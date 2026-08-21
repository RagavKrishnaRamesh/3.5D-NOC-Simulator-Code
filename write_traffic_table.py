#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path

import generate_yaml as yaml_gen


def _load_graph(path, directed):
    with open(path, "r", encoding="utf-8") as f:
        tokens = f.read().split()

    if not tokens:
        raise ValueError(f"Graph file is empty: {path}")

    try:
        n = int(tokens[0])
    except ValueError as exc:
        raise ValueError(f"Invalid graph size in {path}") from exc

    expected = 1 + n * n
    if len(tokens) < expected:
        raise ValueError(
            f"Graph file {path} has {len(tokens) - 1} entries, expected {n * n}"
        )

    edges = []
    idx = 1
    for i in range(n):
        for j in range(n):
            token = tokens[idx]
            idx += 1
            if token.upper() == "INF":
                continue
            try:
                weight = float(token)
            except ValueError as exc:
                raise ValueError(
                    f"Invalid weight '{token}' at ({i},{j}) in {path}"
                ) from exc
            if i == j:
                continue
            if directed:
                edges.append((i, j, weight))
            elif j > i:
                edges.append((i, j, weight))

    return n, edges


def _load_particle(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _resolve_particle_chiplets(particle):
    params = particle.get("params") or {}
    required = (
        "chip_rows",
        "chip_cols",
        "two5d_width",
        "threeD_height",
        "num_2p5d_units",
        "num_3d_units",
    )
    missing = [k for k in required if k not in params]
    if missing:
        raise ValueError(f"Particle is missing required params: {', '.join(missing)}")

    gap = int((particle.get("topology_hints") or {}).get("interposer_gap", 1))
    _, default_base_cols = yaml_gen._base_dims_from_params(params, gap)
    base_cols = int((particle.get("base") or {}).get("cols", default_base_cols))

    layout = yaml_gen._infer_layout_from_params(params, base_cols, gap)
    layout = yaml_gen._overlay_layout_with_particle_chiplets(layout, particle)
    chromosome = yaml_gen._extract_chromosome(particle)
    chiplets = yaml_gen._attach_genes_to_layout(layout, chromosome, particle)
    return chiplets


def _router_to_core(particle):
    mapping = {}
    for chiplet in _resolve_particle_chiplets(particle):
        r_start, r_end = chiplet["range"]
        core_list = chiplet["core_to_router"]
        expected = int(r_end) - int(r_start) + 1
        if expected != len(core_list):
            raise ValueError(
                f"Range {chiplet['range']} expects {expected} entries, got {len(core_list)}"
            )
        for idx, core_id in enumerate(core_list):
            router_id = int(r_start) + idx
            if router_id in mapping:
                raise ValueError(f"Duplicate router id {router_id} in mapping")
            mapping[router_id] = int(core_id)
    return mapping


def _core_to_router(router_to_core, n_cores):
    mapping = {}
    for router_id, core_id in router_to_core.items():
        if core_id in mapping:
            raise ValueError(f"Duplicate core id {core_id} in mapping")
        mapping[core_id] = router_id
    missing = [c for c in range(n_cores) if c not in mapping]
    if missing:
        raise ValueError(f"Missing core ids in mapping: {missing[:8]}")
    return mapping


def _build_router_to_mesh_local(particle):
    params = particle.get("params") or {}
    gap = int((particle.get("topology_hints") or {}).get("interposer_gap", 1))
    router_to_mesh_local = {}
    name_idx = 1

    for chiplet in _resolve_particle_chiplets(particle):
        chip_type = yaml_gen._norm_chip_type(chiplet["type"])

        if chip_type == "3d":
            mesh_name = f"C{name_idx}"
            name_idx += 1
            r_start, r_end = chiplet["range"]
            for router_id in range(int(r_start), int(r_end) + 1):
                if router_id in router_to_mesh_local:
                    raise ValueError(f"Router id {router_id} belongs to multiple meshes")
                router_to_mesh_local[router_id] = (mesh_name, router_id - int(r_start))
            continue

        interposer_name = f"C{name_idx}"
        name_idx += 1

        sub_specs = yaml_gen._build_subchip_specs_2p5d(chiplet, params, gap)
        for spec in sub_specs:
            mesh_name = f"C{name_idx}"
            name_idx += 1
            r_start, r_end = spec["range"]
            for router_id in range(int(r_start), int(r_end) + 1):
                if router_id in router_to_mesh_local:
                    raise ValueError(f"Router id {router_id} belongs to multiple meshes")
                router_to_mesh_local[router_id] = (mesh_name, router_id - int(r_start))

    return router_to_mesh_local


def _build_mesh_tree(particle):
    _, _, base_name, _, meshes, edges = yaml_gen._build_mesh_graph(particle)
    mesh_sizes = {
        name: int(mesh["dim_x"]) * int(mesh["dim_y"]) * int(mesh["dim_z"])
        for name, mesh in meshes.items()
    }
    children = {name: [] for name in meshes}
    for edge in edges:
        children[edge["parent"]].append(edge["child"])
    return base_name, mesh_sizes, children


def _compute_gid_offsets(mesh_sizes, children, base_name):
    offsets = {}
    visited = set()
    gid_offset = 0
    stack = [base_name]

    while stack:
        curr = stack.pop()
        if curr in visited:
            raise ValueError(f"Cycle detected while visiting mesh {curr}")
        visited.add(curr)

        offsets[curr] = gid_offset
        gid_offset += mesh_sizes[curr]

        # Matches simulator DFS behavior with LIFO stack traversal.
        for child in sorted(children.get(curr, [])):
            stack.append(child)

    if len(visited) != len(mesh_sizes):
        missing = sorted(set(mesh_sizes.keys()) - visited)
        raise ValueError(f"Disconnected meshes in topology: {missing}")

    return offsets


def _router_ids_to_global_ids(particle, router_ids):
    base_name, mesh_sizes, children = _build_mesh_tree(particle)
    offsets = _compute_gid_offsets(mesh_sizes, children, base_name)
    router_to_mesh_local = _build_router_to_mesh_local(particle)

    router_to_global = {}
    for router_id in router_ids:
        if router_id not in router_to_mesh_local:
            raise ValueError(f"Router id {router_id} not covered by particle chiplet ranges")
        mesh_name, local_id = router_to_mesh_local[router_id]
        if mesh_name not in offsets:
            raise ValueError(f"Mesh {mesh_name} has no global offset")
        router_to_global[router_id] = offsets[mesh_name] + local_id

    return router_to_global


def _update_config(config_path, table_path):
    with open(config_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    out_lines = []
    updated_dist = False
    updated_table = False
    for line in lines:
        if line.lstrip().startswith("traffic_distribution:"):
            prefix = line.split("traffic_distribution:")[0]
            out_lines.append(f"{prefix}traffic_distribution: TRAFFIC_TABLE_BASED\n")
            updated_dist = True
        elif line.lstrip().startswith("traffic_table_filename:"):
            prefix = line.split("traffic_table_filename:")[0]
            out_lines.append(f"{prefix}traffic_table_filename: \"{table_path}\"\n")
            updated_table = True
        else:
            out_lines.append(line)

    if not updated_dist:
        out_lines.append("traffic_distribution: TRAFFIC_TABLE_BASED\n")
    if not updated_table:
        out_lines.append(f"traffic_table_filename: \"{table_path}\"\n")

    with open(config_path, "w", encoding="utf-8") as f:
        f.writelines(out_lines)


def _generate_traffic_table(graph_path, particle_path, output_path, directed, id_space):
    graph_path = Path(graph_path)
    particle_path = Path(particle_path)
    output_path = Path(output_path)

    n_cores, edges = _load_graph(graph_path, directed)
    if not edges:
        raise ValueError(f"No edges found in graph: {graph_path}")

    particle = _load_particle(particle_path)
    router_to_core = _router_to_core(particle)
    core_to_router = _core_to_router(router_to_core, n_cores)

    if id_space == "global":
        router_to_target_id = _router_ids_to_global_ids(particle, core_to_router.values())
    else:
        router_to_target_id = {r: r for r in core_to_router.values()}

    max_w = max(w for _, _, w in edges)
    if max_w <= 0:
        raise ValueError("Max edge weight must be > 0")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        f.write(f"% graph={graph_path} particle={particle_path} id_space={id_space}\n")
        f.write("% src dst pir\n")
        for u, v, w in edges:
            src_router = core_to_router[u]
            dst_router = core_to_router[v]
            src = router_to_target_id[src_router]
            dst = router_to_target_id[dst_router]
            if src == dst:
                continue
            pir = w / max_w
            f.write(f"{src} {dst} {pir:.6f}\n")

    return output_path


_PARTICLE_RE = re.compile(
    r"^(?:GA_Particle|SA_Particle|SA35_Particle|SA25_Particle|PSO35_Particle|PSO25_Particle|PSO_Particle|Particle)(?P<graph_id>\d+)$",
    re.IGNORECASE,
)


def _particle_base_and_id(path):
    stem = Path(path).stem
    base_name = stem
    match = _PARTICLE_RE.match(base_name)
    if not match:
        raise ValueError(f"Cannot extract graph id from '{path}'")
    return base_name, int(match.group("graph_id"))


def _resolve_logger_dir(name):
    for candidate in (Path(name), Path(f"{name}_results")):
        if candidate.is_dir():
            return candidate
    return None


def _process_logger_dirs(directed, id_space, update_generated_yaml):
    total = 0
    failed = 0

    for logger_name in ("PSO_logger", "SA_logger"):
        source_dir = _resolve_logger_dir(logger_name)
        if source_dir is None:
            print(
                f"Skipping {logger_name}: directory not found "
                f"(checked {logger_name}/ and {logger_name}_results/)"
            )
            continue

        output_dir = Path(f"{logger_name}_simres")
        for particle_path in sorted(source_dir.glob("*.txt")):
            try:
                _, graph_id = _particle_base_and_id(particle_path)
            except Exception as exc:  # noqa: BLE001
                print(f"[{logger_name}] Skipping {particle_path.name}: {exc}")
                failed += 1
                continue

            graph_path = Path("Graphs") / f"Graph{graph_id}.txt"
            if not graph_path.is_file():
                print(f"[{logger_name}] Missing graph file {graph_path} for {particle_path.name}")
                failed += 1
                continue

            output_path = output_dir / f"{particle_path.stem}-TrafficTable.txt"
            try:
                _generate_traffic_table(
                    graph_path,
                    particle_path,
                    output_path,
                    directed,
                    id_space,
                )
                if update_generated_yaml:
                    yaml_path = output_dir / f"{particle_path.stem}-3pt5d.yaml"
                    if yaml_path.is_file():
                        _update_config(yaml_path, output_path.as_posix())
                    else:
                        print(f"[{logger_name}] YAML not found for update: {yaml_path}")
            except Exception as exc:  # noqa: BLE001
                print(f"[{logger_name}] Failed {particle_path.name}: {exc}")
                failed += 1
                continue

            total += 1
            print(f"[{logger_name}] Wrote {output_path}")

    if total == 0:
        print("No particle files processed from PSO_logger or SA_logger.")
    if failed:
        print(f"Encountered {failed} error(s) while processing logger directories.")


def main():
    parser = argparse.ArgumentParser(
        description="Generate a traffic table for the 3D-multimesh YAML pipeline."
    )
    parser.add_argument("graph", nargs="?", help="Graph index (e.g. 1) or path to Graph.txt")
    parser.add_argument(
        "--particle",
        help="Path to Particle.txt (defaults to Particles/GA_ParticleN.txt when graph is an index)",
    )
    parser.add_argument(
        "--output",
        help="Output traffic table path (defaults to TrafficTable/TrafficTableN.txt)",
    )
    parser.add_argument(
        "--directed",
        action="store_true",
        help="Use directed edges (default uses upper-triangle only).",
    )
    parser.add_argument(
        "--id-space",
        choices=("global", "particle"),
        default="global",
        help="Emit simulator global IDs (default) or raw particle router IDs.",
    )
    parser.add_argument(
        "--update-config",
        help="Config YAML path to update traffic_distribution and traffic_table_filename.",
    )
    parser.add_argument(
        "--process-loggers",
        action="store_true",
        help="Process all Particle*.txt files in PSO_logger/ and SA_logger/ into *_simres outputs.",
    )
    parser.add_argument(
        "--update-generated-yaml",
        action="store_true",
        help="With --process-loggers, also patch each generated *_simres/*-3pt5d.yaml to use its traffic table.",
    )
    args = parser.parse_args()

    if args.process_loggers:
        if args.graph or args.particle or args.output or args.update_config:
            parser.error(
                "--process-loggers cannot be combined with graph/--particle/--output/--update-config"
            )
        _process_logger_dirs(args.directed, args.id_space, args.update_generated_yaml)
        return

    if not args.graph:
        parser.error("graph is required unless --process-loggers is set")

    if args.graph.isdigit():
        graph_id = int(args.graph)
        graph_path = Path("Graphs") / f"Graph{graph_id}.txt"
        particle_path = Path(args.particle) if args.particle else Path("Particles") / f"GA_Particle{graph_id}.txt"
        output_path = Path(args.output) if args.output else Path("TrafficTable") / f"TrafficTable{graph_id}.txt"
    else:
        graph_path = Path(args.graph)
        if not args.particle:
            raise SystemExit("Missing --particle when graph is a path")
        particle_path = Path(args.particle)
        output_path = Path(args.output) if args.output else Path("TrafficTable") / "TrafficTable.txt"

    try:
        output_path = _generate_traffic_table(
            graph_path,
            particle_path,
            output_path,
            args.directed,
            args.id_space,
        )
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(str(exc)) from exc

    if args.update_config:
        _update_config(args.update_config, output_path.as_posix())

    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()
