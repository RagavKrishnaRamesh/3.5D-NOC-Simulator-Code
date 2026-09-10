#!/usr/bin/env python3
"""Run the native 3D mesh full pipeline for every graph in Graphs/."""

import re
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import fcntl


REPO_ROOT = Path(__file__).resolve().parents[1]

# Edit these globals before launching a batch.
ALGORITHMS = ["GA", "SA", "PSO"]
MIN_CORE_COUNT = 0
POPULATION = 1000
ITERATIONS = 500
MODE = "elevator_first"  # "elevator_first" or "redelf_random"
SEED = 10
SIM_SEED = 10
NOXIM = "bin/noxim"
POWER = "bin/power.yaml"
ID_SPACE = "global"
DIRECTED = False
USE_WSL = False
DRY_RUN = False
STOP_ON_FAILURE = False


@contextmanager
def batch_lock():
    """Prevent two mesh graph batches from interleaving their CSV output."""
    lock_path = REPO_ROOT / "native_3d_mesh" / ".mesh_graph_batch.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise SystemExit(
                "Another native 3D mesh graph batch is already running. "
                "Wait for it to finish before starting GA, SA, or PSO."
            ) from exc
        try:
            yield
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)


def graph_sort_key(path):
    match = re.search(r"(\d+)$", path.stem)
    if match:
        return int(match.group(1))
    return path.stem


def read_core_count(graph_path):
    with graph_path.open("r", encoding="utf-8") as handle:
        first = handle.readline().strip()
    try:
        return int(first)
    except ValueError as exc:
        raise ValueError(f"Cannot read core count from {graph_path}") from exc


def dims_for_core_count(core_count):
    if core_count <= 16:
        return {
            "chiprows": 2,
            "chipcols": 2,
            "num3d": 1,
            "num2p5d": 1,
            "threedheight": 2,
            "two5dwidth": 2,
        }
    if core_count <= 32:
        return {
            "chiprows": 3,
            "chipcols": 3,
            "num3d": 1,
            "num2p5d": 1,
            "threedheight": 2,
            "two5dwidth": 2,
        }
    if core_count <= 64:
        return {
            "chiprows": 4,
            "chipcols": 4,
            "num3d": 1,
            "num2p5d": 1,
            "threedheight": 2,
            "two5dwidth": 2,
        }
    if core_count <= 128:
        return {
            "chiprows": 4,
            "chipcols": 4,
            "num3d": 2,
            "num2p5d": 2,
            "threedheight": 2,
            "two5dwidth": 2,
        }
    return None


def graph_arg(graph_path):
    match = re.fullmatch(r"Graph(\d+)", graph_path.stem, re.IGNORECASE)
    if match:
        return match.group(1)
    return str(graph_path)


def build_command(algorithm, graph_path, dims):
    cmd = [
        sys.executable,
        "native_3d_mesh/run_pipeline_mesh.py",
        "--algorithm",
        algorithm,
        "--graph",
        graph_arg(graph_path),
        "--chiprows",
        str(dims["chiprows"]),
        "--chipcols",
        str(dims["chipcols"]),
        "--two5dwidth",
        str(dims["two5dwidth"]),
        "--threedheight",
        str(dims["threedheight"]),
        "--num2p5d",
        str(dims["num2p5d"]),
        "--num3d",
        str(dims["num3d"]),
        "--population",
        str(POPULATION),
        "--iterations",
        str(ITERATIONS),
        "--mode",
        MODE,
        "--noxim",
        NOXIM,
        "--power",
        POWER,
        "--id-space",
        ID_SPACE,
    ]
    if SEED is not None:
        cmd.extend(["--seed", str(SEED)])
    if SIM_SEED is not None:
        cmd.extend(["--sim-seed", str(SIM_SEED)])
    if DIRECTED:
        cmd.append("--directed")
    if USE_WSL:
        cmd.append("--use-wsl")
    return cmd


def _run_batch():
    graph_paths = sorted((REPO_ROOT / "Graphs").glob("Graph*.txt"), key=graph_sort_key)
    if not graph_paths:
        raise SystemExit("No Graph*.txt files found under Graphs/")

    failures = []
    skipped = []
    total = 0

    for graph_path in graph_paths:
        core_count = read_core_count(graph_path)
        if core_count < MIN_CORE_COUNT:
            skipped.append((graph_path.name, core_count))
            print(
                f"SKIP {graph_path.name}: "
                f"{core_count} cores is less than {MIN_CORE_COUNT}"
            )
            continue

        dims = dims_for_core_count(core_count)
        if dims is None:
            skipped.append((graph_path.name, core_count))
            print(f"SKIP {graph_path.name}: {core_count} cores exceeds 128")
            continue

        for algorithm in ALGORITHMS:
            total += 1
            cmd = build_command(algorithm, graph_path, dims)
            print(
                f"\nRUN {algorithm} {graph_path.name}: cores={core_count} "
                f"dims={dims}"
            )
            print(" ".join(cmd))

            if DRY_RUN:
                continue

            result = subprocess.run(cmd, cwd=REPO_ROOT, check=False)
            if result.returncode != 0:
                failures.append((algorithm, graph_path.name, result.returncode))
                print(
                    f"FAILED {algorithm} {graph_path.name}: "
                    f"exit code {result.returncode}"
                )
                if STOP_ON_FAILURE:
                    raise SystemExit(result.returncode)

    print("\nBatch complete")
    print(f"Runs attempted: {total}")
    print(f"Skipped graphs: {len(skipped)}")
    print(f"Failures: {len(failures)}")
    if skipped:
        for name, cores in skipped:
            print(f"  skipped {name}: {cores} cores")
    if failures:
        for algorithm, name, code in failures:
            print(f"  failed {algorithm} {name}: exit code {code}")
        raise SystemExit(1)


def main():
    # subprocess.run() below waits for every graph pipeline to finish.  The
    # process-wide lock also prevents a second launcher from mixing its rows
    # into the same date-based CSV while this ordered batch is in progress.
    with batch_lock():
        _run_batch()


if __name__ == "__main__":
    main()
