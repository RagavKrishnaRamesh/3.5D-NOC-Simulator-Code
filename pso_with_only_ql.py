"""Threaded PSO + Q-learning only, without DP or fitness memoization.

States are SHA-256 hashes of complete repaired particles. Actions are ordered
tuples of concrete mapping/TSV swaps, not names of mutation strategies.
"""

import argparse
import copy
import hashlib
import json
import math
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor

import pso_3p5d as pso

Q_LEARNING_ALPHA = 0.15
Q_LEARNING_GAMMA = 0.90
Q_LEARNING_EPSILON = 0.10


def q_state_key(particle_state):
    payload = json.dumps(particle_state, separators=(",", ":"), sort_keys=True, allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_swap_action(state, action):
    mapping_size = sum(len(chip[0]) for chip in state)
    for swap in action:
        if len(swap) != 4:
            raise ValueError("Each swap must be (target, chip_index, i, j)")
        target, chip, i, j = swap
        if not all(type(value) is int for value in (chip, i, j)):
            raise ValueError("Swap indices must be integers")
        if target == "mapping" and chip == -1:
            size = mapping_size
        elif target == "tsv" and 0 <= chip < len(state) and len(state[chip]) == 4:
            size = len(state[chip][1])
        else:
            raise ValueError("Unknown swap target or chip index")
        if not (0 <= i < size and 0 <= j < size and i != j):
            raise ValueError("Swap index out of range or identical indices")


def apply_swap_action(state, action, chiplet_layout):
    """Apply the exact sequence in order; repair is a separate transition step."""
    validate_swap_action(state, action)
    result = copy.deepcopy(state)
    mapping = pso.flatten_particle_mapping(result)
    for target, chip, i, j in action:
        values = mapping if target == "mapping" else result[chip][1]
        values[i], values[j] = values[j], values[i]
    pso.restore_particle_mapping(result, chiplet_layout, mapping)
    return result


def build_swap_actions(particle, personal_best, global_best, chiplet_layout,
                       max_swaps=8, rng=None):
    if max_swaps < 1:
        raise ValueError("max_swaps must be positive")
    rng = rng or pso.random
    mapping = pso.flatten_particle_mapping(particle.state)
    actions = [()]  # A valid no-op gives the learner the option to keep the PSO proposal.
    for guide in (personal_best, global_best):
        swaps = pso.find_swap_sequence(mapping, pso.flatten_particle_mapping(guide.state))
        if swaps:
            actions.append(tuple(("mapping", -1, i, j) for i, j in swaps[:max_swaps]))
    if particle.mapping_velocity:
        actions.append(tuple(("mapping", -1, i, j) for i, j in particle.mapping_velocity[:max_swaps]))
    if len(mapping) > 1:
        for count in (1, min(3, max_swaps)):
            swaps = [tuple(rng.sample(range(len(mapping)), 2)) for _ in range(count)]
            actions.append(tuple(("mapping", -1, i, j) for i, j in swaps))
    for chip, layout in enumerate(chiplet_layout):
        if layout["type"] != "3d":
            continue
        placement = particle.state[chip][1]
        for guide in (personal_best, global_best):
            target = guide.state[chip][1]
            # Pair mismatched bits; swaps preserve the number of TSV columns.
            ones = [i for i, (a, b) in enumerate(zip(placement, target)) if a == 1 and b == 0]
            zeros = [i for i, (a, b) in enumerate(zip(placement, target)) if a == 0 and b == 1]
            swaps = tuple(("tsv", chip, i, j) for i, j in list(zip(ones, zeros))[:max_swaps])
            if swaps:
                actions.append(swaps)
        ones = [i for i, value in enumerate(placement) if value == 1]
        zeros = [i for i, value in enumerate(placement) if value == 0]
        if ones and zeros:
            actions.append((("tsv", chip, rng.choice(ones), rng.choice(zeros)),))
    # Sample all legal sequence lengths and targets with positive probability.
    # PSO-guided proposals are a behavior policy, not a changing action space.
    targets = [("mapping", -1, len(mapping))]
    targets.extend(("tsv", i, len(particle.state[i][1])) for i, chip in enumerate(chiplet_layout)
                   if chip["type"] == "3d")
    targets = [target for target in targets if target[2] > 1]
    if targets:
        sequence = []
        for _ in range(rng.randint(1, max_swaps)):
            target, chip, size = rng.choice(targets)
            i, j = rng.sample(range(size), 2)
            sequence.append((target, chip, i, j))
        actions.append(tuple(sequence))
    return list(dict.fromkeys(actions))


def q_action_count(particle_state, max_swaps):
    """Finite action space: no-op plus every indexed sequence up to the limit."""
    n = len(pso.flatten_particle_mapping(particle_state))
    primitives = n * (n - 1)
    primitives += sum(len(chip[1]) * (len(chip[1]) - 1) for chip in particle_state if len(chip) == 4)
    return 1 + sum(primitives ** k for k in range(1, max_swaps + 1))


def q_choose_action(q_table, state_key, actions, epsilon=Q_LEARNING_EPSILON, rng=None):
    rng = rng or pso.random
    if not actions:
        raise ValueError("At least one feasible swap sequence is required")
    if rng.random() < epsilon:
        return rng.choice(actions)
    row = q_table.get(state_key, {})
    best = max(row.get(action, 0.0) for action in actions)
    return rng.choice([action for action in actions if row.get(action, 0.0) == best])


def q_update_value(q_table, state_key, action, reward, next_state_key,
                   alpha=Q_LEARNING_ALPHA, gamma=Q_LEARNING_GAMMA, terminal=False,
                   next_action_count=None):
    next_row = q_table.get(next_state_key, {})
    values = list(next_row.values())
    # Include zero only for a genuinely untried action. Learned negative
    # values must not be clamped to zero once all feasible actions are known.
    if next_action_count is None or len(next_row) < next_action_count:
        values.append(0.0)
    best_next = 0.0 if terminal else max(values, default=0.0)
    row = q_table.setdefault(state_key, {})
    old = row.get(action, 0.0)
    row[action] = old + alpha * (reward + gamma * best_next - old)
    return row[action]


def _evaluate_task(task):
    return pso.evaluate_particle_state(*task)


def evaluate_particles(particles, chiplet_layout, router_coordinates, edge_file, executor=None):
    # Every particle is evaluated, including duplicate states. There is no
    # DP/fitness cache in this variant; Q values are policy memory only.
    tasks = [(particle.state, chiplet_layout, router_coordinates, edge_file) for particle in particles]
    metrics = map(_evaluate_task, tasks) if executor is None else executor.map(_evaluate_task, tasks)
    for particle, values in zip(particles, metrics):
        particle.fitness_value, particle.cost, particle.variance, particle.var_up, particle.var_down = values
        if not all(math.isfinite(value) for value in values):
            raise ValueError("Particle evaluation returned non-finite metrics")


def particle_output_path(graph_name):
    name = os.path.splitext(os.path.basename(str(graph_name)))[0]
    match = re.fullmatch(r"Graph(\d+)", name, re.IGNORECASE)
    suffix = match.group(1) if match else "_" + re.sub(r"[^A-Za-z0-9_.-]+", "_", name)
    return os.path.join("Particles", f"PSO_QL_Particle{suffix}.txt")


def _resolve_workers(requested, swarm_size):
    requested = requested if requested is not None else os.environ.get("PSO_WORKERS")
    workers = int(requested) if requested is not None else min(os.cpu_count() or 1, swarm_size, 4)
    if workers < 1:
        raise ValueError("parallel_workers must be positive")
    return min(workers, swarm_size)


def _update_bests(particles, personal_best, global_best):
    for index, particle in enumerate(particles):
        if particle.fitness_value < personal_best[index].fitness_value:
            personal_best[index] = particle.clone()
        if particle.fitness_value < global_best.fitness_value:
            global_best = particle.clone()
    return global_best


def run_pso_3p5d(graph_name, chip_rows, chip_cols, two5d_width, threeD_height,
                 num_2p5d_units, num_3d_units, iterations, swarm_size,
                 tsv_assignment_mode=pso.TSV_ASSIGNMENT_RANDOM, seed=None,
                 parallel_workers=None, print_interval=None,
                 q_alpha=Q_LEARNING_ALPHA, q_gamma=Q_LEARNING_GAMMA,
                 q_epsilon=Q_LEARNING_EPSILON, max_swaps=8):
    if swarm_size < 1 or iterations < 0 or max_swaps < 1:
        raise ValueError("Use positive swarm_size/max_swaps and non-negative iterations")
    if not (0 < q_alpha <= 1 and 0 <= q_gamma <= 1 and 0 <= q_epsilon <= 1):
        raise ValueError("Require 0 < alpha <= 1, 0 <= gamma <= 1, 0 <= epsilon <= 1")
    if pso.create_edge_set is None:
        raise RuntimeError("edge_set_creation.create_edge_set is unavailable")
    worker_count = _resolve_workers(parallel_workers, swarm_size)
    print_interval = int(os.environ.get("PSO_PRINT_INTERVAL", 10) if print_interval is None else print_interval)
    if print_interval < 1:
        raise ValueError("print_interval must be positive")
    pso.RANDOM_SEED = int(time.time()) if seed is None else int(seed)
    pso.TSV_ASSIGNMENT_MODE = pso._validate_tsv_assignment_mode(tsv_assignment_mode)
    pso.random.seed(pso.RANDOM_SEED)
    start = time.perf_counter()
    layout, total_routers = pso.build_topology(chip_rows, chip_cols, two5d_width, threeD_height,
                                               num_2p5d_units, num_3d_units)
    edge_file = pso.edge_set_output_path(graph_name)
    pso.create_edge_set(pso.graph_input_path(graph_name), edge_file)
    coordinates = pso.assign_router_coordinates(total_routers)
    pso.init_normalization_terms(graph_name, edge_file, threeD_height)
    print(f"PSO_QL: seed={pso.RANDOM_SEED}, threads={worker_count}, DP=off, fitness_cache=off")
    executor = ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="pso-ql") if worker_count > 1 else None
    q_table = {}
    updates = 0
    total_reward = 0.0
    completed = 0
    try:
        particles = [pso.Particle3p5d(layout, coordinates, edge_file, list(range(total_routers)),
                                     evaluate_initial=False) for _ in range(swarm_size)]
        evaluate_particles(particles, layout, coordinates, edge_file, executor)
        personal_best = [particle.clone() for particle in particles]
        global_best = min(personal_best, key=lambda particle: particle.fitness_value).clone()
        stalled = 0
        for iteration in range(iterations):
            previous_best = global_best.fitness_value
            # PSO proposes a full move. Evaluate it before the Q move so its
            # improvement is not mistakenly credited to the chosen Q action.
            for index, particle in enumerate(particles):
                pso.update_particle(particle, personal_best[index], global_best, layout, coordinates, edge_file)
            evaluate_particles(particles, layout, coordinates, edge_file, executor)
            global_best = _update_bests(particles, personal_best, global_best)
            transitions = []
            for index, particle in enumerate(particles):
                state = q_state_key(particle.state)
                actions = build_swap_actions(particle, personal_best[index], global_best, layout, max_swaps)
                # Revisit learned concrete sequences even when current PSO guides
                # no longer propose them. Exact particle hashes preserve validity.
                actions = list(dict.fromkeys([*actions, *q_table.get(state, {})]))
                action = q_choose_action(q_table, state, actions, q_epsilon)
                transitions.append((state, action, particle.fitness_value))
                if action:
                    proposed = apply_swap_action(particle.state, action, layout)
                    particle.state = pso.repair_particle_state(proposed, layout, coordinates, edge_file)
            evaluate_particles(particles, layout, coordinates, edge_file, executor)
            # Coordinator-only updates avoid races in the Q table and random RNG.
            for particle, (state, action, old_fitness) in zip(particles, transitions):
                reward = old_fitness - particle.fitness_value
                q_update_value(q_table, state, action, reward, q_state_key(particle.state),
                               q_alpha, q_gamma,
                               next_action_count=q_action_count(particle.state, max_swaps))
                updates += 1
                total_reward += reward
            global_best = _update_bests(particles, personal_best, global_best)
            completed = iteration + 1
            stalled = stalled + 1 if global_best.fitness_value >= previous_best else 0
            if completed == 1 or completed == iterations or completed % print_interval == 0:
                print(f"Iteration {completed}: cost={global_best.cost:.6f}, fitness={global_best.fitness_value:.6f}, Q states={len(q_table)}")
            if stalled >= pso.CONVERGENCE_STALL_LIMIT:
                print(f"Early stopping after {completed} iterations")
                break
    finally:
        if executor is not None:
            executor.shutdown(wait=True)
    output = particle_output_path(graph_name)
    q_output = os.path.splitext(output)[0] + ".qtable.json"
    metadata = {"algorithm": "PSO_QL", "backend": "threads", "workers": worker_count,
                "dp": False, "fitness_cache": False, "q_state": "sha256_complete_repaired_particle",
                "q_action": "ordered_swap_sequence", "q_alpha": q_alpha, "q_gamma": q_gamma,
                "q_epsilon": q_epsilon, "max_swaps": max_swaps, "q_updates": updates,
                "q_states": len(q_table), "q_total_reward": total_reward,
                "iterations_completed": completed, "q_table_file": q_output,
                "q_environment": "continuing_particle_edit_mdp",
                "iteration_limit_is_truncation": True}
    pso.write_particle_file(output, graph_name, chip_rows, chip_cols, two5d_width, threeD_height,
                            num_2p5d_units, num_3d_units, global_best.state, layout, global_best.cost,
                            global_best.fitness_value, global_best.variance, global_best.var_up, global_best.var_down,
                            optimizer_metadata=metadata)
    with open(q_output, "w", encoding="utf-8") as handle:
        json.dump({"schema_version": 1, "graph": graph_name, "seed": pso.RANDOM_SEED,
                   "action_format": "[target, chip_index, i, j]; mapping uses chip_index=-1",
                   "states": {state: [{"swaps": action, "value": value} for action, value in row.items()]
                              for state, row in q_table.items()}}, handle, indent=2, allow_nan=False)
        handle.write("\n")
    print(f"PSO_QL best cost={global_best.cost:.6f}, fitness={global_best.fitness_value:.6f}")
    print(f"Q updates={updates}, states={len(q_table)}, elapsed={time.perf_counter() - start:.3f}s")
    print(f"Particle: {output}\nQ table: {q_output}")
    return global_best.state, global_best.cost


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("graph_name")
    for name in ("chip_rows", "chip_cols", "two5d_width", "threeD_height", "num_2p5d_units",
                 "num_3d_units", "iterations", "swarm_size"):
        parser.add_argument(name, type=int)
    parser.add_argument("tsv_assignment_mode", type=int, choices=(0, 1))
    parser.add_argument("--seed", type=int)
    parser.add_argument("--parallel-workers", type=int, help="Fitness worker threads; default min(cpu_count, swarm_size, 4)")
    parser.add_argument("--print-interval", type=int)
    parser.add_argument("--q-alpha", type=float, default=Q_LEARNING_ALPHA)
    parser.add_argument("--q-gamma", type=float, default=Q_LEARNING_GAMMA)
    parser.add_argument("--q-epsilon", type=float, default=Q_LEARNING_EPSILON)
    parser.add_argument("--max-swaps", type=int, default=8)
    run_pso_3p5d(**vars(parser.parse_args()))


if __name__ == "__main__":
    main()
