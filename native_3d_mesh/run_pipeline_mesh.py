#!/usr/bin/env python3
"""Full pipeline variant that emits native 3D mesh topology YAML."""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import run_pipeline as legacy
from native_3d_mesh.run_simulator_mesh import run_simulation


def main():
    legacy.os.chdir(REPO_ROOT)
    args = legacy.parse_args()
    algorithm = legacy._normalize_algorithm(args.algorithm)
    mode = legacy._normalize_mode(args.mode)
    graph_name, graph_path, graph_number = legacy._graph_name_and_path(args.graph)

    particle_path, optimizer_runtime = legacy._run_optimizer(
        algorithm,
        graph_name,
        args,
        mode,
    )

    sim_seed = args.sim_seed if args.sim_seed is not None else args.seed
    sim_start = legacy.time.perf_counter()
    sim_result = run_simulation(
        particle_path,
        graph_path,
        noxim=args.noxim,
        seed=sim_seed,
        power=args.power,
        id_space=args.id_space,
        directed=args.directed,
        use_wsl=args.use_wsl,
    )
    simulation_time = legacy.time.perf_counter() - sim_start
    metrics = legacy._parse_simulation_metrics(sim_result["log"])
    optimizer_metrics = legacy._read_optimizer_metrics(particle_path)

    csv_path = REPO_ROOT / "native_3d_mesh" / f"RUN_{legacy.datetime.now().strftime('%d%m%y')}.csv"
    row = {
        "Graph": graph_number,
        "Algorithm": algorithm,
        "Dimension": legacy._dimension_text(args),
        "Population": args.population,
        "Iterations": args.iterations,
        "Runtime": optimizer_runtime,
        "Simulation Time": simulation_time,
    }
    row.update(optimizer_metrics)
    written_csv_path = legacy._append_csv(row, metrics, csv_path)

    print(f"Particle: {particle_path}")
    print(f"YAML: {sim_result['yaml']}")
    print(f"Traffic Table: {sim_result['traffic_table']}")
    print(f"Log: {sim_result['log']}")
    print(f"CSV: {written_csv_path}")


if __name__ == "__main__":
    main()
