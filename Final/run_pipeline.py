#!/usr/bin/env python3
import argparse
import csv
import json
import os
import re
import tempfile
import time
from datetime import datetime
from pathlib import Path

from csv_to_excel_results import SIMULATOR_COLUMNS, convert, convert_comparison
from pipeline_paths import FINAL_DIR, graph_input_path
import pso_3p5d as pso
import pso_dp_multithreaded as pso_dp_mt
import pso_with_only_dp as pso_dp
from run_simulator import DEFAULT_NOXIM, DEFAULT_POWER, run_simulation


RESULTS_TIME_FORMAT = "%Y%m%d_%H%M%S"
ALGORITHMS = {"PSO": pso, "PSO_DP": pso_dp, "PSO_DP_MT": pso_dp_mt}
METRIC_RE = re.compile(
    r"^\s*%\s*(?P<name>[^:\n]+):\s*"
    r"(?P<value>[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)\s*$"
)


def _normalize_algorithm(value):
    algorithm = re.sub(r"[+\s-]+", "_", value.strip().upper())
    if algorithm not in (*ALGORITHMS, "ALL"):
        raise argparse.ArgumentTypeError("choose PSO, PSO_DP, PSO_DP_MT, or ALL")
    return algorithm


def _normalize_mode(value):
    mode = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "0": 0,
        "elf": 0,
        "elevator": 0,
        "elevator_first": 0,
        "elevatorfirst": 0,
        "1": 1,
        "redelf": 1,
        "redelf_random": 1,
        "random": 1,
    }
    if mode not in aliases:
        raise argparse.ArgumentTypeError("mode must be elevator or random")
    return aliases[mode]


def _validate_results_start_time(value):
    try:
        parsed = datetime.strptime(value, RESULTS_TIME_FORMAT)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("results start time must be YYYYMMDD_HHMMSS") from exc
    if parsed.strftime(RESULTS_TIME_FORMAT) != value:
        raise argparse.ArgumentTypeError("results start time must be YYYYMMDD_HHMMSS")
    return value


def _dimension_text(args):
    return ",".join(
        str(value)
        for value in (
            args.chiprows,
            args.chipcols,
            args.two5dwidth,
            args.threedheight,
            args.num2p5d,
            args.num3d,
        )
    )


def _run_optimizer(algorithm, graph_path, args):
    optimizer = ALGORITHMS[algorithm]
    try:
        graph = graph_path.relative_to(FINAL_DIR).as_posix()
    except ValueError:
        graph = str(graph_path)
    kwargs = {"tsv_assignment_mode": args.mode, "seed": args.seed}
    if algorithm == "PSO_DP_MT":
        kwargs["parallel_workers"] = args.parallel_workers

    start = time.perf_counter()
    cpu_start = os.times()
    optimizer.run_pso_3p5d(
        graph,
        args.chiprows,
        args.chipcols,
        args.two5dwidth,
        args.threedheight,
        args.num2p5d,
        args.num3d,
        args.iterations,
        args.population,
        **kwargs,
    )
    cpu_end = os.times()
    runtime = time.perf_counter() - start
    particle = FINAL_DIR / optimizer.particle_output_path(graph)
    return particle, runtime, cpu_end.user - cpu_start.user, cpu_end.system - cpu_start.system


def _parse_simulation_metrics(log_path):
    metrics = {}
    with Path(log_path).open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            match = METRIC_RE.match(line)
            if not match:
                continue
            name = " ".join(match.group("name").strip().split())
            metrics[name] = float(match.group("value"))
    return metrics


def _read_optimizer_metrics(particle_path):
    with Path(particle_path).open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    return {
        "Fitness Workers": data.get("optimizer", {}).get("workers", 1),
        "Optimizer Seed": data.get("seed"),
        "comm_cost": data.get("best_cost"),
        "Variance": data.get("variance"),
        "Variance Up": data.get("variance_up"),
        "Variance Down": data.get("variance_down"),
        "Normalized Variance": data.get("normalized_variance"),
        "Effective Fitness": data.get("effective_fitness"),
    }


def _rename_legacy_cost_column(fieldnames, rows):
    if "Hopcount" not in fieldnames:
        return fieldnames
    for row in rows:
        old_cost = row.pop("Hopcount", None)
        if old_cost is not None and not row.get("comm_cost"):
            row["comm_cost"] = old_cost
    return list(dict.fromkeys(
        "comm_cost" if name == "Hopcount" else name for name in fieldnames
    ))


def _append_csv(row, metrics, csv_path):
    csv_path = Path(csv_path)
    headers = [
        "Graph",
        "Algorithm",
        "Dimension",
        "Population",
        "Iterations",
        "Runtime",
        "Real Time",
        "User Time",
        "System Time",
        "CPU Time",
        "comm_cost",
        "Variance",
        "Variance Up",
        "Variance Down",
        "Normalized Variance",
        "Effective Fitness",
        "Fitness Workers",
        "Optimizer Seed",
        "Simulator Seed",
        "Simulation Time",
        *SIMULATOR_COLUMNS,
    ]

    existing_rows = []
    existing_headers = []
    if csv_path.exists():
        with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            existing_headers = reader.fieldnames or []
            existing_rows = list(reader)
        existing_headers = _rename_legacy_cost_column(existing_headers, existing_rows)

    final_headers = [header for header in existing_headers if header]
    for header in headers + sorted(metrics):
        if header not in final_headers:
            final_headers.append(header)

    values = dict(row)
    values.update(metrics)
    existing_rows.append(
        {
            header: "" if values.get(header) is None else values.get(header)
            for header in final_headers
        }
    )

    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="", dir=csv_path.parent,
            prefix=f".{csv_path.stem}_", suffix=".tmp", delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            writer = csv.DictWriter(handle, fieldnames=final_headers)
            writer.writeheader()
            writer.writerows(existing_rows)
        os.replace(temp_path, csv_path)
    except PermissionError as exc:
        raise PermissionError(
            f"Cannot update {csv_path}; close it and rerun with the same "
            "--results-start-time to keep all results in one file"
        ) from exc
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
    return csv_path


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run optimizer, generate YAML/traffic table, simulate, and log results."
    )
    parser.add_argument(
        "--algorithm", required=True, type=_normalize_algorithm,
        help="PSO, PSO_DP, PSO_DP_MT, or ALL",
    )
    parser.add_argument(
        "--graph", required=True, action="append",
        help="Graph number or path. Repeat for multiple graphs using the same dimensions.",
    )
    parser.add_argument("--chiprows", type=int, required=True)
    parser.add_argument("--chipcols", type=int, required=True)
    parser.add_argument("--2.5dwidth", "--two5dwidth", dest="two5dwidth", type=int, required=True)
    parser.add_argument("--3dheight", "--threedheight", dest="threedheight", type=int, required=True)
    parser.add_argument("--num2.5d", "--num2p5d", dest="num2p5d", type=int, required=True)
    parser.add_argument("--num3d", type=int, required=True)
    parser.add_argument("--population", type=int, required=True)
    parser.add_argument("--iterations", type=int, required=True)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--parallel-workers", type=int, help="Fitness workers for PSO_DP_MT")
    parser.add_argument(
        "--mode",
        type=_normalize_mode,
        default="random",
        help="TSV assignment mode: elevator or random",
    )
    parser.add_argument(
        "--results-start-time",
        type=_validate_results_start_time,
        help="Reuse a results CSV with this batch start time (YYYYMMDD_HHMMSS)",
    )
    parser.add_argument("--sim-seed", type=int, default=None)
    parser.add_argument("--noxim", default=DEFAULT_NOXIM, help="Simulator binary (default: ../bin/noxim)")
    parser.add_argument("--power", default=DEFAULT_POWER, help="Power model (default: ../bin/power.yaml)")
    parser.add_argument("--id-space", choices=("global", "particle"), default="global")
    parser.add_argument("--directed", action="store_true")
    parser.add_argument("--use-wsl", action="store_true")
    parser.add_argument(
        "--native-3d-mesh", action="store_true",
        help="Represent each 3D chiplet as one native mesh with sparse internal TSVs.",
    )
    args = parser.parse_args()
    if args.parallel_workers is not None:
        if args.algorithm not in ("PSO_DP_MT", "ALL"):
            parser.error("--parallel-workers is available for PSO_DP_MT and ALL")
        if args.parallel_workers < 1:
            parser.error("--parallel-workers must be positive")
    return args


def _run_one(algorithm, graph_path, args, csv_path):
    match = re.fullmatch(r"Graph(\d+)", graph_path.stem, flags=re.IGNORECASE)
    graph_id = int(match[1]) if match else graph_path.stem
    particle, runtime, user_time, system_time = _run_optimizer(algorithm, graph_path, args)

    sim_seed = args.sim_seed if args.sim_seed is not None else args.seed
    start = time.perf_counter()
    simulation = run_simulation(
        particle,
        graph_path,
        noxim=args.noxim,
        seed=sim_seed,
        power=args.power,
        id_space=args.id_space,
        directed=args.directed,
        use_wsl=args.use_wsl,
        native_3d_mesh=args.native_3d_mesh,
    )
    simulation_time = time.perf_counter() - start
    row = {
        "Graph": graph_id,
        "Algorithm": algorithm,
        "Dimension": _dimension_text(args),
        "Population": args.population,
        "Iterations": args.iterations,
        "Runtime": runtime,
        "Real Time": runtime,
        "User Time": user_time,
        "System Time": system_time,
        "CPU Time": user_time + system_time,
        "Simulator Seed": sim_seed,
        "Simulation Time": simulation_time,
    }
    row.update(_read_optimizer_metrics(particle))
    _append_csv(row, _parse_simulation_metrics(simulation["log"]), csv_path)

    print(f"Particle: {particle}")
    print(f"YAML: {simulation['yaml']}")
    print(f"Traffic Table: {simulation['traffic_table']}")
    print(f"Log: {simulation['log']}")
    print(f"CSV: {csv_path}")


def main():
    os.chdir(FINAL_DIR)
    args = parse_args()
    graph_paths = [graph_input_path(graph) for graph in args.graph]
    start_time = args.results_start_time or datetime.now().strftime(RESULTS_TIME_FORMAT)
    results_dir = FINAL_DIR / "native_3d_mesh" if args.native_3d_mesh else FINAL_DIR
    mode = "elevator" if args.mode == 0 else "random"
    algorithms = ALGORITHMS if args.algorithm == "ALL" else (args.algorithm,)
    csv_files = {}

    for algorithm in algorithms:
        csv_path = results_dir / f"RESULTS_{mode}_{algorithm.lower()}_{start_time}.csv"
        for graph_path in graph_paths:
            _run_one(algorithm, graph_path, args, csv_path)
        workbook = csv_path.with_suffix(".xlsx")
        convert(csv_path, workbook)
        print(f"Excel: {workbook}")
        csv_files[algorithm] = csv_path

    if args.algorithm == "ALL":
        workbook = results_dir / f"RESULTS_{mode}_pso_comparison_{start_time}.xlsx"
        convert_comparison(csv_files, workbook)
        print(f"Comparison Excel: {workbook}")


if __name__ == "__main__":
    main()
