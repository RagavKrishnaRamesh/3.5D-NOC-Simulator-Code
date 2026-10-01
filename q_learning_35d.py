"""
Q-learning based 3.5D NoC / Multi-Chiplet Topology Optimizer.

The optimizer reuses the same topology, repair, fitness, and particle writer
used by the SA flow. Q-learning selects which neighborhood operator to apply:
mapping swap, mapping reversal, TSV flip, or attach-point move.

Usage:
  python q_learning_35d.py <GraphNameWithoutExt>
                           <chip_rows> <chip_cols>
                           <two5d_width> <threeD_height>
                           <num_2p5d_units> <num_3d_units>
                           <iterations> <population_size>
                           <tsv_assignment_mode>
"""

import argparse
import os
import random
import re
import time
from copy import deepcopy
from dataclasses import dataclass, field

import sa_3p5d as sa


ACTION_SWAP_MAPPING = "swap_mapping"
ACTION_REVERSE_MAPPING = "reverse_mapping"
ACTION_FLIP_TSV = "flip_tsv"
ACTION_MOVE_ATTACH = "move_attach"
DEFAULT_ACTIONS = (
    ACTION_SWAP_MAPPING,
    ACTION_REVERSE_MAPPING,
    ACTION_FLIP_TSV,
    ACTION_MOVE_ATTACH,
)


@dataclass
class QLearningParams:
    alpha: float = 0.35
    gamma: float = 0.85
    epsilon_start: float = 0.40
    epsilon_min: float = 0.05
    epsilon_decay: float = 0.995
    stagnation_patience: int = 100
    accept_worse_scale: float = 0.20
    actions: tuple = field(default_factory=lambda: DEFAULT_ACTIONS)


def particle_output_path(graph_name):
    match = re.search(r"(\d+)$", graph_name)
    if match and graph_name.lower().startswith("graph"):
        return os.path.join("Particles", f"QL_Particle{match.group(1)}.txt")
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", graph_name.strip()) or "graph"
    return os.path.join("Particles", f"QL_Particle_{safe}.txt")


def _validate_chromosome(chromosome, chiplet_layout, router_coordinates, edge_set_file):
    chromosome = sa.fix_core_to_router_mapping_3p5d(chromosome, chiplet_layout)
    chromosome = sa.validate_tsv_placement_3p5d(chromosome, chiplet_layout, router_coordinates)
    chromosome = sa.validate_tsv_assignment_3p5d(
        chromosome, chiplet_layout, router_coordinates, edge_set_file
    )
    return chromosome


def _random_initial_chromosome(chiplet_layout, router_coordinates, edge_set_file, total_routers):
    chromosome = sa.generate_chromosome_3p5d(chiplet_layout, list(range(total_routers)))
    return _validate_chromosome(chromosome, chiplet_layout, router_coordinates, edge_set_file)


def _flatten_core_to_router(chromosome, chiplet_layout):
    flat = []
    for chip_idx, chip in enumerate(chiplet_layout):
        flat.extend(chromosome[chip_idx][0])
    return flat


def _unflatten_core_to_router(flat, chromosome, chiplet_layout):
    idx = 0
    for chip_idx, chip in enumerate(chiplet_layout):
        n = chip["no_routers"]
        chromosome[chip_idx][0] = flat[idx:idx + n]
        idx += n


def _mutate_swap_mapping(child, chiplet_layout):
    flat = _flatten_core_to_router(child, chiplet_layout)
    if len(flat) >= 2:
        i, j = random.sample(range(len(flat)), 2)
        flat[i], flat[j] = flat[j], flat[i]
    _unflatten_core_to_router(flat, child, chiplet_layout)


def _mutate_reverse_mapping(child, chiplet_layout):
    flat = _flatten_core_to_router(child, chiplet_layout)
    if len(flat) >= 4:
        i = random.randrange(0, len(flat) - 1)
        j = random.randrange(i + 1, len(flat))
        flat[i:j] = reversed(flat[i:j])
    else:
        _mutate_swap_mapping(child, chiplet_layout)
        return
    _unflatten_core_to_router(flat, child, chiplet_layout)


def _mutate_flip_tsv(child, chiplet_layout):
    three_d_indices = [i for i, chip in enumerate(chiplet_layout) if chip["type"] == "3d"]
    if not three_d_indices:
        _mutate_swap_mapping(child, chiplet_layout)
        return
    chip_idx = random.choice(three_d_indices)
    chip = chiplet_layout[chip_idx]
    routers_per_level = chip["no_routers"] // chip["no_levels"]
    bit = random.randrange(routers_per_level)
    child[chip_idx][1][bit] = 1 - child[chip_idx][1][bit]
    child[chip_idx][2] = [0] * chip["no_routers"]


def _mutate_move_attach(child, chiplet_layout):
    chip_idx = random.randrange(len(chiplet_layout))
    chip = chiplet_layout[chip_idx]
    if chip["type"] == "3d":
        routers_per_level = chip["no_routers"] // chip["no_levels"]
        child[chip_idx][3] = random.randrange(routers_per_level)
    else:
        local_rows = chip["interposer"]["rows"]
        local_cols = chip["interposer"]["cols"]
        child[chip_idx][1] = random.randrange(local_rows * local_cols)


def _apply_action(chromosome, action, chiplet_layout, router_coordinates, edge_set_file):
    child = deepcopy(chromosome)
    if action == ACTION_SWAP_MAPPING:
        _mutate_swap_mapping(child, chiplet_layout)
    elif action == ACTION_REVERSE_MAPPING:
        _mutate_reverse_mapping(child, chiplet_layout)
    elif action == ACTION_FLIP_TSV:
        _mutate_flip_tsv(child, chiplet_layout)
    elif action == ACTION_MOVE_ATTACH:
        _mutate_move_attach(child, chiplet_layout)
    else:
        raise ValueError(f"Unsupported Q-learning action: {action}")
    return _validate_chromosome(child, chiplet_layout, router_coordinates, edge_set_file)


def _state_key(current_e, best_e, stall_count):
    denom = max(abs(best_e), 1e-12)
    relative_gap = max(0.0, (current_e - best_e) / denom)
    if relative_gap < 0.01:
        fitness_bucket = 0
    elif relative_gap < 0.05:
        fitness_bucket = 1
    elif relative_gap < 0.15:
        fitness_bucket = 2
    else:
        fitness_bucket = 3

    if stall_count < 10:
        stall_bucket = 0
    elif stall_count < 40:
        stall_bucket = 1
    elif stall_count < 100:
        stall_bucket = 2
    else:
        stall_bucket = 3
    return (fitness_bucket, stall_bucket)


def _q_value(q_table, state, action):
    return q_table.get((state, action), 0.0)


def _choose_action(q_table, state, actions, epsilon):
    if random.random() < epsilon:
        return random.choice(actions)
    best_value = max(_q_value(q_table, state, action) for action in actions)
    best_actions = [
        action for action in actions
        if _q_value(q_table, state, action) == best_value
    ]
    return random.choice(best_actions)


def _update_q_value(q_table, state, action, reward, next_state, actions, params):
    old_value = _q_value(q_table, state, action)
    next_best = max(_q_value(q_table, next_state, next_action) for next_action in actions)
    q_table[(state, action)] = old_value + params.alpha * (
        reward + params.gamma * next_best - old_value
    )


def _energy(chromosome, chiplet_layout, router_coordinates, edge_set_file):
    eff, *_ = sa.fitness_terms_3p5d(
        chromosome, chiplet_layout, router_coordinates, edge_set_file
    )
    return eff


def run_q_learning_35d(
    graph_name,
    chip_rows,
    chip_cols,
    two5d_width,
    threeD_height,
    num_2p5d_units,
    num_3d_units,
    iterations,
    population_size,
    q_params=None,
    tsv_assignment_mode=sa.TSV_ASSIGNMENT_RANDOM,
    seed=None,
):
    if q_params is None:
        q_params = QLearningParams()

    seed_value = int(time.time()) if seed is None else int(seed)
    sa.RANDOM_SEED = seed_value
    sa.TSV_ASSIGNMENT_MODE = sa._validate_tsv_assignment_mode(tsv_assignment_mode)
    random.seed(seed_value)
    print(f"Using random seed: {seed_value}")
    print(f"Using TSV assignment mode: {sa._tsv_assignment_mode_name()}")
    print(
        "Using Q-learning: "
        f"alpha={q_params.alpha}, gamma={q_params.gamma}, "
        f"epsilon={q_params.epsilon_start}->{q_params.epsilon_min}"
    )

    start_time = time.time()
    chiplet_layout, total_routers = sa.build_topology(
        chip_rows,
        chip_cols,
        two5d_width,
        threeD_height,
        num_2p5d_units,
        num_3d_units,
    )

    input_graph = sa.graph_input_path(graph_name)
    edge_set_file = sa.edge_set_output_path(graph_name)
    if sa.create_edge_set is not None:
        sa.create_edge_set(input_graph, edge_set_file)
    else:
        sa._fallback_create_edge_set(input_graph, edge_set_file)

    router_coordinates = sa.assign_router_coordinates(total_routers)
    sa.init_normalization_terms(graph_name, edge_set_file, threeD_height)

    pool_n = max(1, int(population_size))
    init_pool = [
        _random_initial_chromosome(
            chiplet_layout, router_coordinates, edge_set_file, total_routers
        )
        for _ in range(pool_n)
    ]

    current = min(
        init_pool,
        key=lambda chrom: _energy(chrom, chiplet_layout, router_coordinates, edge_set_file),
    )
    current_e = _energy(current, chiplet_layout, router_coordinates, edge_set_file)
    best = deepcopy(current)
    best_e = current_e
    q_table = {}
    epsilon = q_params.epsilon_start
    stall_count = 0
    total_steps = max(1, int(iterations))

    for step in range(total_steps):
        state = _state_key(current_e, best_e, stall_count)
        action = _choose_action(q_table, state, q_params.actions, epsilon)
        candidate = _apply_action(
            current, action, chiplet_layout, router_coordinates, edge_set_file
        )
        candidate_e = _energy(candidate, chiplet_layout, router_coordinates, edge_set_file)

        improvement = current_e - candidate_e
        improved_best = candidate_e < best_e
        reward = improvement / max(abs(current_e), 1e-12)
        if improved_best:
            reward += 1.0
        elif improvement <= 0.0:
            reward -= 0.02

        accept_worse_prob = max(q_params.epsilon_min, epsilon) * q_params.accept_worse_scale
        if improvement >= 0.0 or random.random() < accept_worse_prob:
            current = candidate
            current_e = candidate_e

        if improved_best:
            best = deepcopy(candidate)
            best_e = candidate_e
            stall_count = 0
        else:
            stall_count += 1

        next_state = _state_key(current_e, best_e, stall_count)
        _update_q_value(q_table, state, action, reward, next_state, q_params.actions, q_params)
        epsilon = max(q_params.epsilon_min, epsilon * q_params.epsilon_decay)

        if (step + 1) >= max(50, q_params.stagnation_patience):
            if stall_count >= q_params.stagnation_patience:
                print(
                    f"Early stopping at iteration {step + 1} after "
                    f"{q_params.stagnation_patience} stagnant iterations without improvement."
                )
                break

        if total_steps <= 20000 or (step + 1) % 200 == 0:
            _, cost, var, _, _ = sa.fitness_terms_3p5d(
                best, chiplet_layout, router_coordinates, edge_set_file
            )
            print(
                f"Iteration {step + 1}: Best Fitness = {best_e:.6f} | "
                f"Cost={cost:.6f} | Var={var:.6f} | eps={epsilon:.4f} | "
                f"action={action}"
            )

    end_time = time.time()
    eff, cost, var, var_up, var_down = sa.fitness_terms_3p5d(
        best, chiplet_layout, router_coordinates, edge_set_file
    )

    print("\n=== 3.5D Q-Learning Result ===")
    print(f"Graph:         {graph_name}")
    print(f"Total routers: {total_routers}")
    print(f"Best cost:     {cost:.6f}")
    print(f"Best fitness:  {eff:.6f}")
    print(f"TSV var up:    {var_up:.6f}")
    print(f"TSV var down:  {var_down:.6f}")
    print(f"TSV var max:   {var:.6f}")
    print(f"Q states:      {len({state for state, _ in q_table})}")
    print(f"Real time:     {end_time - start_time:.2f} s")

    particle_path = particle_output_path(graph_name)
    sa.write_particle_file(
        particle_path,
        graph_name,
        chip_rows,
        chip_cols,
        two5d_width,
        threeD_height,
        num_2p5d_units,
        num_3d_units,
        best,
        chiplet_layout,
        cost,
        eff,
        var,
        var_up,
        var_down,
    )

    return best, cost


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("graph_name")
    parser.add_argument("chip_rows", type=int)
    parser.add_argument("chip_cols", type=int)
    parser.add_argument("two5d_width", type=int)
    parser.add_argument("threeD_height", type=int)
    parser.add_argument("num_2p5d_units", type=int)
    parser.add_argument("num_3d_units", type=int)
    parser.add_argument("iterations", type=int)
    parser.add_argument("population_size", type=int)
    parser.add_argument(
        "tsv_assignment_mode",
        type=int,
        choices=[0, 1],
        help="TSV assignment mode: 0=elevator_first, 1=redelf_random",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for Q-learning. Omit to use the current system time.",
    )
    args = parser.parse_args()
    run_q_learning_35d(
        args.graph_name,
        args.chip_rows,
        args.chip_cols,
        args.two5d_width,
        args.threeD_height,
        args.num_2p5d_units,
        args.num_3d_units,
        args.iterations,
        args.population_size,
        tsv_assignment_mode=args.tsv_assignment_mode,
        seed=args.seed,
    )


if __name__ == "__main__":
    main()
