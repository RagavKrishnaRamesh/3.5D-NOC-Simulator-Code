import json
import re
import sys
import math
from pathlib import Path

N_VIRTUAL_CHANNELS = 2

BASELINE_TAIL = """\
# number of flits for each router buffer
buffer_depth: 4
# size of flits, in bits
flit_size: 32
# lenght in mm of router to hub connection
r2h_link_length: 2.0
# lenght in mm of router to router connection
r2r_link_length: 1.0
n_virtual_channels: 2

# Routing algorithms:
#   XY
#   WEST_FIRST
#   DELTA
#   NORTH_LAST
#   NEGATIVE_FIRST
#   ODD_EVEN
#   DYAD
#   TABLE_BASED
# Each of the above labels should match a corresponding
# implementation in the routingAlgorithms source code directory
routing_algorithm: DEPTH_FIRST
routing_table_filename: ""

# Routing specific parameters
#   dyad_threshold: double
dyad_threshold: 0.6

# Selection Strategies:
#   RANDOM
#   BUFFER_LEVEL
#   NOP
# Each of the above labels should match a corresponding
# implementation in the selectionStrategies source code directory
selection_strategy: BUFFER_LEVEL
# If set to false, the multi-noc routing algorithm uses an internal arbiter to
# choose between available routing path and the selection strategy is not used.
route_using_selection_strategy: true
enable_vc_reallocation: true

# SIMULATION PARAMETERS
#
clock_period_ps: 1000
# duration of reset signal assertion, expressed in cycles
reset_time: 1
# overal simulation lenght, expressed in cycles
simulation_time: 200000
# Number of cycles the simulation will continue to 'drain' the networks. This
# is used to check if the routing function allows to route any flit to its
# destination (sent_flit == received_flit).
# In this stage, each PE can just emit the remaining packets of their packet
# queues, but cannot inject new ones.
drain_time: 0
# collect stats after a given number of cycles
stats_warm_up_time: 0
# power breakdown, nodes communication details
detailed: false
# stop after a given amount of load has been processed
max_volume_to_be_drained: 0
show_buffer_stats: false

# Winoc
# enable wireless, when false, all wireless channel configuration is
# ignored
use_winoc: false
# experimental power saving strategy
use_wirxsleep: false

# Verbosity level:
#   VERBOSE_OFF
#   VERBOSE_LOW
#   VERBOSE_MEDIUM
#   VERBOSE_HIGH
verbose_mode: VERBOSE_OFF
# Trace
trace_mode: false
trace_filename: ""

min_packet_size: 8
max_packet_size: 8
packet_injection_rate: 0.005
probability_of_retransmission: 0.01

# Traffic distribution:
#   TRAFFIC_RANDOM
#   TRAFFIC_TRANSPOSE1
#   TRAFFIC_TRANSPOSE2
#   TRAFFIC_HOTSPOT
#   TRAFFIC_TABLE_BASED
#   TRAFFIC_BIT_REVERSAL
#   TRAFFIC_SHUFFLE
#   TRAFFIC_BUTTERFLY
#   TRAFFIC_SINGLE_PACKET
traffic_distribution: TRAFFIC_LOCAL_CHIPLET
# for single packet traffic only
# 'chip' fields are mandatory for MULTI_MESH
traffic_single_packet_src_lid: 2
traffic_single_packet_src_chip: C1
traffic_single_packet_dst_lid: 3
traffic_single_packet_dst_chip: C2
traffic_localized_chiplet_ratio: 0.4
# when traffic table based is specified, use the following
# configuration file
traffic_table_filename: "t.txt"
"""


def _router_id_from_coord(x, y, cols):
    return int(y) * int(cols) + int(x)


def _format_pairs(pairs, indent):
    pad = " " * indent
    lines = []
    for a, b in pairs:
        lines.append(f"{pad}- [ {int(a):2d}, {int(b):2d}]")
    return "\n".join(lines)


def _custom_pe_corners(cols, rows):
    cols = int(cols)
    rows = int(rows)
    if cols <= 0 or rows <= 0:
        return [0]
    return [
        0,
        cols - 1,
        (rows - 1) * cols,
        rows * cols - 1,
    ]


def _load_particle(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _plane_pe_ids(dim_x, dim_y, dim_z, plane_z):
    layer_size = dim_x * dim_y
    base = plane_z * layer_size
    return list(range(base, base + layer_size))


def _local_coord(local_id, dim_x, dim_y):
    layer_size = int(dim_x) * int(dim_y)
    lid = int(local_id) % layer_size
    x = lid % int(dim_x)
    y = lid // int(dim_x)
    z = int(local_id) // layer_size
    return x, y, z


def _nearest_router(src_local, candidates, dim_x, dim_y, include_z=False):
    sx, sy, sz = _local_coord(src_local, dim_x, dim_y)
    best = None
    best_key = None
    for cand in candidates:
        cx, cy, cz = _local_coord(cand, dim_x, dim_y)
        dist = abs(sx - cx) + abs(sy - cy)
        if include_z:
            dist += abs(sz - cz)
        key = (dist, int(cand))
        if best_key is None or key < best_key:
            best_key = key
            best = int(cand)
    return best


def _build_router_to_vlink_selection(router_count, dim_x, dim_y,
                                     vlink_local_ids, intra_map=None):
    if router_count <= 0:
        return []
    valid_vlinks = sorted({
        int(v) for v in vlink_local_ids
        if 0 <= int(v) < int(router_count)
    })
    if not valid_vlinks:
        return []

    layer_size = int(dim_x) * int(dim_y)
    by_layer = {}
    for lid in valid_vlinks:
        by_layer.setdefault(lid // layer_size, []).append(lid)

    intra_map = intra_map or {}
    out = []
    for src in range(int(router_count)):
        src_layer = src // layer_size
        same_layer_vlinks = by_layer.get(src_layer, [])

        if same_layer_vlinks:
            selected = _nearest_router(src, same_layer_vlinks, dim_x, dim_y)
        else:
            selected = intra_map.get(src, -1)
            if not (0 <= int(selected) < int(router_count) and
                    int(selected) // layer_size == src_layer):
                selected = _nearest_router(src, valid_vlinks, dim_x, dim_y,
                                           include_z=True)
            else:
                selected = int(selected)

        out.append((src, selected))
    return out


def _select_layer_tsv(src_lid, layer_z, plane_size, tsv_assignment,
                      tsv_candidates, dim_x, dim_y):
    selected = -1
    src_idx = int(layer_z) * int(plane_size) + int(src_lid)

    if 0 <= src_idx < len(tsv_assignment):
        raw = int(tsv_assignment[src_idx])
        if raw >= 0:
            selected = raw % int(plane_size)

    if selected not in tsv_candidates:
        selected = _nearest_router(int(src_lid), tsv_candidates,
                                   int(dim_x), int(dim_y))
    return int(selected)


def _derive_tsv_candidates(tsv_placement, tsv_assignment, plane_size,
                           fallback_idx):
    candidates = [idx for idx, enabled in enumerate(tsv_placement)
                  if int(enabled) != 0]
    if not candidates:
        derived = set()
        for raw in tsv_assignment:
            v = int(raw)
            if v >= 0:
                derived.add(v % int(plane_size))
        candidates = sorted(derived)
    if not candidates:
        candidates = [int(fallback_idx) % int(plane_size)]
    return sorted(set(int(v) for v in candidates))


def _norm_chip_type(value):
    t = str(value).strip().lower()
    if t in ("3d", "3-d", "3_d"):
        return "3d"
    if t in ("2.5d", "2p5d", "2_5d", "2-5d"):
        return "2.5d"
    raise ValueError(f"Unsupported chip type '{value}'")


def _pack_footprints_on_square(footprints, side, gap):
    placements = {}
    x = 0
    y = 0
    row_h = 0

    for fp in footprints:
        key = fp["key"]
        w = int(fp["w"])
        h = int(fp["h"])
        if w > int(side) or h > int(side):
            return None

        if x > 0 and x + w > int(side):
            y += row_h + int(gap)
            x = 0
            row_h = 0

        if y + h > int(side):
            return None

        placements[key] = (x, y, w, h)
        x += w + int(gap)
        row_h = max(row_h, h)

    return placements


def _compute_square_plan(footprints, gap):
    if not footprints:
        return 0, {}

    max_w = max(int(fp["w"]) for fp in footprints)
    max_h = max(int(fp["h"]) for fp in footprints)
    total_area = sum(int(fp["w"]) * int(fp["h"]) for fp in footprints)
    side = max(max_w, max_h, int(math.ceil(math.sqrt(total_area))))

    while True:
        placements = _pack_footprints_on_square(footprints, side, gap)
        if placements is not None:
            return int(side), placements
        side += 1


def _local_2p5d_footprints(params):
    chip_rows = int(params["chip_rows"])
    chip_cols = int(params["chip_cols"])
    two5d_width = int(params["two5d_width"])
    out = []
    for c in range(max(0, two5d_width)):
        out.append({
            "key": c,
            "w": chip_cols,
            "h": chip_rows,
        })
    return out


def _default_local_2p5d_plan(params, gap):
    return _compute_square_plan(_local_2p5d_footprints(params), gap)


def _base_dims_from_params(params, gap):
    num_slots = int(params["num_3d_units"]) + int(params["num_2p5d_units"])
    slot_stride = int(gap) + 1
    cols = max(4, 2 + max(num_slots - 1, 0) * slot_stride)
    rows = 4
    return rows, cols


def _infer_layout_from_params(params, base_cols, gap):
    chip_rows = int(params["chip_rows"])
    chip_cols = int(params["chip_cols"])
    two5d_width = int(params["two5d_width"])
    threeD_height = int(params["threeD_height"])
    num_3d_units = int(params["num_3d_units"])
    num_2p5d_units = int(params["num_2p5d_units"])

    routers_per_2d = chip_rows * chip_cols
    slot_stride = int(gap) + 1
    x = int(gap)
    next_id = 0
    layout = []

    for i in range(num_3d_units):
        no_routers = routers_per_2d * threeD_height
        start_id = next_id
        end_id = next_id + no_routers - 1
        layout.append({
            "type": "3d",
            "name": f"3D_{i}",
            "vl_coord": [x, 1],
            "range": [start_id, end_id],
            "no_routers": no_routers,
            "no_levels": threeD_height,
        })
        next_id += no_routers
        x += slot_stride

    for i in range(num_2p5d_units):
        no_routers = routers_per_2d * two5d_width
        start_id = next_id
        end_id = next_id + no_routers - 1
        if x >= base_cols:
            x = int(gap)
        layout.append({
            "type": "2.5d",
            "name": f"2p5D_{i}",
            "vl_coord": [x, 3],
            "range": [start_id, end_id],
            "no_routers": no_routers,
        })
        next_id += no_routers
        x += slot_stride

    return layout


def _extract_chromosome(data):
    chromosome = data.get("chromosome")
    if isinstance(chromosome, list):
        return chromosome

    cs = data.get("chromosome_structure") or {}
    chromosome = cs.get("best_chromosome_raw")
    if isinstance(chromosome, list):
        return chromosome

    chips = data.get("chiplets")
    if not isinstance(chips, list):
        return None

    genes = []
    for chip in chips:
        try:
            t = _norm_chip_type(chip.get("type"))
        except Exception:
            return None
        if t == "3d":
            if all(k in chip for k in ("core_to_router", "tsv_placement", "tsv_assignment", "base_attach_router")):
                genes.append([
                    chip["core_to_router"],
                    chip["tsv_placement"],
                    chip["tsv_assignment"],
                    chip["base_attach_router"],
                ])
            else:
                return None
        else:
            if all(k in chip for k in ("core_to_router", "base_attach_router")):
                genes.append([chip["core_to_router"], chip["base_attach_router"]])
            else:
                return None
    return genes


def _overlay_layout_with_particle_chiplets(layout, data):
    raw_chiplets = data.get("chiplets")
    if not isinstance(raw_chiplets, list):
        return layout

    merged = [dict(chip) for chip in layout]
    count = min(len(merged), len(raw_chiplets))
    for idx in range(count):
        src = raw_chiplets[idx]
        dst = merged[idx]
        if "type" in src:
            dst["type"] = _norm_chip_type(src["type"])
        if "name" in src:
            dst["name"] = src["name"]
        if "vl_coord" in src and isinstance(src["vl_coord"], (list, tuple)) and len(src["vl_coord"]) == 2:
            dst["vl_coord"] = [int(src["vl_coord"][0]), int(src["vl_coord"][1])]
        if "range" in src and isinstance(src["range"], (list, tuple)) and len(src["range"]) == 2:
            dst["range"] = [int(src["range"][0]), int(src["range"][1])]
        if "no_routers" in src:
            dst["no_routers"] = int(src["no_routers"])
        if dst["type"] == "3d" and "no_levels" in src:
            dst["no_levels"] = int(src["no_levels"])
        if "interposer" in src:
            dst["interposer"] = src["interposer"]

    return merged


def _attach_genes_to_layout(layout, chromosome, data):
    chip_rows = int(data["params"]["chip_rows"])
    chip_cols = int(data["params"]["chip_cols"])
    routers_per_2d = chip_rows * chip_cols
    raw_chiplets = data.get("chiplets") if isinstance(data.get("chiplets"), list) else []

    out = []
    for idx, chip in enumerate(layout):
        entry = dict(chip)
        gene = chromosome[idx] if chromosome is not None and idx < len(chromosome) else None
        raw = raw_chiplets[idx] if idx < len(raw_chiplets) else {}

        if entry["type"] == "3d":
            levels = int(entry.get("no_levels", data["params"]["threeD_height"]))
            plane_size = routers_per_2d
            default_tsv_place = [0] * plane_size
            default_tsv_assign = [0] * int(entry["no_routers"])
            if gene is not None and len(gene) >= 4:
                entry["core_to_router"] = [int(v) for v in gene[0]]
                entry["tsv_placement"] = [int(v) for v in gene[1]]
                entry["tsv_assignment"] = [int(v) for v in gene[2]]
                entry["base_attach_router"] = int(gene[3])
            else:
                entry["core_to_router"] = [int(v) for v in raw.get("core_to_router", [])]
                entry["tsv_placement"] = [int(v) for v in raw.get("tsv_placement", default_tsv_place)]
                entry["tsv_assignment"] = [int(v) for v in raw.get("tsv_assignment", default_tsv_assign)]
                entry["base_attach_router"] = int(raw.get("base_attach_router", 0))

            if len(entry["tsv_placement"]) != plane_size:
                entry["tsv_placement"] = (entry["tsv_placement"] + default_tsv_place)[:plane_size]
            if len(entry["tsv_assignment"]) != plane_size * levels:
                entry["tsv_assignment"] = (entry["tsv_assignment"] + default_tsv_assign)[:plane_size * levels]
        else:
            if gene is not None and len(gene) >= 2:
                entry["core_to_router"] = [int(v) for v in gene[0]]
                entry["base_attach_router"] = int(gene[1])
            else:
                entry["core_to_router"] = [int(v) for v in raw.get("core_to_router", [])]
                entry["base_attach_router"] = int(raw.get("base_attach_router", 0))

        out.append(entry)

    return out


def _build_subchip_specs_2p5d(chip, params, gap):
    chip_rows = int(params["chip_rows"])
    chip_cols = int(params["chip_cols"])
    two5d_width = int(params["two5d_width"])
    routers_per_2d = chip_rows * chip_cols

    interposer = chip.get("interposer") if isinstance(chip.get("interposer"), dict) else {}
    subchiplets = interposer.get("chiplets") if isinstance(interposer.get("chiplets"), dict) else None
    specs = []

    if subchiplets:
        for sub_name, spec in sorted(subchiplets.items(), key=lambda kv: kv[1]["range"][0]):
            s, e = spec["range"]
            attach = spec.get("attach_coord")
            if attach is None:
                attach = [chip_cols - 1, chip_rows - 1]
            specs.append({
                "name": sub_name,
                "range": [int(s), int(e)],
                "attach_coord": [int(attach[0]), int(attach[1])],
            })
        return specs

    local_side, placements = _default_local_2p5d_plan(params, gap)
    rows = int(interposer.get("rows", local_side))
    cols = int(interposer.get("cols", local_side))
    if rows > 0 and cols > 0 and rows == cols:
        fixed = _pack_footprints_on_square(_local_2p5d_footprints(params), rows, gap)
        if fixed is not None:
            placements = fixed

    start_id = int(chip["range"][0])
    for c in range(two5d_width):
        s = start_id + c * routers_per_2d
        e = s + routers_per_2d - 1
        if c in placements:
            px, py, pw, ph = placements[c]
            attach = [int(px + pw - 1), int(py + ph - 1)]
        else:
            attach = [(c + 1) * chip_cols - 1, chip_rows - 1]
        specs.append({
            "name": f"{chip.get('name', '2p5D')}_C{c}",
            "range": [int(s), int(e)],
            "attach_coord": attach,
        })
    return specs


def _build_mesh_graph(data):
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
    default_base_rows, default_base_cols = _base_dims_from_params(params, gap)
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
    layout = _infer_layout_from_params(params, layout_base_cols, gap)
    layout = _overlay_layout_with_particle_chiplets(layout, data)
    chromosome = _extract_chromosome(data)
    chiplets = _attach_genes_to_layout(layout, chromosome, data)

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
        chip_type = _norm_chip_type(chip["type"])
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
            tsv_candidates = _derive_tsv_candidates(
                tsv_placement, tsv_assignment, plane_size, attach_local
            )

            layer_names = []
            for _z in range(levels):
                name = f"C{name_idx}"
                name_idx += 1
                meshes[name] = {
                    "name": name,
                    "dim_x": chip_cols,
                    "dim_y": chip_rows,
                    "dim_z": 1,
                }
                order.append(name)
                layer_names.append(name)

            if use_base_mesh:
                vl_coord = chip.get("vl_coord", [0, 0])
                i_router = _router_id_from_coord(vl_coord[0], vl_coord[1], base_cols)

                # Base interposer <-> first 3D layer
                edges.append({
                    "parent": base_name,
                    "child": layer_names[0],
                    "parent_router": i_router,
                    "child_router": attach_local,
                    "links": [(i_router, attach_local)],
                })
                meshes[layer_names[0]]["down_links_selection"] = [
                    (src, attach_local) for src in range(plane_size)
                ]

            # Stack layer z with layer z+1 through TSV columns
            for z in range(max(0, levels - 1)):
                parent_name = layer_names[z]
                child_name = layer_names[z + 1]
                links = [(idx, idx) for idx in tsv_candidates]
                edges.append({
                    "parent": parent_name,
                    "child": child_name,
                    "parent_router": links[0][0],
                    "child_router": links[0][1],
                    "links": links,
                })

                up_sel = []
                down_sel = []
                for src in range(plane_size):
                    up_sel.append((
                        src,
                        _select_layer_tsv(src, z, plane_size, tsv_assignment,
                                          tsv_candidates, chip_cols, chip_rows)
                    ))
                    down_sel.append((
                        src,
                        _select_layer_tsv(src, z + 1, plane_size, tsv_assignment,
                                          tsv_candidates, chip_cols, chip_rows)
                    ))

                meshes[parent_name].setdefault(
                    "up_links_selection_by_child", {}
                )[child_name] = up_sel
                meshes[child_name]["down_links_selection"] = down_sel
        else:
            name = f"C{name_idx}"
            name_idx += 1
            interposer = chip.get("interposer") if isinstance(chip.get("interposer"), dict) else {}
            local_side, _ = _default_local_2p5d_plan(params, gap)
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
                i_router = _router_id_from_coord(vl_coord[0], vl_coord[1], base_cols)
                inter_attach = int(chip.get("base_attach_router", 0))
                edges.append({
                    "parent": base_name,
                    "child": name,
                    "parent_router": i_router,
                    "child_router": inter_attach,
                })

            sub_specs = _build_subchip_specs_2p5d(chip, params, gap)
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
                inter_router = _router_id_from_coord(ax, ay, inter_cols)
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
    base_cols, base_rows, base_name, order, meshes, edges = _build_mesh_graph(data)

    children_map = {name: [] for name in meshes}
    parent_map = {}
    for edge in edges:
        children_map[edge["parent"]].append(edge)
        if edge["child"] in parent_map:
            raise ValueError(f"Chiplet {edge['child']} has multiple parents")
        parent_map[edge["child"]] = edge

    lines = []
    lines.append("# (C) Copyright 2025 CEA LIST. All Rights Reserved.")
    lines.append("# Contributor(s): Davy Million (davy.million@cea.fr)")
    lines.append("#")
    if base_name is not None:
        lines.append("# This yaml file describes a 3.5D multi-chip topology with one base interposer")
        lines.append("# and stacked chiplets. Each chip has 2 VCs.")
    else:
        lines.append("# This yaml file describes a 3.5D multi-chip topology without a base interposer")
        lines.append("# (single-unit mode). Each chip has 2 VCs.")
    lines.append("")
    lines.append("topology: MULTI_MESH")
    lines.append("")
    lines.append("multi_mesh:")

    for name in order:
        mesh = meshes[name]
        lines.append(f"  {name}:")
        lines.append(f"    dim_x: {int(mesh['dim_x'])}")
        lines.append(f"    dim_y: {int(mesh['dim_y'])}")
        lines.append(f"    dim_z: {int(mesh['dim_z'])}")
        lines.append(f"    n_virtual_channels: {N_VIRTUAL_CHANNELS}")
        if name == base_name:
            custom_pe = _custom_pe_corners(base_cols, base_rows)
            custom_pe_str = ", ".join(str(v) for v in custom_pe)
            lines.append(f"    custom_pe: [{custom_pe_str}]")
        elif "custom_pe" in mesh:
            custom_pe_str = ", ".join(str(v) for v in mesh["custom_pe"])
            lines.append(f"    custom_pe: [{custom_pe_str}]")

        up_links = children_map.get(name) or []
        down_link = parent_map.get(name)
        intra_placement = mesh.get("intra_links_placement") or []
        if up_links or down_link or intra_placement:
            lines.append("    vertical_links_placement:")
            if up_links:
                lines.append("      up:")
                for link in up_links:
                    link_pairs = link.get("links")
                    if not link_pairs:
                        link_pairs = [(link["parent_router"], link["child_router"])]
                    lines.append(f"        {link['child']}:")
                    lines.append(_format_pairs(link_pairs, 10))
            if down_link:
                down_pairs = down_link.get("links")
                if not down_pairs:
                    down_pairs = [(down_link["parent_router"], down_link["child_router"])]
                down_pairs = [(b, a) for a, b in down_pairs]
                lines.append("      down:")
                lines.append(_format_pairs(down_pairs, 10))
            if intra_placement:
                lines.append("      intra:")
                for lid in intra_placement:
                    lines.append(f"        - {int(lid):2d}")

        intra_selection = mesh.get("intra_links_selection") or []
        if up_links or down_link or intra_selection:
            lines.append("")
            lines.append("    vertical_links_selection:")
            router_count = int(mesh["dim_x"]) * int(mesh["dim_y"]) * int(mesh["dim_z"])
            intra_map = {int(src): int(dst) for src, dst in intra_selection}
            if up_links:
                lines.append("      up:")
                custom_up_sel = mesh.get("up_links_selection_by_child", {})
                for link in up_links:
                    lines.append(f"        {link['child']}:")
                    selection_pairs = custom_up_sel.get(link["child"])
                    if not selection_pairs:
                        link_pairs = link.get("links")
                        if not link_pairs:
                            link_pairs = [(link["parent_router"], link["child_router"])]
                        candidates = [int(a) for a, _ in link_pairs]
                        selection_pairs = _build_router_to_vlink_selection(
                            router_count,
                            int(mesh["dim_x"]),
                            int(mesh["dim_y"]),
                            candidates,
                            intra_map,
                        )
                    lines.append(_format_pairs(selection_pairs, 10))
            if down_link:
                lines.append("      down:")
                selection_pairs = mesh.get("down_links_selection")
                if not selection_pairs:
                    down_pairs = down_link.get("links")
                    if not down_pairs:
                        down_pairs = [(down_link["parent_router"], down_link["child_router"])]
                    candidates = [int(b) for _, b in down_pairs]
                    selection_pairs = _build_router_to_vlink_selection(
                        router_count,
                        int(mesh["dim_x"]),
                        int(mesh["dim_y"]),
                        candidates,
                        intra_map,
                    )
                lines.append(_format_pairs(selection_pairs, 8))
            if intra_selection:
                lines.append("      intra:")
                lines.append(_format_pairs(intra_selection, 8))

        lines.append("")

    lines.append(BASELINE_TAIL.rstrip())
    lines.append("")
    return "\n".join(lines)


def _parse_index(value):
    try:
        return int(value)
    except ValueError:
        return None


_PARTICLE_RE = re.compile(
    r"^(?:GA_Particle|SA_Particle|SA35_Particle|SA25_Particle|PSO35_Particle|PSO25_Particle|PSO_Particle|Particle)(?P<graph_id>\d+)$",
    re.IGNORECASE,
)


def _known_particle_dirs():
    return [
        Path("."),
        Path("Particles"),
        Path("GA_Particles"),
        Path("SA35_Particles"),
        Path("SA25_Particles"),
        Path("PSO35_Particles"),
        Path("PSO25_Particles"),
        Path("PSO_Particles"),
        Path("Chiplet_code_2.5D") / "1_vertical_pso",
        Path("Chiplet_code_2.5D") / "simulated_annealing",
    ]


def _resolve_particle_path(input_value):
    raw = Path(input_value)
    if raw.is_file():
        return raw

    base = raw.name
    variants = [base]
    if not base.lower().endswith(".txt"):
        variants.append(f"{base}.txt")

    for root in _known_particle_dirs():
        for name in variants:
            candidate = root / name
            if candidate.is_file():
                return candidate
    return raw


def _resolve_particle_by_index(index):
    idx = int(index)
    names = [
        f"GA_Particle{idx}.txt",
        f"SA_Particle{idx}.txt",
        f"SA35_Particle{idx}.txt",
        f"SA25_Particle{idx}.txt",
        f"PSO35_Particle{idx}.txt",
        f"PSO25_Particle{idx}.txt",
        f"PSO_Particle{idx}.txt",
        f"Particle{idx}.txt",
    ]
    for root in _known_particle_dirs():
        for name in names:
            candidate = root / name
            if candidate.is_file():
                return candidate
    return Path(names[0])


def _particle_base_and_id(path):
    stem = Path(path).stem
    base_name = stem
    match = _PARTICLE_RE.match(base_name)
    if not match:
        raise ValueError(f"Cannot extract graph id from '{path}'")
    return base_name, int(match.group("graph_id"))


def _resolve_logger_dir(name):
    candidates = [Path(name), Path(f"{name}_results")]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return None


def _process_particle_file(particle_path, output_path=None):
    data = _load_particle(particle_path)
    yaml_text = build_yaml(data)
    out_path = Path(output_path) if output_path is not None else Path(particle_path).with_suffix(".yaml")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(yaml_text, encoding="utf-8")
    return out_path


def _process_logger_particles(logger_name):
    source_dir = _resolve_logger_dir(logger_name)
    if source_dir is None:
        print(f"Skipping {logger_name}: directory not found (checked {logger_name}/ and {logger_name}_results/)")
        return 0, 0

    processed = 0
    failed = 0
    for particle_path in sorted(source_dir.glob("*.txt")):
        try:
            _particle_base_and_id(particle_path)
        except Exception as exc:  # noqa: BLE001
            print(f"[{logger_name}] Skipping {particle_path.name}: {exc}")
            failed += 1
            continue

        try:
            out_path = _process_particle_file(particle_path)
        except Exception as exc:  # noqa: BLE001
            print(f"[{logger_name}] Failed {particle_path.name}: {exc}")
            failed += 1
            continue

        processed += 1
        print(f"[{logger_name}] Wrote {out_path}")

    return processed, failed


def _process_all_loggers():
    total = 0
    failed = 0
    for logger_name in ("PSO_logger", "SA_logger"):
        p_count, f_count = _process_logger_particles(logger_name)
        total += p_count
        failed += f_count

    if total == 0:
        print("No particle files processed from PSO_logger or SA_logger.")
    if failed:
        print(f"Encountered {failed} error(s) while processing logger directories.")


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("--process-loggers", "--loggers", "--batch-loggers"):
        _process_all_loggers()
        return

    if len(args) not in (1, 2):
        print(
            "Usage:\n"
            "  python generate_yaml.py <graph_id> [output.yaml]\n"
            "  python generate_yaml.py <Particle.txt> [output.yaml]\n"
            "  # default output: same folder/name as particle, with .yaml\n"
            "  python generate_yaml.py --process-loggers"
        )
        sys.exit(1)

    index = _parse_index(args[0])
    if index is not None:
        particle_path = _resolve_particle_by_index(index)
        missing = [path for path in (particle_path,) if not path.is_file()]
        if missing:
            missing_str = ", ".join(str(path) for path in missing)
            print(f"Missing required input file(s): {missing_str}")
            sys.exit(1)
        output_path = Path(args[1]) if len(args) == 2 else particle_path.with_suffix(".yaml")
    else:
        particle_path = _resolve_particle_path(args[0])
        if not particle_path.is_file():
            print(f"Missing required input file: {particle_path}")
            sys.exit(1)
        output_path = Path(args[1]) if len(args) == 2 else particle_path.with_suffix(".yaml")

    data = _load_particle(particle_path)
    yaml_text = build_yaml(data)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(yaml_text, encoding="utf-8")
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()
