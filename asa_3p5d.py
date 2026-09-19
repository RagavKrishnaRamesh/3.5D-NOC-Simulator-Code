#!/usr/bin/env python3
import argparse
import math
import os
import random
import re
import time
from copy import deepcopy

import sa_3p5d as sa


class ASAParams(sa.SAParams):
    # Defaults for adaptive simulated annealing on the 3.5D topology.
    def __init__(self):
        super().__init__()
        self.ADAPT_INTERVAL = 100
        self.TARGET_ACCEPTANCE = 0.40
        self.ACCEPT_TOLERANCE = 0.05
        self.HEAT_FACTOR = 1.20
        self.COOL_FACTOR = 0.80
        self.REHEAT_FACTOR = 1.35
        self.REHEAT_PATIENCE = 500
        self.MAX_REHEATS = 8


def _adapt_temperature(T, accept_ratio, asa_params):
    target = asa_params.TARGET_ACCEPTANCE
    if accept_ratio < target - asa_params.ACCEPT_TOLERANCE:
        return T * asa_params.HEAT_FACTOR
    if accept_ratio > target + asa_params.ACCEPT_TOLERANCE:
        return T * asa_params.COOL_FACTOR
    return T


def _maybe_reheat(T, stall_count, reheats, initial_T, asa_params):
    if stall_count < asa_params.REHEAT_PATIENCE:
        return T, stall_count, reheats
    if reheats >= asa_params.MAX_REHEATS:
        return T, stall_count, reheats
    if T >= initial_T:
        return T, stall_count, reheats
    T = min(initial_T, T * asa_params.REHEAT_FACTOR)
    return T, 0, reheats + 1


def run_asa_3p5d(
    graph_name,
    chip_rows,
    chip_cols,
    two5d_width,
    threeD_height,
    num_2p5d_units,
    num_3d_units,
    iterations,
    population_size,
    asa_params=None,
    tsv_assignment_mode=sa.TSV_ASSIGNMENT_RANDOM,
    seed=None,
):
    if asa_params is None:
        asa_params = ASAParams()
    asa_params.MAX_STEPS = iterations

    seed_value = int(time.time()) if seed is None else int(seed)
    sa.RANDOM_SEED = seed_value
    sa.TSV_ASSIGNMENT_MODE = sa._validate_tsv_assignment_mode(tsv_assignment_mode)
    random.seed(seed_value)

    print(f'Using random seed: {seed_value}')
    print(f'Using TSV assignment mode: {sa._tsv_assignment_mode_name()}')
    print(
        'Using adaptive SA: '
        f'interval={asa_params.ADAPT_INTERVAL}, '
        f'target_acceptance={asa_params.TARGET_ACCEPTANCE:.2f}'
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

    tsv_list = list(range(total_routers))
    init_pool = []
    pool_n = max(1, int(population_size))
    for _ in range(pool_n):
        chrom = sa.generate_chromosome_3p5d(chiplet_layout, tsv_list)
        chrom = sa.fix_core_to_router_mapping_3p5d(chrom, chiplet_layout)
        chrom = sa.validate_tsv_placement_3p5d(chrom, chiplet_layout, router_coordinates)
        chrom = sa.validate_tsv_assignment_3p5d(
            chrom,
            chiplet_layout,
            router_coordinates,
            edge_set_file,
        )
        init_pool.append(chrom)

    current = min(
        init_pool,
        key=lambda c: sa._energy(c, chiplet_layout, router_coordinates, edge_set_file, asa_params),
    )
    current_e = sa._energy(current, chiplet_layout, router_coordinates, edge_set_file, asa_params)
    best = deepcopy(current)
    best_e = current_e

    T = sa._estimate_initial_temperature(
        current,
        current_e,
        chiplet_layout,
        router_coordinates,
        edge_set_file,
        asa_params,
    )
    if T <= 0:
        T = asa_params.INIT_TEMP
    initial_T = T

    accepted_window = 0
    proposed_window = 0
    stall_count = 0
    best_snapshot = best_e
    reheats = 0

    for step in range(asa_params.MAX_STEPS):
        cand = sa.perturb_chromosome_sa(
            current,
            chiplet_layout,
            router_coordinates,
            edge_set_file,
            asa_params,
        )
        cand_e = sa._energy(cand, chiplet_layout, router_coordinates, edge_set_file, asa_params)
        delta = cand_e - current_e
        accepted = delta < 0 or random.random() < math.exp(-delta / max(T, 1e-12))
        proposed_window += 1

        if accepted:
            accepted_window += 1
            current = cand
            current_e = cand_e
            if current_e < best_e:
                best = deepcopy(current)
                best_e = current_e

        if best_e < best_snapshot:
            best_snapshot = best_e
            stall_count = 0
        else:
            stall_count += 1

        if (step + 1) % max(1, asa_params.ADAPT_INTERVAL) == 0:
            accept_ratio = accepted_window / max(1, proposed_window)
            T = _adapt_temperature(T, accept_ratio, asa_params)
            accepted_window = 0
            proposed_window = 0

        old_reheats = reheats
        T, stall_count, reheats = _maybe_reheat(
            T,
            stall_count,
            reheats,
            initial_T,
            asa_params,
        )
        if reheats > old_reheats:
            print(f'Reheating at iteration {step + 1}: T={T:.6g}, reheats={reheats}')

        allow_early_stop = (
            (step + 1) >= max(50, asa_params.STAGNATION_PATIENCE)
            and T <= max(asa_params.MIN_TEMP * 10.0, initial_T * 0.10)
        )
        if allow_early_stop and stall_count >= asa_params.STAGNATION_PATIENCE:
            print(
                f'Early stopping at iteration {step + 1} after '
                f'{asa_params.STAGNATION_PATIENCE} stagnant iterations without improvement.'
            )
            break

        T *= asa_params.COOLING_RATE
        if T < asa_params.MIN_TEMP:
            break

        if asa_params.MAX_STEPS <= 20000 or (step + 1) % 200 == 0:
            if asa_params.USE_FITNESS_TERMS:
                _, cost, var, var_up, var_down = sa.fitness_terms_3p5d(
                    best,
                    chiplet_layout,
                    router_coordinates,
                    edge_set_file,
                )
                print(
                    f'Iteration {step + 1}: Best Fitness = {best_e:.6f} | '
                    f'Cost={cost:.6f} | Var={var:.6f} | T={T:.6g}'
                )
            else:
                print(f'Iteration {step + 1}: Best Cost = {best_e:.6f} | T={T:.6g}')

    end_time = time.time()
    if asa_params.USE_FITNESS_TERMS:
        eff, cost, var, var_up, var_down = sa.fitness_terms_3p5d(
            best,
            chiplet_layout,
            router_coordinates,
            edge_set_file,
        )
        best_cost = cost
    else:
        best_cost = best_e
        var_up, var_down = sa.tsv_variance_3p5d(
            best,
            chiplet_layout,
            router_coordinates,
            edge_set_file,
        )
        var = max(var_up, var_down)

    print('\n=== 3.5D Adaptive SA Result ===')
    print(f'Graph:         {graph_name}')
    print(f'Total routers: {total_routers}')
    print(f'Best cost:     {best_cost:.6f}')
    print(f'TSV var up:    {var_up:.6f}')
    print(f'TSV var down:  {var_down:.6f}')
    print(f'TSV var max:   {var:.6f}')
    print(f'Reheats:       {reheats}')
    print(f'Real time:     {end_time - start_time:.2f} s')
    print('\nBest Chromosome (by chiplet):')
    for idx, chip in enumerate(chiplet_layout):
        if chip['type'] == '3d':
            core_to_router, tsv_place, tsv_assign, base_attach = best[idx]
            print(f"  {chip['name']} (3D): VL={chip['vl_coord']}, range={chip['range']}")
            print(f'    Core->Router: {core_to_router}')
            print(f'    TSV place:    {tsv_place}')
            print(f'    TSV assign:   {tsv_assign}')
            print(f'    Base attach router (bottom layer): {base_attach}')
        else:
            core_to_router, base_attach = best[idx]
            print(f"  {chip['name']} (2.5D): VL={chip['vl_coord']}, range={chip['range']}")
            print(f'    Core->Router: {core_to_router}')
            print(f'    Base attach router (local interposer): {base_attach}')

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
        best_cost,
        best_e if asa_params.USE_FITNESS_TERMS else None,
        var,
        var_up,
        var_down,
    )

    return (best, best_cost)


def particle_output_path(graph_name):
    match = re.search(r'(\d+)$', graph_name)
    if match and graph_name.lower().startswith('graph'):
        return os.path.join('Particles', f'ASA_Particle{match.group(1)}.txt')
    safe = re.sub(r'[^A-Za-z0-9_.-]+', '_', graph_name.strip()) or 'graph'
    return os.path.join('Particles', f'ASA_Particle_{safe}.txt')


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
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--adapt-interval", type=int, default=None)
    parser.add_argument("--target-acceptance", type=float, default=None)
    parser.add_argument("--reheat-patience", type=int, default=None)
    parser.add_argument("--max-reheats", type=int, default=None)
    args = parser.parse_args()

    params = ASAParams()
    if args.adapt_interval is not None:
        params.ADAPT_INTERVAL = args.adapt_interval
    if args.target_acceptance is not None:
        params.TARGET_ACCEPTANCE = args.target_acceptance
    if args.reheat_patience is not None:
        params.REHEAT_PATIENCE = args.reheat_patience
    if args.max_reheats is not None:
        params.MAX_REHEATS = args.max_reheats

    run_asa_3p5d(
        args.graph_name,
        args.chip_rows,
        args.chip_cols,
        args.two5d_width,
        args.threeD_height,
        args.num_2p5d_units,
        args.num_3d_units,
        args.iterations,
        args.population_size,
        asa_params=params,
        tsv_assignment_mode=args.tsv_assignment_mode,
        seed=args.seed,
    )


if __name__ == '__main__':
    main()
