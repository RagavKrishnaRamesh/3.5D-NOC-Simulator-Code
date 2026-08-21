#!/usr/bin/env python3
"""
Verify optimizer metrics from a saved particle JSON.

This script recomputes:
  - total unweighted hop count
  - weighted hop cost
  - TSV up/down variance
  - effective fitness

The effective fitness formula follows the Tabu reference convention:
    W * (weighted_hop_cost / A) + (1 - W) * (variance / B^2)

For 3.5D particles, the selected GA/SA/PSO module supplies the exact topology,
hop-cost, variance, and normalization behavior used by that optimizer.
"""

import argparse
import atexit
import importlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent


ALGORITHM_MODULES = {
    "GA": "ga_3pt5d",
    "SA": "sa_3p5d",
    "PSO": "pso_3p5d",
}


def _repo_path(path_text):
    path = Path(path_text)
    if path.is_absolute():
        return path
    return REPO_ROOT / path


def _infer_algorithm(particle_path, data):
    explicit = data.get("algorithm")
    if explicit:
        value = str(explicit).strip().upper()
        if value in ALGORITHM_MODULES:
            return value

    name = particle_path.name.upper()
    match = re.match(r"(GA|SA|PSO)(?:_|-)", name)
    if match:
        return match.group(1)

    return None


def _graph_name_and_path(graph_value):
    raw = str(graph_value).strip()
    candidates = []

    raw_path = Path(raw)
    if raw_path.is_absolute():
        candidates.append(raw_path)
    else:
        candidates.append(REPO_ROOT / raw)

    if raw.isdigit():
        candidates.append(REPO_ROOT / "Graphs" / f"Graph{int(raw)}.txt")

    if not raw.lower().endswith(".txt"):
        candidates.append(REPO_ROOT / f"{raw}.txt")
        candidates.append(REPO_ROOT / "Graphs" / f"{raw}.txt")

    candidates.append(REPO_ROOT / "Graphs" / Path(raw).name)

    for candidate in candidates:
        if candidate.is_file():
            return candidate.stem, candidate

    raise FileNotFoundError(f"Graph file not found for particle graph value: {raw}")


def _read_edges(graph_path, directed=False):
    with graph_path.open("r", encoding="utf-8") as handle:
        first = handle.readline().strip()
        if not first:
            raise ValueError(f"Graph file is empty: {graph_path}")
        size = int(first)

        matrix = []
        for _ in range(size):
            row = handle.readline().strip().split()
            if len(row) != size:
                raise ValueError(f"Expected {size} columns in graph row, found {len(row)}")
            matrix.append(row)

    edges = []
    for src in range(size):
        start_dst = 0 if directed else src + 1
        for dst in range(start_dst, size):
            if src == dst:
                continue
            raw = matrix[src][dst]
            if raw.upper() == "INF":
                continue
            bw = float(raw)
            if bw > 0:
                edges.append((src, dst, bw))

    return size, edges


def _remove_if_exists(path):
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _write_temp_edge_set(edges, graph_name):
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", graph_name) or "graph"
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        delete=False,
        prefix=f"edge_set_{safe_name}_verify_",
        suffix=".txt",
    )
    path = Path(handle.name)
    with handle:
        for src, dst, bw in edges:
            handle.write(f"{src} {dst} {bw}\n")
    atexit.register(_remove_if_exists, path)
    return path


def _load_optimizer_module(algorithm):
    module_name = ALGORITHM_MODULES[algorithm]
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    return importlib.import_module(module_name)


def _build_layout(module, params):
    required = [
        "chip_rows",
        "chip_cols",
        "two5d_width",
        "threeD_height",
        "num_2p5d_units",
        "num_3d_units",
    ]
    missing = [key for key in required if key not in params]
    if missing:
        raise KeyError(f"Particle params missing required keys: {', '.join(missing)}")

    return module.build_topology(
        int(params["chip_rows"]),
        int(params["chip_cols"]),
        int(params["two5d_width"]),
        int(params["threeD_height"]),
        int(params["num_2p5d_units"]),
        int(params["num_3d_units"]),
    )


def _weighted_and_unweighted_hops(module, chromosome, chiplet_layout, edges):
    if hasattr(module, "current_chromosome"):
        module.current_chromosome = chromosome
    if hasattr(module, "current_particle_state"):
        module.current_particle_state = chromosome
    module.tsv_assignment_global = module.build_global_tsv_assignment(
        chromosome,
        chiplet_layout,
    )

    core_to_router = module.build_core_to_router_map(chromosome, chiplet_layout)
    total_hops = 0.0
    weighted_cost = 0.0

    for src_core, dst_core, bw in edges:
        if src_core not in core_to_router or dst_core not in core_to_router:
            continue
        src_router = core_to_router[src_core]
        dst_router = core_to_router[dst_core]
        hops = module.calculate_count(src_router, dst_router)
        total_hops += hops
        weighted_cost += hops * bw

    return total_hops, weighted_cost


def _format_float(value):
    if value is None:
        return "None"
    return f"{float(value):.12g}"


def _print_delta(label, recomputed, stored):
    if stored is None:
        return
    delta = float(recomputed) - float(stored)
    print(f"{label} delta vs particle: {_format_float(delta)}")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Recompute hop, variance, and effective fitness from a particle JSON."
    )
    parser.add_argument("particle_path", help="Path to GA/SA/PSO particle JSON")
    parser.add_argument(
        "--algorithm",
        choices=sorted(ALGORITHM_MODULES),
        help="Metric model to use. Defaults to inferring from particle filename.",
    )
    parser.add_argument(
        "--graph",
        help="Override graph file or graph number. Defaults to particle['graph'].",
    )
    parser.add_argument(
        "--directed",
        action="store_true",
        help="Use all non-INF matrix entries instead of the default upper-triangle edge set.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    os.chdir(REPO_ROOT)

    particle_path = _repo_path(args.particle_path)
    with particle_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    algorithm = args.algorithm or _infer_algorithm(particle_path, data)
    if algorithm is None:
        raise ValueError(
            "Could not infer algorithm from particle filename. Pass --algorithm GA, SA, or PSO."
        )

    graph_value = args.graph if args.graph is not None else data.get("graph")
    if graph_value is None:
        raise KeyError("Particle does not contain 'graph'; pass --graph explicitly.")

    graph_name, graph_path = _graph_name_and_path(graph_value)
    graph_size, edges = _read_edges(graph_path, directed=args.directed)
    edge_set_path = _write_temp_edge_set(edges, graph_name)

    module = _load_optimizer_module(algorithm)
    params = data.get("params", {})
    chromosome = data.get("chromosome")
    if chromosome is None:
        raise KeyError("Particle JSON missing 'chromosome'.")

    chiplet_layout, total_routers = _build_layout(module, params)
    if graph_size != total_routers:
        raise ValueError(
            f"Graph core count ({graph_size}) does not match particle router count ({total_routers})."
        )

    router_coordinates = module.assign_router_coordinates(total_routers)
    module.init_normalization_terms(graph_name, str(edge_set_path), int(params["threeD_height"]))

    effective, weighted_cost, variance, variance_up, variance_down = module.fitness_terms_3p5d(
        chromosome,
        chiplet_layout,
        router_coordinates,
        str(edge_set_path),
    )
    total_hops, weighted_hops_check = _weighted_and_unweighted_hops(
        module,
        chromosome,
        chiplet_layout,
        edges,
    )

    print(f"Particle: {particle_path}")
    print(f"Algorithm model: {algorithm}")
    print(f"Graph: {graph_path}")
    print(f"Edge mode: {'directed' if args.directed else 'upper-triangle'}")
    print(f"Total unweighted hops: {_format_float(total_hops)}")
    print(f"Weighted hop cost: {_format_float(weighted_cost)}")
    print(f"Weighted hop cost check: {_format_float(weighted_hops_check)}")
    print(f"Variance up: {_format_float(variance_up)}")
    print(f"Variance down: {_format_float(variance_down)}")
    print(f"Variance max: {_format_float(variance)}")
    print(f"Effective fitness: {_format_float(effective)}")

    print("")
    _print_delta("Weighted hop cost", weighted_cost, data.get("best_cost"))
    _print_delta("Variance up", variance_up, data.get("variance_up"))
    _print_delta("Variance down", variance_down, data.get("variance_down"))
    _print_delta("Variance max", variance, data.get("variance"))
    _print_delta("Effective fitness", effective, data.get("effective_fitness"))


if __name__ == "__main__":
    main()
