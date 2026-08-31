#!/usr/bin/env python3
"""Generate MULTI_MESH YAML with each 3D chiplet as one native 3D mesh."""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import generate_yaml as legacy


def _layer_local_id(plane_lid, layer_z, plane_size):
    return int(layer_z) * int(plane_size) + int(plane_lid)


def _build_intra_tsv_selection(levels, plane_size, tsv_assignment,
                               tsv_candidates, dim_x, dim_y):
    placement = []
    selection = []

    for z in range(int(levels)):
        for tsv in tsv_candidates:
            placement.append(_layer_local_id(tsv, z, plane_size))

    for z in range(int(levels)):
        for src_lid in range(int(plane_size)):
            selected_plane_lid = legacy._select_layer_tsv(
                src_lid,
                z,
                plane_size,
                tsv_assignment,
                tsv_candidates,
                dim_x,
                dim_y,
            )
            selection.append((
                _layer_local_id(src_lid, z, plane_size),
                _layer_local_id(selected_plane_lid, z, plane_size),
            ))

    return sorted(set(placement)), selection


def _build_native_down_selection(levels, plane_size, tsv_assignment,
                                 tsv_candidates, dim_x, dim_y,
                                 bottom_attach):
    selection = []
    for z in range(int(levels)):
        for src_lid in range(int(plane_size)):
            src = _layer_local_id(src_lid, z, plane_size)
            if z == 0:
                dst = int(bottom_attach)
            else:
                selected_plane_lid = legacy._select_layer_tsv(
                    src_lid,
                    z,
                    plane_size,
                    tsv_assignment,
                    tsv_candidates,
                    dim_x,
                    dim_y,
                )
                dst = _layer_local_id(selected_plane_lid, z, plane_size)
            selection.append((src, dst))
    return selection


def _build_mesh_graph_native_3d(data):
    params = data.get("params") or {}
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

    topology_hints = data.get("topology_hints") or {}
    gap = int(topology_hints.get("interposer_gap", 1))
    default_base_rows, default_base_cols = legacy._base_dims_from_params(params, gap)
    base_data = data.get("base") if isinstance(data.get("base"), dict) else {}

    base_hint = topology_hints.get("base_interposer_enabled")
    if base_hint is False:
        base_rows = int(base_data.get("rows", 0))
        base_cols = int(base_data.get("cols", 0))
    else:
        base_rows = int(base_data.get("rows", default_base_rows))
        base_cols = int(base_data.get("cols", default_base_cols))

    use_base_mesh = bool(base_rows > 0 and base_cols > 0)
    if base_hint is not None:
        use_base_mesh = bool(base_hint) and use_base_mesh

    chip_rows = int(params["chip_rows"])
    chip_cols = int(params["chip_cols"])
    two5d_width = int(params["two5d_width"])

    layout_base_cols = base_cols if base_cols > 0 else max(1, default_base_cols)
    layout = legacy._infer_layout_from_params(params, layout_base_cols, gap)
    layout = legacy._overlay_layout_with_particle_chiplets(layout, data)
    chromosome = legacy._extract_chromosome(data)
    chiplets = legacy._attach_genes_to_layout(layout, chromosome, data)

    meshes = {}
    order = []
    edges = []
    base_name = "I" if use_base_mesh else None
    if use_base_mesh:
        meshes[base_name] = {
            "name": base_name,
            "dim_x": base_cols,
            "dim_y": base_rows,
            "dim_z": 1,
        }
        order.append(base_name)

    name_idx = 1
    for chip in chiplets:
        chip_type = legacy._norm_chip_type(chip["type"])
        if chip_type == "3d":
            levels = int(chip.get("no_levels", params["threeD_height"]))
            plane_size = chip_cols * chip_rows
            attach_router = int(chip.get("base_attach_router", 0))
            if attach_router < 0:
                attach_router = 0
            max_attach = plane_size * levels - 1
            if max_attach >= 0 and attach_router > max_attach:
                attach_router = max_attach

            tsv_assignment = chip.get("tsv_assignment") or []
            tsv_placement = chip.get("tsv_placement") or []
            if len(tsv_assignment) != plane_size * levels:
                default_assign = [0] * (plane_size * levels)
                tsv_assignment = (list(tsv_assignment) + default_assign)[:plane_size * levels]
            else:
                tsv_assignment = [int(v) for v in tsv_assignment]
            if len(tsv_placement) != plane_size:
                default_place = [0] * plane_size
                tsv_placement = (list(tsv_placement) + default_place)[:plane_size]
            else:
                tsv_placement = [int(v) for v in tsv_placement]

            attach_local = attach_router % plane_size if plane_size > 0 else 0
            tsv_candidates = legacy._derive_tsv_candidates(
                tsv_placement, tsv_assignment, plane_size, attach_local
            )
            intra_placement, intra_selection = _build_intra_tsv_selection(
                levels,
                plane_size,
                tsv_assignment,
                tsv_candidates,
                chip_cols,
                chip_rows,
            )

            name = f"C{name_idx}"
            name_idx += 1
            meshes[name] = {
                "name": name,
                "dim_x": chip_cols,
                "dim_y": chip_rows,
                "dim_z": levels,
                "intra_links_placement": intra_placement,
                "intra_links_selection": intra_selection,
            }
            order.append(name)

            if use_base_mesh:
                vl_coord = chip.get("vl_coord", [0, 0])
                i_router = legacy._router_id_from_coord(vl_coord[0], vl_coord[1], base_cols)
                bottom_attach = attach_router % plane_size
                edges.append({
                    "parent": base_name,
                    "child": name,
                    "parent_router": i_router,
                    "child_router": bottom_attach,
                    "links": [(i_router, bottom_attach)],
                })
                meshes[name]["down_links_selection"] = _build_native_down_selection(
                    levels,
                    plane_size,
                    tsv_assignment,
                    tsv_candidates,
                    chip_cols,
                    chip_rows,
                    bottom_attach,
                )
        else:
            name = f"C{name_idx}"
            name_idx += 1
            interposer = chip.get("interposer") if isinstance(chip.get("interposer"), dict) else {}
            local_side, _ = legacy._default_local_2p5d_plan(params, gap)
            inter_cols = int(interposer.get("cols", local_side))
            inter_rows = int(interposer.get("rows", local_side))
            if inter_cols <= 0 or inter_rows <= 0:
                inter_cols = max(1, chip_cols * max(two5d_width, 1))
                inter_rows = max(1, chip_rows)
            meshes[name] = {
                "name": name,
                "dim_x": inter_cols,
                "dim_y": inter_rows,
                "dim_z": 1,
            }
            order.append(name)

            if use_base_mesh:
                vl_coord = chip.get("vl_coord", [0, 0])
                i_router = legacy._router_id_from_coord(vl_coord[0], vl_coord[1], base_cols)
                inter_attach = int(chip.get("base_attach_router", 0))
                edges.append({
                    "parent": base_name,
                    "child": name,
                    "parent_router": i_router,
                    "child_router": inter_attach,
                })

            sub_specs = legacy._build_subchip_specs_2p5d(chip, params, gap)
            for spec in sub_specs:
                child_name = f"C{name_idx}"
                name_idx += 1
                meshes[child_name] = {
                    "name": child_name,
                    "dim_x": chip_cols,
                    "dim_y": chip_rows,
                    "dim_z": 1,
                }
                order.append(child_name)
                ax, ay = spec["attach_coord"]
                inter_router = legacy._router_id_from_coord(ax, ay, inter_cols)
                local_x = int(ax) % chip_cols
                local_y = int(ay) % chip_rows
                chip_router = local_y * chip_cols + local_x
                edges.append({
                    "parent": name,
                    "child": child_name,
                    "parent_router": inter_router,
                    "child_router": chip_router,
                })

    return base_cols, base_rows, base_name, order, meshes, edges


def build_yaml(data):
    original = legacy._build_mesh_graph
    legacy._build_mesh_graph = _build_mesh_graph_native_3d
    try:
        return legacy.build_yaml(data)
    finally:
        legacy._build_mesh_graph = original


def main():
    args = sys.argv[1:]
    if len(args) not in (1, 2):
        print(
            "Usage:\n"
            "  python native_3d_mesh/generate_yaml_mesh.py <Particle.txt> [output.yaml]"
        )
        sys.exit(1)

    particle_path = legacy._resolve_particle_path(args[0])
    if not particle_path.is_file():
        print(f"Missing required input file: {particle_path}")
        sys.exit(1)

    output_path = Path(args[1]) if len(args) == 2 else particle_path.with_suffix(".native3d.yaml")
    data = legacy._load_particle(particle_path)
    yaml_text = build_yaml(data)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(yaml_text, encoding="utf-8")
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()
