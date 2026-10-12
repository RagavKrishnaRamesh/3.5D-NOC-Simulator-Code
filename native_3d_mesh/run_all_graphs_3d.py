#!/usr/bin/env python3
"""Run native 3D mesh PSO on all or k random graphs using pure-3D dimensions."""

import argparse
import random
from datetime import datetime
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from native_3d_mesh import run_all_mesh_graphs as runner

runner.ALGORITHMS = ["PSO"]
runner.SEED = 10
runner.SIM_SEED = 10
DEFAULT_SAMPLE_SEED = 10


def dims_for_core_count_3d(core_count):
    if core_count <= 8:
        chiprows, chipcols, threedheight = 2, 2, 2
    elif core_count <= 16:
        chiprows, chipcols, threedheight = 2, 2, 4
    elif core_count <= 27:
        chiprows, chipcols, threedheight = 3, 3, 3
    elif core_count <= 32:
        chiprows, chipcols, threedheight = 4, 4, 2
    elif core_count <= 64:
        chiprows, chipcols, threedheight = 4, 4, 4
    elif core_count <= 128:
        chiprows, chipcols, threedheight = 4, 4, 8
    else:
        return None

    return {
        "chiprows": chiprows,
        "chipcols": chipcols,
        "num3d": 1,
        "num2p5d": 0,
        "threedheight": threedheight,
        "two5dwidth": 1,
    }


def eligible_graphs():
    graph_paths = sorted((REPO_ROOT / "Graphs").glob("Graph*.txt"), key=runner.graph_sort_key)
    if not graph_paths:
        raise SystemExit("No Graph*.txt files found under Graphs/")

    selected = []
    skipped = []
    for graph_path in graph_paths:
        core_count = runner.read_core_count(graph_path)
        if core_count < runner.MIN_CORE_COUNT:
            skipped.append((graph_path, core_count, f"less than {runner.MIN_CORE_COUNT}"))
            continue
        if dims_for_core_count_3d(core_count) is None:
            skipped.append((graph_path, core_count, "exceeds 128"))
            continue
        selected.append((graph_path, core_count))
    return selected, skipped


def choose_graphs(graphs, k, sample_seed):
    if k is None:
        return graphs
    if k < 0:
        raise ValueError("k must be non-negative")
    if k >= len(graphs):
        return graphs

    rng = random.Random(sample_seed)
    return sorted(rng.sample(graphs, k), key=lambda item: runner.graph_sort_key(item[0]))


def run_batch_3d(results_start_time, k=None, sample_seed=None):
    runner.ALGORITHMS = ["PSO"]

    if runner.MODE not in {"elevator", "random"}:
        raise ValueError("MODE must be elevator or random")

    graphs, skipped = eligible_graphs()
    graphs = choose_graphs(graphs, k, sample_seed)

    print("Results CSVs:")
    for algorithm in runner.ALGORITHMS:
        print(
            f"  native_3d_mesh/RESULTS_{runner.MODE}_"
            f"{algorithm.lower()}_{results_start_time}.csv"
        )
    if k is not None:
        print(f"Random graph sample: k={k}, seed={sample_seed}, selected={len(graphs)}")

    failures = []
    total = 0

    for graph_path, core_count in graphs:
        dims = dims_for_core_count_3d(core_count)
        for algorithm in runner.ALGORITHMS:
            total += 1
            cmd = runner.build_command(algorithm, graph_path, dims, results_start_time)
            print(
                f"\nRUN {algorithm} {graph_path.name}: cores={core_count} "
                f"dims={dims}"
            )
            print(" ".join(cmd))

            if runner.DRY_RUN:
                continue

            result = runner.subprocess.run(cmd, cwd=REPO_ROOT, check=False)
            if result.returncode != 0:
                failures.append((algorithm, graph_path.name, result.returncode))
                print(
                    f"FAILED {algorithm} {graph_path.name}: "
                    f"exit code {result.returncode}"
                )
                if runner.STOP_ON_FAILURE:
                    raise SystemExit(result.returncode)

    print("\nBatch complete")
    print(f"Runs attempted: {total}")
    print(f"Skipped graphs: {len(skipped)}")
    print(f"Failures: {len(failures)}")
    if skipped:
        for path, cores, reason in skipped:
            print(f"  skipped {path.name}: {cores} cores {reason}")
    if failures:
        for algorithm, name, code in failures:
            print(f"  failed {algorithm} {name}: exit code {code}")
        raise SystemExit(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "k",
        nargs="?",
        type=int,
        help="Pick k random eligible graphs. Omit to run every eligible graph.",
    )
    parser.add_argument(
        "--sample-seed",
        type=int,
        default=DEFAULT_SAMPLE_SEED,
        help="Seed used only for selecting the k random graphs.",
    )
    parser.add_argument(
        "--results-start-time",
        help="Reuse a results CSV from an earlier batch (YYYYMMDD_HHMMSS)",
    )
    args = parser.parse_args()

    results_start_time = args.results_start_time or datetime.now().strftime("%Y%m%d_%H%M%S")
    try:
        parsed_start_time = datetime.strptime(results_start_time, "%Y%m%d_%H%M%S")
    except ValueError:
        parser.error("--results-start-time must be YYYYMMDD_HHMMSS")
    if parsed_start_time.strftime("%Y%m%d_%H%M%S") != results_start_time:
        parser.error("--results-start-time must be YYYYMMDD_HHMMSS")

    with runner.batch_lock():
        run_batch_3d(results_start_time, k=args.k, sample_seed=args.sample_seed)


if __name__ == "__main__":
    main()
