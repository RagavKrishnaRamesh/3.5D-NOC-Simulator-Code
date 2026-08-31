#!/usr/bin/env python3
import argparse
import csv
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

from ga_3pt5d import particle_output_path as ga_particle_output_path
from ga_3pt5d import run_ga_3p5d
from pso_3p5d import particle_output_path as pso_particle_output_path
from pso_3p5d import run_pso_3p5d
from run_simulator import run_simulation
from sa_3p5d import particle_output_path as sa_particle_output_path
from sa_3p5d import run_sa_3p5d


REPO_ROOT = Path(__file__).resolve().parent
METRIC_RE = re.compile(
    r"^\s*%\s*(?P<name>[^:\n]+):\s*"
    r"(?P<value>[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)\s*$"
)


def _normalize_algorithm(value):
    algorithm = str(value).strip().upper()
    if algorithm not in {"GA", "PSO", "SA"}:
        raise ValueError("algorithm must be GA, PSO, or SA")
    return algorithm


def _normalize_mode(value):
    mode = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "random": 0,
        "redelf": 1,
        "elevator": 1,
        "elevator_first": 1,
        "elevatorfirst": 1,
    }
    if mode not in aliases:
        raise ValueError("mode must be random or redelf")
    return aliases[mode]


def _graph_name_and_path(graph):
    raw = str(graph).strip()
    if raw.isdigit():
        graph_name = f"Graph{int(raw)}"
        graph_path = REPO_ROOT / "Graphs" / f"{graph_name}.txt"
        graph_number = int(raw)
    else:
        path = Path(raw)
        graph_path = path if path.is_absolute() else REPO_ROOT / path
        if not graph_path.is_file():
            graph_path = REPO_ROOT / "Graphs" / path.name
        graph_name = graph_path.stem
        match = re.search(r"(\d+)$", graph_name)
        graph_number = int(match.group(1)) if match else graph_name

    if not graph_path.is_file():
        raise FileNotFoundError(f"Graph file not found: {graph_path}")
    return graph_name, graph_path, graph_number


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


def _run_optimizer(algorithm, graph_name, args, mode):
    runners = {
        "GA": (run_ga_3p5d, ga_particle_output_path),
        "PSO": (run_pso_3p5d, pso_particle_output_path),
        "SA": (run_sa_3p5d, sa_particle_output_path),
    }
    runner, particle_path_fn = runners[algorithm]
    start = time.perf_counter()
    runner(
        graph_name,
        args.chiprows,
        args.chipcols,
        args.two5dwidth,
        args.threedheight,
        args.num2p5d,
        args.num3d,
        args.iterations,
        args.population,
        tsv_assignment_mode=mode,
        seed=args.seed,
    )
    runtime = time.perf_counter() - start
    particle_path = REPO_ROOT / particle_path_fn(graph_name)
    if not particle_path.is_file():
        raise FileNotFoundError(f"Optimizer did not write particle file: {particle_path}")
    return particle_path, runtime


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
        "Hopcount": data.get("best_cost"),
        "Variance": data.get("variance"),
        "Variance Up": data.get("variance_up"),
        "Variance Down": data.get("variance_down"),
        "Effective Fitness": data.get("effective_fitness"),
    }


def _append_csv(row, metrics, csv_path):
    csv_path = Path(csv_path)
    headers = [
        "Graph",
        "Algorithm",
        "Dimension",
        "Population",
        "Iterations",
        "Runtime",
        "Hopcount",
        "Variance",
        "Variance Up",
        "Variance Down",
        "Effective Fitness",
        "Simulation Time",
    ]

    existing_rows = []
    existing_headers = []
    if csv_path.exists():
        with csv_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            existing_headers = reader.fieldnames or []
            existing_rows = list(reader)

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

    output_path = csv_path
    try:
        handle = output_path.open("w", encoding="utf-8", newline="")
    except PermissionError:
        output_path = csv_path.with_name(f"{csv_path.stem}_pending.csv")
        if output_path.exists():
            with output_path.open("r", encoding="utf-8", newline="") as pending_handle:
                pending_reader = csv.DictReader(pending_handle)
                pending_headers = pending_reader.fieldnames or []
                pending_rows = list(pending_reader)
            for header in pending_headers:
                if header not in final_headers:
                    final_headers.append(header)
            existing_rows = pending_rows + [existing_rows[-1]]
        handle = output_path.open("w", encoding="utf-8", newline="")

    with handle:
        writer = csv.DictWriter(handle, fieldnames=final_headers)
        writer.writeheader()
        writer.writerows(existing_rows)
    return output_path


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run optimizer, generate YAML/traffic table, simulate, and log results."
    )
    parser.add_argument("--algorithm", required=True, help="GA, PSO, or SA")
    parser.add_argument("--graph", required=True, help="Graph number x or graph path")
    parser.add_argument("--chiprows", type=int, required=True)
    parser.add_argument("--chipcols", type=int, required=True)
    parser.add_argument("--2.5dwidth", "--two5dwidth", dest="two5dwidth", type=int, required=True)
    parser.add_argument("--3dheight", "--threedheight", dest="threedheight", type=int, required=True)
    parser.add_argument("--num2.5d", "--num2p5d", dest="num2p5d", type=int, required=True)
    parser.add_argument("--num3d", type=int, required=True)
    parser.add_argument("--population", type=int, required=True)
    parser.add_argument("--iterations", type=int, required=True)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument(
        "--mode",
        default="random",
        help="TSV assignment mode: random or redelf",
    )
    parser.add_argument("--sim-seed", type=int, default=None)
    parser.add_argument("--noxim", default="bin/noxim")
    parser.add_argument("--power", default="bin/power.yaml")
    parser.add_argument("--id-space", choices=("global", "particle"), default="global")
    parser.add_argument("--directed", action="store_true")
    parser.add_argument("--use-wsl", action="store_true")
    return parser.parse_args()


def main():
    os.chdir(REPO_ROOT)
    args = parse_args()
    algorithm = _normalize_algorithm(args.algorithm)
    mode = _normalize_mode(args.mode)
    graph_name, graph_path, graph_number = _graph_name_and_path(args.graph)

    particle_path, optimizer_runtime = _run_optimizer(
        algorithm,
        graph_name,
        args,
        mode,
    )

    sim_seed = args.sim_seed if args.sim_seed is not None else args.seed
    sim_start = time.perf_counter()
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
    simulation_time = time.perf_counter() - sim_start
    metrics = _parse_simulation_metrics(sim_result["log"])
    optimizer_metrics = _read_optimizer_metrics(particle_path)

    csv_path = REPO_ROOT / f"RUN_{datetime.now().strftime('%d%m%y')}.csv"
    row = {
        "Graph": graph_number,
        "Algorithm": algorithm,
        "Dimension": _dimension_text(args),
        "Population": args.population,
        "Iterations": args.iterations,
        "Runtime": optimizer_runtime,
        "Simulation Time": simulation_time,
    }
    row.update(optimizer_metrics)
    written_csv_path = _append_csv(row, metrics, csv_path)

    print(f"Particle: {particle_path}")
    print(f"YAML: {sim_result['yaml']}")
    print(f"Traffic Table: {sim_result['traffic_table']}")
    print(f"Log: {sim_result['log']}")
    print(f"CSV: {written_csv_path}")


if __name__ == "__main__":
    main()
