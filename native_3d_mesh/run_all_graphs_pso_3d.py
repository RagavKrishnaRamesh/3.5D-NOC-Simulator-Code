#!/usr/bin/env python3
"""Run native 3D mesh PSO for every graph with selected 2-layer or 4-layer meshes."""

import argparse
from datetime import datetime, timedelta
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from native_3d_mesh import run_all_mesh_graphs as runner


runner.ALGORITHMS = ["PSO"]
runner.SEED = 10
runner.SIM_SEED = 10
SIM_BUFFER_DEPTH = 8
SIM_PACKET_SIZE = 8
SIM_STATS_WARM_UP_TIME = 2000


def _dims(chiprows, chipcols, threedheight):
    return {
        "chiprows": chiprows,
        "chipcols": chipcols,
        "num3d": 1,
        "num2p5d": 0,
        "threedheight": threedheight,
        "two5dwidth": 1,
    }


def dims_for_core_count_2_layer(core_count):
    if core_count <= 8:
        return _dims(2, 2, 2)
    if core_count <= 16:
        return _dims(3, 3, 2)
    if core_count <= 32:
        return _dims(4, 4, 2)
    if core_count <= 50:
        return _dims(5, 5, 2)
    if core_count <= 72:
        return _dims(6, 6, 2)
    if core_count <= 98:
        return _dims(7, 7, 2)
    if core_count <= 128:
        return _dims(8, 8, 2)
    return None


def dims_for_core_count_4_layer(core_count):
    if core_count <= 16:
        return _dims(2, 2, 4)
    if core_count <= 36:
        return _dims(3, 3, 4)
    if core_count <= 64:
        return _dims(4, 4, 4)
    if core_count <= 100:
        return _dims(5, 5, 4)
    if core_count <= 128:
        return _dims(6, 6, 4)
    return None


def graph_paths():
    paths = sorted((REPO_ROOT / "Graphs").glob("Graph*.txt"), key=runner.graph_sort_key)
    if not paths:
        raise SystemExit("No Graph*.txt files found under Graphs/")
    return paths


def run_layer_batch(label, dims_for_core_count, results_start_time):
    if runner.MODE not in {"elevator", "random"}:
        raise ValueError("MODE must be elevator or random")

    csv_path = (
        REPO_ROOT
        / "native_3d_mesh"
        / f"RESULTS_{runner.MODE}_pso_{results_start_time}.csv"
    )
    print(f"\n=== {label} PSO native 3D mesh batch ===")
    print(f"Results CSV: {csv_path}")

    failures = []
    skipped = []
    total = 0

    for graph_path in graph_paths():
        core_count = runner.read_core_count(graph_path)
        if core_count < runner.MIN_CORE_COUNT:
            skipped.append((graph_path.name, core_count, f"less than {runner.MIN_CORE_COUNT}"))
            print(
                f"SKIP {graph_path.name}: "
                f"{core_count} cores is less than {runner.MIN_CORE_COUNT}"
            )
            continue

        dims = dims_for_core_count(core_count)
        if dims is None:
            skipped.append((graph_path.name, core_count, "exceeds 128"))
            print(f"SKIP {graph_path.name}: {core_count} cores exceeds 128")
            continue

        total += 1
        cmd = runner.build_command("PSO", graph_path, dims, results_start_time)
        cmd.extend([
            "--buffer-depth",
            str(SIM_BUFFER_DEPTH),
            "--packet-size",
            str(SIM_PACKET_SIZE),
            "--stats-warm-up-time",
            str(SIM_STATS_WARM_UP_TIME),
        ])
        print(
            f"\nRUN PSO {label} {graph_path.name}: cores={core_count} "
            f"dims={dims}"
        )
        print(" ".join(cmd))

        if runner.DRY_RUN:
            continue

        result = runner.subprocess.run(cmd, cwd=REPO_ROOT, check=False)
        if result.returncode != 0:
            failures.append((graph_path.name, result.returncode))
            print(f"FAILED PSO {label} {graph_path.name}: exit code {result.returncode}")
            if runner.STOP_ON_FAILURE:
                raise SystemExit(result.returncode)

    print(f"\n{label} batch complete")
    print(f"Runs attempted: {total}")
    print(f"Skipped graphs: {len(skipped)}")
    print(f"Failures: {len(failures)}")
    if skipped:
        for name, cores, reason in skipped:
            print(f"  skipped {name}: {cores} cores {reason}")
    if failures:
        for name, code in failures:
            print(f"  failed PSO {label} {name}: exit code {code}")
    return failures


def _validate_results_start_time(parser, value):
    try:
        parsed = datetime.strptime(value, "%Y%m%d_%H%M%S")
    except ValueError:
        parser.error("--results-start-time must be YYYYMMDD_HHMMSS")
    if parsed.strftime("%Y%m%d_%H%M%S") != value:
        parser.error("--results-start-time must be YYYYMMDD_HHMMSS")
    return parsed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--layers",
        choices=("2", "4", "both"),
        default="both",
        help="Mesh layers to run: 2, 4, or both (default: both).",
    )
    parser.add_argument(
        "--results-start-time",
        help=(
            "Timestamp for the first selected CSV (YYYYMMDD_HHMMSS). "
            "When running both layers, the 4-layer CSV uses the next second."
        ),
    )
    args = parser.parse_args()

    if args.results_start_time:
        two_layer_time = _validate_results_start_time(parser, args.results_start_time)
    else:
        two_layer_time = datetime.now()
    four_layer_time = two_layer_time + timedelta(seconds=args.layers == "both")

    with runner.batch_lock():
        failures = []
        if args.layers in {"2", "both"}:
            failures.extend(run_layer_batch(
                "2-layer",
                dims_for_core_count_2_layer,
                two_layer_time.strftime("%Y%m%d_%H%M%S"),
            ))
        if args.layers in {"4", "both"}:
            failures.extend(run_layer_batch(
                "4-layer",
                dims_for_core_count_4_layer,
                four_layer_time.strftime("%Y%m%d_%H%M%S"),
            ))

    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
