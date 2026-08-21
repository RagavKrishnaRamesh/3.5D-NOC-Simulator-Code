"""
PSO-based 3.5D NoC / Multi-Chiplet Topology Optimizer

This version follows the discrete PSO structure used in the 2.5D PSO flow,
keeps the 3.5D topology/cost/TSV logic local to this file, and writes the
final particle in the same JSON schema used by the GA flow.

Usage:
  python pso_3p5d.py <GraphNameWithoutExt>
                     <chip_rows> <chip_cols>
                     <two5d_width> <threeD_height>
                     <num_2p5d_units> <num_3d_units>
                     <iterations> <swarm_size>
"""

import argparse
import copy
import json
import math
import os
import random
import re
import time

try:
    from edge_set_creation import create_edge_set
except ImportError:
    create_edge_set = None


# =========================
# Tunable PSO / latency parameters
# =========================

INTRACHIP_LATENCY = 1.0
INTERPOSER_LATENCY = 1.0
VL_LATENCY = 1.0

INERTIA_PROB = 0.10
COGNITIVE_PROB = 0.04
SOCIAL_PROB = 0.02

CONVERGENCE_STALL_LIMIT = 200
MIN_INTERPOSER_GAP = 1
TSV_REBUILD_ATTEMPTS = 3
W_FACTOR = 0.5
RANDOM_SEED = None


# =========================
# Global topology / normalization state
# =========================

CHIP_ROWS = None
CHIP_COLS = None
BASE_ROWS = None
BASE_COLS = None
BASE_INTERPOSER_ENABLED = True
NUM_3D_CHIPLETS = 0
MAX_COMM_COST = 1.0
VAR_COMM_SQ = 1.0

base_icrt = {}
INF = float("inf")
tsv_assignment_global = {}
current_particle_state = None
TSV_ASSIGNMENT_RANDOM = 0
TSV_ASSIGNMENT_ELEVATOR_FIRST = 1
TSV_ASSIGNMENT_MODE = TSV_ASSIGNMENT_RANDOM


# =========================
# Base interposer / topology construction
# =========================

def add_base_vl(x, y, t, start_id, end_id, chiplet_name, interposer=None,
                enforce_bounds=True, enforce_gap=True):
    """Register a vertical-link stack on the base interposer."""
    if enforce_bounds and not (0 <= x < BASE_COLS and 0 <= y < BASE_ROWS):
        raise ValueError(f"VL ({x},{y}) out of bounds for {BASE_COLS}x{BASE_ROWS}")
    if (x, y) in base_icrt:
        raise ValueError(f"Duplicate VL at ({x},{y})")
    if enforce_gap:
        for bx, by in base_icrt:
            if max(abs(x - bx), abs(y - by)) <= MIN_INTERPOSER_GAP:
                raise ValueError(
                    f"VL ({x},{y}) too close to existing stack at ({bx},{by}); "
                    f"need at least {MIN_INTERPOSER_GAP} empty base slot(s) of spacing"
                )

    for meta in base_icrt.values():
        s, e = meta["range"]
        if not (end_id < s or start_id > e):
            raise ValueError(f"ID range {start_id}-{end_id} overlaps with existing {s}-{e}")

    entry = {
        "type": t,
        "chiplet": chiplet_name,
        "range": (start_id, end_id),
    }
    if t == "2.5d" and interposer is not None:
        entry["interposer"] = interposer

    base_icrt[(x, y)] = entry


def build_2p5d_interposer(rows, cols, chiplet_specs):
    """Build local interposer metadata for one 2.5D complex."""
    chiplets = {}
    used_ranges = []

    for name, (ax, ay), (s, e) in chiplet_specs:
        if not (0 <= ax < cols and 0 <= ay < rows):
            raise ValueError(f"{name} attach ({ax},{ay}) out of bounds for {cols}x{rows}")
        for ps, pe in used_ranges:
            if not (e < ps or s > pe):
                raise ValueError(f"{name} range {s}-{e} overlaps with {ps}-{pe}")
        used_ranges.append((s, e))
        chiplets[name] = {"attach_coord": (ax, ay), "range": (s, e)}

    return {"rows": rows, "cols": cols, "chiplets": chiplets}


def _pack_footprints_on_square(footprints, side, gap):
    """Greedy shelf-packing of chiplet footprints into a square."""
    placements = {}
    x = 0
    y = 0
    row_h = 0

    for fp in footprints:
        key = fp["key"]
        w = fp["w"]
        h = fp["h"]

        if w > side or h > side:
            return None

        if x > 0 and x + w > side:
            y += row_h + gap
            x = 0
            row_h = 0

        if y + h > side:
            return None

        placements[key] = (x, y, w, h)
        x += w + gap
        row_h = max(row_h, h)

    return placements


def _compute_square_base_plan(footprints, gap):
    """Compute the minimum square side that fits all footprints."""
    if not footprints:
        return 0, {}

    max_w = max(fp["w"] for fp in footprints)
    max_h = max(fp["h"] for fp in footprints)
    total_area = sum(fp["w"] * fp["h"] for fp in footprints)
    side = max(max_w, max_h, int(math.ceil(math.sqrt(total_area))))

    while True:
        placements = _pack_footprints_on_square(footprints, side, gap)
        if placements is not None:
            return side, placements
        side += 1


def _compute_square_local_2p5d_plan(two5d_width, gap):
    """Build the square local-interposer packing plan for one 2.5D complex."""
    if two5d_width <= 0:
        return 0, {}

    local_footprints = []
    for c in range(two5d_width):
        local_footprints.append({
            "key": c,
            "w": CHIP_COLS,
            "h": CHIP_ROWS,
        })
    return _compute_square_base_plan(local_footprints, gap)


def build_topology(chip_rows, chip_cols,
                   two5d_width, threeD_height,
                   num_2p5d_units, num_3d_units):
    """Build the heterogeneous 3.5D topology and particle-state metadata."""
    global CHIP_ROWS, CHIP_COLS, BASE_ROWS, BASE_COLS, base_icrt
    global NUM_3D_CHIPLETS, BASE_INTERPOSER_ENABLED

    CHIP_ROWS = chip_rows
    CHIP_COLS = chip_cols
    base_icrt = {}
    NUM_3D_CHIPLETS = num_3d_units

    routers_per_2d = CHIP_ROWS * CHIP_COLS
    chiplet_layout = []
    next_id = 0
    local_2p5d_side = 0
    local_2p5d_placements = {}

    if num_2p5d_units > 0:
        local_2p5d_side, local_2p5d_placements = _compute_square_local_2p5d_plan(
            two5d_width, MIN_INTERPOSER_GAP
        )

    num_slots = num_3d_units + num_2p5d_units
    if num_slots <= 0:
        raise ValueError("At least one chiplet unit is required")

    BASE_INTERPOSER_ENABLED = num_slots > 1

    footprints = []
    for i in range(num_3d_units):
        footprints.append({
            "key": ("3d", i),
            "w": CHIP_COLS,
            "h": CHIP_ROWS,
        })
    for i in range(num_2p5d_units):
        footprints.append({
            "key": ("2.5d", i),
            "w": local_2p5d_side,
            "h": local_2p5d_side,
        })

    if BASE_INTERPOSER_ENABLED:
        side, placements = _compute_square_base_plan(footprints, MIN_INTERPOSER_GAP)
        BASE_ROWS = side
        BASE_COLS = side
    else:
        BASE_ROWS = 0
        BASE_COLS = 0
        placements = {footprints[0]["key"]: (0, 0, footprints[0]["w"], footprints[0]["h"])}

    for i in range(num_3d_units):
        no_levels = threeD_height
        no_routers = routers_per_2d * no_levels
        start_id = next_id
        end_id = next_id + no_routers - 1

        px, py, pw, ph = placements[("3d", i)]
        if BASE_INTERPOSER_ENABLED:
            vlx = px + pw - 1
            vly = py + ph - 1
        else:
            vlx, vly = (0, 0)

        add_base_vl(
            vlx, vly, "3d", start_id, end_id, f"3D_{i}",
            enforce_bounds=BASE_INTERPOSER_ENABLED,
            enforce_gap=BASE_INTERPOSER_ENABLED,
        )

        chiplet_layout.append({
            "type": "3d",
            "name": f"3D_{i}",
            "no_routers": no_routers,
            "no_levels": no_levels,
            "vl_coord": (vlx, vly),
            "range": (start_id, end_id),
        })
        next_id += no_routers

    for i in range(num_2p5d_units):
        local_rows = local_2p5d_side
        local_cols = local_2p5d_side
        chip_specs = []

        for c in range(two5d_width):
            cs = next_id
            ce = next_id + routers_per_2d - 1
            px_c, py_c, pw_c, ph_c = local_2p5d_placements[c]
            att_x = px_c + pw_c - 1
            att_y = py_c + ph_c - 1
            chip_specs.append((f"C{i}_{c}", (att_x, att_y), (cs, ce)))
            next_id += routers_per_2d

        interposer = build_2p5d_interposer(local_rows, local_cols, chip_specs)

        start_id = chip_specs[0][2][0]
        end_id = chip_specs[-1][2][1]
        px, py, pw, ph = placements[("2.5d", i)]
        if BASE_INTERPOSER_ENABLED:
            vlx = px + pw - 1
            vly = py + ph - 1
        else:
            vlx, vly = (0, 0)

        add_base_vl(
            vlx, vly, "2.5d", start_id, end_id, f"2p5D_{i}",
            interposer=interposer,
            enforce_bounds=BASE_INTERPOSER_ENABLED,
            enforce_gap=BASE_INTERPOSER_ENABLED,
        )

        chiplet_layout.append({
            "type": "2.5d",
            "name": f"2p5D_{i}",
            "no_routers": routers_per_2d * two5d_width,
            "vl_coord": (vlx, vly),
            "range": (start_id, end_id),
            "interposer": interposer,
        })

    return chiplet_layout, next_id


# =========================
# Coordinate helpers
# =========================

def _find_stack_for_router(global_router_id):
    for (bx, by), meta in base_icrt.items():
        s, e = meta["range"]
        if s <= global_router_id <= e:
            return (bx, by), meta
    return None, None


def _local_coords_3d(global_router_id, start_id, levels):
    size = CHIP_ROWS * CHIP_COLS
    idx = global_router_id - start_id
    layer = idx // size
    within = idx % size
    ly = within // CHIP_COLS
    lx = within % CHIP_COLS
    return (lx, ly, layer)


def _local_coords_2d(global_router_id, start_id):
    idx = global_router_id - start_id
    ly = idx // CHIP_COLS
    lx = idx % CHIP_COLS
    return (lx, ly)


def _locate_in_2p5d(global_router_id, base_coord, meta_2p5d):
    interposer = meta_2p5d["interposer"]
    cols = interposer["cols"]
    rows = interposer["rows"]

    for name, spec in interposer["chiplets"].items():
        s, e = spec["range"]
        if s <= global_router_id <= e:
            lx, ly = _local_coords_2d(global_router_id, s)
            return {
                "type": "2.5d",
                "chiplet": name,
                "local_coords": (lx, ly),
                "chiplet_to_local_interposer_vl": spec["attach_coord"],
                "local_interposer_bottom_right": (cols - 1, rows - 1),
                "local_interposer_to_global_vl": base_coord,
            }

    raise ValueError(f"Router {global_router_id} not found in any 2.5D chiplet")


def locate_router(global_router_id):
    base_coord, meta = _find_stack_for_router(global_router_id)
    if meta is None:
        raise ValueError(f"Global router {global_router_id} not mapped in base_icrt")

    start_id, end_id = meta["range"]

    if meta["type"] == "3d":
        levels = (end_id - start_id + 1) // (CHIP_ROWS * CHIP_COLS)
        lx, ly, lz = _local_coords_3d(global_router_id, start_id, levels)
        return {
            "type": "3d",
            "chiplet": meta["chiplet"],
            "local_coords": (lx, ly, lz),
            "base_attach_coord": base_coord,
        }

    if meta["type"] == "2.5d":
        return _locate_in_2p5d(global_router_id, base_coord, meta)

    raise ValueError(f"Unsupported type '{meta['type']}'")


# =========================
# Cost helpers
# =========================

def _3d_chiplet_params(router_id):
    _, meta = _find_stack_for_router(router_id)
    if meta is None or meta["type"] != "3d":
        raise ValueError(f"Router {router_id} not in a 3D chiplet")
    start_id, end_id = meta["range"]
    routers_per_level = CHIP_ROWS * CHIP_COLS
    levels = (end_id - start_id + 1) // routers_per_level
    return start_id, end_id, levels, routers_per_level


def _walk_3d_to_level(src_router, dest_level, start_id, end_id, levels, routers_per_level):
    current_router = src_router
    cost = 0.0

    while True:
        cx, cy, cz = _local_coords_3d(current_router, start_id, levels)
        if cz == dest_level:
            break

        direction = 1 if dest_level > cz else -1

        tsv_r = tsv_assignment_global.get(current_router, current_router)
        if not (start_id <= tsv_r <= end_id):
            tsv_r = current_router
        tx, ty, tz = _local_coords_3d(tsv_r, start_id, levels)
        if tz != cz:
            tx, ty, tz = cx, cy, cz

        cost += (abs(cx - tx) + abs(cy - ty)) * INTRACHIP_LATENCY

        next_z = tz + direction
        if next_z < 0 or next_z >= levels:
            return cost, None

        current_router = start_id + next_z * routers_per_level + ty * CHIP_COLS + tx
        cost += VL_LATENCY

    return cost, current_router


def _same_chiplet_3d_cost(src, dest):
    start_id, end_id, levels, routers_per_level = _3d_chiplet_params(src)
    sx, sy, sz = _local_coords_3d(src, start_id, levels)
    dx, dy, dz = _local_coords_3d(dest, start_id, levels)

    if sz == dz:
        return (abs(sx - dx) + abs(sy - dy)) * INTRACHIP_LATENCY

    cost, current_router = _walk_3d_to_level(
        src, dz, start_id, end_id, levels, routers_per_level
    )
    if current_router is None:
        return INF

    cx, cy, _ = _local_coords_3d(current_router, start_id, levels)
    cost += (abs(cx - dx) + abs(cy - dy)) * INTRACHIP_LATENCY
    return cost


def _3d_to_base_cost(router_id, info):
    start_id, end_id, levels, routers_per_level = _3d_chiplet_params(router_id)
    _, _, sz = _local_coords_3d(router_id, start_id, levels)

    chip_idx = int(info["chiplet"].split("_")[1])
    base_attach_router = int(current_particle_state[chip_idx][3])
    ax = int(base_attach_router % CHIP_COLS)
    ay = int(base_attach_router // CHIP_COLS)

    cost = 0.0
    current_router = router_id
    if sz != 0:
        cost, current_router = _walk_3d_to_level(
            router_id, 0, start_id, end_id, levels, routers_per_level
        )
        if current_router is None:
            return INF

    cx, cy, _ = _local_coords_3d(current_router, start_id, levels)
    cost += (abs(cx - ax) + abs(cy - ay)) * INTRACHIP_LATENCY
    cost += VL_LATENCY
    return cost


def _base_to_3d_cost(router_id, info):
    return _3d_to_base_cost(router_id, info)


def _2p5d_to_base_cost(info):
    lx, ly = info["local_coords"]
    att_x, att_y = info["chiplet_to_local_interposer_vl"]

    chip_idx = int(info["chiplet"].split("_")[0][1:])
    state_idx = NUM_3D_CHIPLETS + chip_idx
    base_attach_router = int(current_particle_state[state_idx][1])

    interposer = base_icrt[info["local_interposer_to_global_vl"]]["interposer"]
    rows = interposer["rows"]
    cols = interposer["cols"]
    local_area = rows * cols
    if local_area <= 0:
        return INF
    base_attach_router %= local_area

    ax = int(base_attach_router % cols)
    ay = int(base_attach_router // cols)

    src_to_br = (abs(CHIP_COLS - 1 - lx) + abs(CHIP_ROWS - 1 - ly)) * INTRACHIP_LATENCY
    br_to_li = VL_LATENCY
    li_to_attach = (abs(att_x - ax) + abs(att_y - ay)) * INTERPOSER_LATENCY
    li_attach_to_base = VL_LATENCY

    return src_to_br + br_to_li + li_to_attach + li_attach_to_base


def _base_to_2p5d_cost(info):
    return _2p5d_to_base_cost(info)


def calculate_count(src_router, dest_router):
    src_info = locate_router(src_router)
    dest_info = locate_router(dest_router)

    src_type = src_info["type"]
    dest_type = dest_info["type"]

    if src_type == "2.5d" and dest_type == "2.5d":
        src_base = src_info["local_interposer_to_global_vl"]
        dest_base = dest_info["local_interposer_to_global_vl"]
        sx, sy = src_info["local_coords"]
        dx, dy = dest_info["local_coords"]

        if src_base == dest_base:
            if src_info["chiplet"] == dest_info["chiplet"]:
                return (abs(sx - dx) + abs(sy - dy)) * INTRACHIP_LATENCY

            src_to_br = (abs(CHIP_COLS - 1 - sx) + abs(CHIP_ROWS - 1 - sy)) * INTRACHIP_LATENCY
            dest_to_br = (abs(CHIP_COLS - 1 - dx) + abs(CHIP_ROWS - 1 - dy)) * INTRACHIP_LATENCY
            src_br_loc = src_info["chiplet_to_local_interposer_vl"]
            dest_br_loc = dest_info["chiplet_to_local_interposer_vl"]
            br_to_br = (
                abs(src_br_loc[0] - dest_br_loc[0]) +
                abs(src_br_loc[1] - dest_br_loc[1])
            ) * INTERPOSER_LATENCY
            return src_to_br + dest_to_br + br_to_br + 2 * VL_LATENCY

        cost_src_to_base = _2p5d_to_base_cost(src_info)
        cost_dest_from_base = _base_to_2p5d_cost(dest_info)
        base_to_base = (
            abs(src_base[0] - dest_base[0]) +
            abs(src_base[1] - dest_base[1])
        ) * INTERPOSER_LATENCY
        return cost_src_to_base + base_to_base + cost_dest_from_base

    if src_type == "3d" and dest_type == "3d":
        if src_info["chiplet"] == dest_info["chiplet"]:
            return _same_chiplet_3d_cost(src_router, dest_router)

        cost_src_to_base = _3d_to_base_cost(src_router, src_info)
        cost_dest_from_base = _base_to_3d_cost(dest_router, dest_info)
        src_base = src_info["base_attach_coord"]
        dest_base = dest_info["base_attach_coord"]
        base_to_base = (
            abs(src_base[0] - dest_base[0]) +
            abs(src_base[1] - dest_base[1])
        ) * INTERPOSER_LATENCY
        return cost_src_to_base + base_to_base + cost_dest_from_base

    if src_type == "3d" and dest_type == "2.5d":
        cost_src_to_base = _3d_to_base_cost(src_router, src_info)
        src_base = src_info["base_attach_coord"]
        dest_base = dest_info["local_interposer_to_global_vl"]
        base_walk = (
            abs(src_base[0] - dest_base[0]) +
            abs(src_base[1] - dest_base[1])
        ) * INTERPOSER_LATENCY
        cost_dest_from_base = _base_to_2p5d_cost(dest_info)
        return cost_src_to_base + base_walk + cost_dest_from_base

    if src_type == "2.5d" and dest_type == "3d":
        cost_src_to_base = _2p5d_to_base_cost(src_info)
        src_base = src_info["local_interposer_to_global_vl"]
        dest_base = dest_info["base_attach_coord"]
        base_walk = (
            abs(src_base[0] - dest_base[0]) +
            abs(src_base[1] - dest_base[1])
        ) * INTERPOSER_LATENCY
        cost_dest_from_base = _base_to_3d_cost(dest_router, dest_info)
        return cost_src_to_base + base_walk + cost_dest_from_base

    raise ValueError(f"Unsupported type combination: {src_type} -> {dest_type}")


# =========================
# Chromosome and TSV helpers
# =========================

def _validate_tsv_assignment_mode(mode):
    mode = int(mode)
    if mode not in (TSV_ASSIGNMENT_RANDOM, TSV_ASSIGNMENT_ELEVATOR_FIRST):
        raise ValueError(
            "TSV assignment mode must be 0 (random) or 1 (elevator_first)"
        )
    return mode


def _tsv_assignment_mode_name(mode=None):
    mode = TSV_ASSIGNMENT_MODE if mode is None else _validate_tsv_assignment_mode(mode)
    if mode == TSV_ASSIGNMENT_RANDOM:
        return "random"
    return "elevator_first"


def _nearest_tsv_local_index(router_local_idx, tsv_local_indices):
    rx = router_local_idx % CHIP_COLS
    ry = router_local_idx // CHIP_COLS
    return min(
        tsv_local_indices,
        key=lambda t: (
            abs(rx - (t % CHIP_COLS)) + abs(ry - (t // CHIP_COLS)),
            t,
        ),
    )


def _select_tsv_local_index(router_local_idx, candidate_local_indices):
    if not candidate_local_indices:
        raise ValueError("candidate_local_indices cannot be empty")
    if TSV_ASSIGNMENT_MODE == TSV_ASSIGNMENT_RANDOM:
        return random.choice(candidate_local_indices)
    if TSV_ASSIGNMENT_MODE == TSV_ASSIGNMENT_ELEVATOR_FIRST:
        return _nearest_tsv_local_index(router_local_idx, candidate_local_indices)
    raise ValueError(f"Unsupported TSV assignment mode: {TSV_ASSIGNMENT_MODE}")


def _build_initial_tsv_assignment(start_id, no_levels, routers_per_level, tsv_placement):
    assignment = []
    local_tsvs = [idx for idx, bit in enumerate(tsv_placement) if bit == 1]

    for layer in range(no_levels):
        layer_offset = start_id + layer * routers_per_level
        for router_local_idx in range(routers_per_level):
            if local_tsvs:
                chosen_local = _select_tsv_local_index(router_local_idx, local_tsvs)
                assignment.append(layer_offset + chosen_local)
            else:
                assignment.append(layer_offset)

    return assignment

def generate_particle_state_3p5d(chiplet_layout, tsv_list):
    total_routers = sum(chip["no_routers"] for chip in chiplet_layout)
    global_core_perm = random.sample(range(total_routers), total_routers)

    particle_state = []
    idx = 0

    for chip in chiplet_layout:
        no_routers = chip["no_routers"]
        core_to_router = global_core_perm[idx:idx + no_routers]
        idx += no_routers

        if chip["type"] == "3d":
            no_levels = chip["no_levels"]
            routers_per_level = no_routers // no_levels
            tsv_placement = [random.choice([0, 1]) for _ in range(routers_per_level)]
            tsv_assignment = _build_initial_tsv_assignment(
                chip["range"][0],
                no_levels,
                routers_per_level,
                tsv_placement,
            )
            base_attach_router = random.randrange(routers_per_level)
            particle_state.append([
                core_to_router,
                tsv_placement,
                tsv_assignment,
                base_attach_router,
            ])
        elif chip["type"] == "2.5d":
            local_rows = chip["interposer"]["rows"]
            local_cols = chip["interposer"]["cols"]
            local_area = local_rows * local_cols
            if local_area <= 0:
                raise ValueError(
                    f"Invalid local interposer size for {chip['name']}: {local_rows}x{local_cols}"
                )
            base_attach_router = random.randrange(local_area)
            particle_state.append([core_to_router, base_attach_router])
        else:
            raise ValueError(f"Unknown chiplet type: {chip['type']}")

    return particle_state


def _validate_tsv_placement_single_3d(tsv_placement, router_coordinates, base_offset, routers_per_level):
    initial_tsv_count = tsv_placement.count(1)
    max_tsvs = max(2, math.floor(0.25 * routers_per_level))
    target_tsv_count = min(max_tsvs, max(2, initial_tsv_count))

    def is_manhattan_distance_greater_than_1(i, j):
        router_i = base_offset + i
        router_j = base_offset + j
        x1, y1, z1 = router_coordinates[router_i]
        x2, y2, z2 = router_coordinates[router_j]
        if z1 != z2:
            return True
        return abs(x1 - x2) + abs(y1 - y2) > 1

    def find_valid_tsv_position(tp):
        available = [idx for idx, bit in enumerate(tp) if bit == 0]
        random.shuffle(available)
        for pos in available:
            if tp.count(1) >= max_tsvs:
                break
            ok = True
            for existing_idx, bit in enumerate(tp):
                if bit == 1 and not is_manhattan_distance_greater_than_1(pos, existing_idx):
                    ok = False
                    break
            if ok:
                return pos
        return None

    def is_valid_tsv_placement(tp):
        tsv_indices = [i for i, bit in enumerate(tp) if bit == 1]
        if len(tsv_indices) < 2 or len(tsv_indices) > max_tsvs:
            return False

        for a_idx, i in enumerate(tsv_indices):
            for j in tsv_indices[a_idx + 1:]:
                if not is_manhattan_distance_greater_than_1(i, j):
                    return False
        return True

    def rebuild_valid_tsv_placement():
        rebuilt = [0] * routers_per_level
        while rebuilt.count(1) < target_tsv_count:
            pos = find_valid_tsv_position(rebuilt)
            if pos is None:
                return None
            rebuilt[pos] = 1
        return rebuilt

    if tsv_placement.count(1) < 2:
        need = min(2 - tsv_placement.count(1), max_tsvs - tsv_placement.count(1))
        zeros = [i for i, bit in enumerate(tsv_placement) if bit == 0]
        for _ in range(need):
            if not zeros:
                break
            idx = random.choice(zeros)
            zeros.remove(idx)
            tsv_placement[idx] = 1

    tsv_indices = [i for i, bit in enumerate(tsv_placement) if bit == 1]
    if len(tsv_indices) == 2:
        i, j = tsv_indices
        if not is_manhattan_distance_greater_than_1(i, j):
            tsv_placement[j] = 0
            pos = find_valid_tsv_position(tsv_placement)
            if pos is not None:
                tsv_placement[pos] = 1
            else:
                tsv_placement[j] = 1
    else:
        conflicts = []
        for a_idx, i in enumerate(tsv_indices):
            for j in tsv_indices[a_idx + 1:]:
                if not is_manhattan_distance_greater_than_1(i, j):
                    conflicts.append((i, j))
        for i, j in conflicts:
            if tsv_placement.count(1) > 2:
                tsv_placement[random.choice([i, j])] = 0

    restored = 0
    attempts = 0
    max_attempts = routers_per_level
    while (
        tsv_placement.count(1) < max_tsvs
        and restored < (initial_tsv_count - tsv_placement.count(1))
        and attempts < max_attempts
    ):
        pos = find_valid_tsv_position(tsv_placement)
        if pos is not None:
            tsv_placement[pos] = 1
            restored += 1
        attempts += 1

    while tsv_placement.count(1) > max_tsvs:
        idxs = [i for i, bit in enumerate(tsv_placement) if bit == 1]
        if len(idxs) > 2:
            tsv_placement[random.choice(idxs)] = 0
        else:
            break

    if tsv_placement.count(1) < 2:
        zeros = [i for i, bit in enumerate(tsv_placement) if bit == 0]
        while tsv_placement.count(1) < 2 and zeros:
            pos = find_valid_tsv_position(tsv_placement)
            if pos is not None:
                tsv_placement[pos] = 1
            else:
                idx = random.choice(zeros)
                zeros.remove(idx)
                tsv_placement[idx] = 1

    if is_valid_tsv_placement(tsv_placement):
        return tsv_placement

    for _ in range(TSV_REBUILD_ATTEMPTS):
        rebuilt = rebuild_valid_tsv_placement()
        if rebuilt is not None and is_valid_tsv_placement(rebuilt):
            return rebuilt

    raise ValueError(
        "Unable to build a spacing-valid TSV placement after "
        f"{TSV_REBUILD_ATTEMPTS} rebuild attempts"
    )


def validate_tsv_placement_3p5d(particle_state, chiplet_layout, router_coordinates):
    offset = 0
    for idx, chip in enumerate(chiplet_layout):
        no_routers = chip["no_routers"]
        if chip["type"] == "3d":
            no_levels = chip["no_levels"]
            routers_per_level = no_routers // no_levels
            _, tsv_placement, _, _ = particle_state[idx]
            particle_state[idx][1] = _validate_tsv_placement_single_3d(
                tsv_placement,
                router_coordinates,
                base_offset=offset,
                routers_per_level=routers_per_level,
            )
        offset += no_routers
    return particle_state


def _count_vertical_communications_3d_chip(core_to_router, router_coordinates, edge_set_file, chip_range):
    start_id, end_id = chip_range
    vertical = 0

    with open(edge_set_file, "r", encoding="utf-8") as f:
        for line in f:
            vals = line.split()
            if len(vals) < 3:
                continue

            src_core = int(vals[0])
            dest_core = int(vals[1])

            if src_core not in core_to_router or dest_core not in core_to_router:
                continue

            src_router = start_id + core_to_router.index(src_core)
            dest_router = start_id + core_to_router.index(dest_core)

            if not (start_id <= src_router <= end_id and start_id <= dest_router <= end_id):
                continue

            if router_coordinates[src_router][2] != router_coordinates[dest_router][2]:
                vertical += 1

    return vertical


def _validate_tsv_assignment_single_3d(tsv_placement, no_routers, no_levels,
                                       core_to_router, router_coordinates,
                                       edge_set_file, base_offset, routers_per_level):
    tsv_assignment = [0] * no_routers
    vertical_comms = _count_vertical_communications_3d_chip(
        core_to_router,
        router_coordinates,
        edge_set_file,
        (base_offset, base_offset + no_routers - 1),
    )

    for layer in range(no_levels):
        layer_offset = base_offset + layer * routers_per_level
        tsv_list = [layer_offset + i for i, bit in enumerate(tsv_placement) if bit == 1]

        if tsv_list:
            max_assign = max(1, vertical_comms // len(tsv_list)) + 1
            tsv_count = {tsv_router: 0 for tsv_router in tsv_list}
            for router in range(layer_offset, layer_offset + routers_per_level):
                available = [t for t, count in tsv_count.items() if count < max_assign]
                candidate_tsvs = available if available else tsv_list
                candidate_local_indices = [tsv - layer_offset for tsv in candidate_tsvs]
                chosen = layer_offset + _select_tsv_local_index(
                    router - layer_offset,
                    candidate_local_indices,
                )
                local_idx = router - base_offset
                tsv_assignment[local_idx] = chosen
                tsv_count[chosen] += 1
        else:
            for router in range(layer_offset, layer_offset + routers_per_level):
                local_idx = router - base_offset
                tsv_assignment[local_idx] = layer_offset

    return tsv_assignment


def validate_tsv_assignment_3p5d(particle_state, chiplet_layout, router_coordinates, edge_set_file):
    offset = 0
    for idx, chip in enumerate(chiplet_layout):
        no_routers = chip["no_routers"]
        if chip["type"] == "3d":
            no_levels = chip["no_levels"]
            routers_per_level = no_routers // no_levels
            core_to_router, tsv_placement, _, _ = particle_state[idx]
            particle_state[idx][2] = _validate_tsv_assignment_single_3d(
                tsv_placement,
                no_routers,
                no_levels,
                core_to_router,
                router_coordinates,
                edge_set_file,
                base_offset=offset,
                routers_per_level=routers_per_level,
            )
        offset += no_routers
    return particle_state


def fix_core_to_router_mapping_3p5d(particle_state, chiplet_layout):
    total_routers = sum(chip["no_routers"] for chip in chiplet_layout)
    flat = []
    for chip_idx, _ in enumerate(chiplet_layout):
        flat.extend(particle_state[chip_idx][0])

    missing = list(set(range(total_routers)) - set(flat))
    repeated_indices = []
    seen = {}

    for idx, val in enumerate(flat):
        if val in seen:
            repeated_indices.append(idx)
        else:
            seen[val] = idx

    random.shuffle(repeated_indices)
    for replace_idx, missing_val in zip(repeated_indices, missing):
        flat[replace_idx] = missing_val

    idx = 0
    for chip_idx, chip in enumerate(chiplet_layout):
        no_routers = chip["no_routers"]
        particle_state[chip_idx][0] = flat[idx:idx + no_routers]
        idx += no_routers

    return particle_state


def assign_router_coordinates(total_routers):
    """Build router_coordinates[router_id] = (x, y, z)."""
    coords = {}
    for meta in base_icrt.values():
        start_id, end_id = meta["range"]
        if meta["type"] == "3d":
            levels = (end_id - start_id + 1) // (CHIP_ROWS * CHIP_COLS)
            for router_id in range(start_id, end_id + 1):
                coords[router_id] = _local_coords_3d(router_id, start_id, levels)
        else:
            for router_id in range(start_id, end_id + 1):
                x, y = _local_coords_2d(router_id, start_id)
                coords[router_id] = (x, y, 0)

    if len(coords) != total_routers:
        raise RuntimeError("Router coordinate map incomplete")
    return coords


def build_core_to_router_map(particle_state, chiplet_layout):
    mapping = {}
    offset = 0
    for idx, chip in enumerate(chiplet_layout):
        for local_router, core in enumerate(particle_state[idx][0]):
            mapping[core] = offset + local_router
        offset += chip["no_routers"]
    return mapping


def build_global_tsv_assignment(particle_state, chiplet_layout):
    assignment = {}
    offset = 0
    for idx, chip in enumerate(chiplet_layout):
        if chip["type"] == "3d":
            _, _, local_tsv_assignment, _ = particle_state[idx]
            for local_router, tsv_router in enumerate(local_tsv_assignment):
                assignment[offset + local_router] = tsv_router
        offset += chip["no_routers"]
    return assignment


def tsv_variance_3p5d(particle_state, chiplet_layout, router_coordinates, edge_set_file):
    core_to_router_map = build_core_to_router_map(particle_state, chiplet_layout)
    global_tsv_assignment = build_global_tsv_assignment(particle_state, chiplet_layout)

    router_to_chip = {}
    for chip_idx, chip in enumerate(chiplet_layout):
        if chip["type"] == "3d":
            start_id, end_id = chip["range"]
            for router_id in range(start_id, end_id + 1):
                router_to_chip[router_id] = chip_idx

    tsv_traffic = {}
    for chip_idx, chip in enumerate(chiplet_layout):
        if chip["type"] != "3d":
            continue

        no_routers = chip["no_routers"]
        no_levels = chip["no_levels"]
        start_id, _ = chip["range"]
        routers_per_level = no_routers // no_levels
        tsv_placement = particle_state[chip_idx][1]

        for layer in range(no_levels - 1):
            base_offset = start_id + layer * routers_per_level
            for pos, bit in enumerate(tsv_placement):
                if bit == 1:
                    lower = base_offset + pos
                    upper = lower + routers_per_level
                    tsv_traffic[(lower, upper)] = 0.0
                    tsv_traffic[(upper, lower)] = 0.0

    coord_to_router = {coords: router_id for router_id, coords in router_coordinates.items()}

    with open(edge_set_file, "r", encoding="utf-8") as f:
        for line in f:
            vals = line.split()
            if len(vals) < 3:
                continue

            src_core = int(vals[0])
            dest_core = int(vals[1])
            bw = float(vals[2])

            if src_core not in core_to_router_map or dest_core not in core_to_router_map:
                continue

            src_router = core_to_router_map[src_core]
            dest_router = core_to_router_map[dest_core]

            if src_router not in router_to_chip or dest_router not in router_to_chip:
                continue
            chip_idx = router_to_chip[src_router]
            if router_to_chip[dest_router] != chip_idx:
                continue

            src_coords = router_coordinates[src_router]
            dest_coords = router_coordinates[dest_router]
            if src_coords[2] == dest_coords[2]:
                continue

            current_router = src_router
            while True:
                curr_coords = router_coordinates[current_router]
                if curr_coords[2] == dest_coords[2]:
                    break

                direction = 1 if dest_coords[2] > curr_coords[2] else -1
                tsv_router = global_tsv_assignment.get(current_router, current_router)
                tsv_coords = router_coordinates[tsv_router]

                neighbor_z = tsv_coords[2] + direction
                neighbor_coords = (tsv_coords[0], tsv_coords[1], neighbor_z)
                neighbor_router = coord_to_router.get(neighbor_coords)
                if neighbor_router is None:
                    break

                pair = (tsv_router, neighbor_router)
                if pair in tsv_traffic:
                    tsv_traffic[pair] += bw

                current_router = neighbor_router

    def variance(values):
        if not values:
            return 0.0
        mean = sum(values) / len(values)
        return sum((value - mean) ** 2 for value in values) / len(values)

    up_values = []
    down_values = []
    for (router_a, router_b), traffic in tsv_traffic.items():
        if router_coordinates[router_a][2] < router_coordinates[router_b][2]:
            up_values.append(traffic)
        else:
            down_values.append(traffic)

    return variance(up_values), variance(down_values)


def cost_function_3p5d(particle_state, chiplet_layout, edge_set_file):
    global tsv_assignment_global, current_particle_state

    current_particle_state = particle_state
    tsv_assignment_global = build_global_tsv_assignment(particle_state, chiplet_layout)
    core_to_router_map = build_core_to_router_map(particle_state, chiplet_layout)

    total_cost = 0.0
    with open(edge_set_file, "r", encoding="utf-8") as f:
        for line in f:
            vals = line.split()
            if len(vals) < 3:
                continue

            src_core = int(vals[0])
            dest_core = int(vals[1])
            bw = float(vals[2])

            if src_core not in core_to_router_map or dest_core not in core_to_router_map:
                continue

            src_router = core_to_router_map[src_core]
            dest_router = core_to_router_map[dest_core]
            total_cost += calculate_count(src_router, dest_router) * bw

    return total_cost


def init_normalization_terms(graph_name, edge_set_file, threeD_height):
    global MAX_COMM_COST, VAR_COMM_SQ

    input_graph = graph_input_path(graph_name)
    with open(input_graph, "r", encoding="utf-8") as f:
        no_of_cores = int(f.readline().strip())

    max_bw = 0.0
    total_bw = 0.0
    with open(edge_set_file, "r", encoding="utf-8") as f:
        for line in f:
            vals = line.split()
            if len(vals) < 3:
                continue
            bw = float(vals[2])
            max_bw = max(max_bw, bw)
            total_bw += bw

    if max_bw <= 0.0:
        max_bw = 1.0
    if total_bw <= 0.0:
        total_bw = 1.0

    base_hops = 0
    if BASE_INTERPOSER_ENABLED and BASE_ROWS > 0 and BASE_COLS > 0:
        base_hops = BASE_ROWS - 1 + BASE_COLS - 1

    max_hops = (
        (CHIP_ROWS - 1 + CHIP_COLS - 1) * threeD_height
        + (threeD_height - 1)
        + base_hops
    )
    if max_hops <= 0:
        max_hops = 1

    MAX_COMM_COST = max_bw * max_hops * no_of_cores
    VAR_COMM_SQ = total_bw * total_bw


def graph_input_path(graph_name):
    raw = str(graph_name)
    candidates = []
    if os.path.isfile(raw):
        return raw
    candidates.append(raw)
    if not raw.lower().endswith(".txt"):
        candidates.append(f"{raw}.txt")
    base = os.path.basename(raw)
    candidates.append(os.path.join("Graphs", base))
    if not base.lower().endswith(".txt"):
        candidates.append(os.path.join("Graphs", f"{base}.txt"))
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    return os.path.join("Graphs", f"{base}.txt" if not base.lower().endswith(".txt") else base)


def edge_set_output_path(graph_name):
    base = os.path.splitext(os.path.basename(str(graph_name)))[0]
    os.makedirs("EdgeSet", exist_ok=True)
    return os.path.join("EdgeSet", f"edge_set_{base}.txt")


def fitness_terms_3p5d(particle_state, chiplet_layout, router_coordinates, edge_set_file):
    cost = cost_function_3p5d(particle_state, chiplet_layout, edge_set_file)
    var_up, var_down = tsv_variance_3p5d(particle_state, chiplet_layout, router_coordinates, edge_set_file)
    variance = max(var_up, var_down)

    norm_cost = (W_FACTOR * cost) / MAX_COMM_COST if MAX_COMM_COST > 0.0 else cost
    norm_var = ((1.0 - W_FACTOR) * variance) / VAR_COMM_SQ if VAR_COMM_SQ > 0.0 else variance

    effective_fitness = norm_cost + norm_var
    return effective_fitness, cost, variance, var_up, var_down


# =========================
# Discrete PSO helpers
# =========================

def find_swap_sequence(list1, list2):
    """
    Compute the swap sequence needed to turn list1 into list2.
    Both lists are expected to contain the same set of values.
    """
    if len(list1) != len(list2):
        return []

    current = list1.copy()
    swap_sequence = []

    for i in range(len(list2)):
        if current[i] == list2[i]:
            continue

        target_val = list2[i]
        try:
            j = current.index(target_val, i + 1)
        except ValueError:
            continue

        current[i], current[j] = current[j], current[i]
        swap_sequence.append((i, j))

    return swap_sequence


def find_swap_sequence_for_placement(list1, list2):
    """
    Swap sequence for TSV placement bitmaps.
    The count of 1s is aligned first, then mismatches are paired as swaps.
    """
    if len(list1) != len(list2):
        return []

    work1 = list1.copy()
    work2 = list2.copy()

    count1 = sum(work1)
    count2 = sum(work2)

    if count1 != count2:
        if count1 < count2:
            diff = count2 - count1
            non_tsv = [i for i, v in enumerate(work1) if v == 0]
            for idx in random.sample(non_tsv, min(diff, len(non_tsv))):
                work1[idx] = 1
        else:
            diff = count1 - count2
            tsv_idx = [i for i, v in enumerate(work1) if v == 1]
            for idx in random.sample(tsv_idx, min(diff, len(tsv_idx))):
                work1[idx] = 0

    ones_to_zero = []
    zeros_to_one = []

    for i in range(len(work1)):
        if work1[i] == 1 and work2[i] == 0:
            ones_to_zero.append(i)
        elif work1[i] == 0 and work2[i] == 1:
            zeros_to_one.append(i)

    swap_sequence = []
    for k in range(min(len(ones_to_zero), len(zeros_to_one))):
        swap_sequence.append((ones_to_zero[k], zeros_to_one[k]))

    return swap_sequence


def apply_swap_velocity(current_list, velocity, local_swap_seq, global_swap_seq):
    """
    Standard discrete PSO update:
      1. inertia via old velocity,
      2. cognitive pull to local best,
      3. social pull to global best.
    """
    new_velocity = []

    for i, j in velocity:
        if random.random() < INERTIA_PROB:
            current_list[i], current_list[j] = current_list[j], current_list[i]
            new_velocity.append((i, j))

    for i, j in local_swap_seq:
        if random.random() < COGNITIVE_PROB:
            current_list[i], current_list[j] = current_list[j], current_list[i]
            new_velocity.append((i, j))

    for i, j in global_swap_seq:
        if random.random() < SOCIAL_PROB:
            current_list[i], current_list[j] = current_list[j], current_list[i]
            new_velocity.append((i, j))

    return new_velocity


def flatten_particle_mapping(particle_state):
    flat = []
    for chip_state in particle_state:
        flat.extend(chip_state[0])
    return flat


def restore_particle_mapping(particle_state, chiplet_layout, flat_mapping):
    idx = 0
    for chip_idx, chip in enumerate(chiplet_layout):
        no_routers = chip["no_routers"]
        particle_state[chip_idx][0] = flat_mapping[idx:idx + no_routers]
        idx += no_routers


def attach_index_for_chip(chip):
    return 3 if chip["type"] == "3d" else 1


def attach_limit_for_chip(chip):
    if chip["type"] == "3d":
        return chip["no_routers"] // chip["no_levels"]
    return chip["interposer"]["rows"] * chip["interposer"]["cols"]


def repair_particle_state(particle_state, chiplet_layout, router_coordinates, edge_set_file):
    particle_state = fix_core_to_router_mapping_3p5d(particle_state, chiplet_layout)
    particle_state = validate_tsv_placement_3p5d(particle_state, chiplet_layout, router_coordinates)
    particle_state = validate_tsv_assignment_3p5d(
        particle_state,
        chiplet_layout,
        router_coordinates,
        edge_set_file,
    )
    return particle_state


def evaluate_particle_state(particle_state, chiplet_layout, router_coordinates, edge_set_file):
    return fitness_terms_3p5d(
        particle_state,
        chiplet_layout,
        router_coordinates,
        edge_set_file,
    )


def update_attach_router(particle_state, chiplet_layout, local_best, global_best):
    for chip_idx, chip in enumerate(chiplet_layout):
        idx = attach_index_for_chip(chip)
        limit = attach_limit_for_chip(chip)

        if limit <= 0:
            continue

        if random.random() < COGNITIVE_PROB:
            particle_state[chip_idx][idx] = local_best.state[chip_idx][idx]

        if global_best is not None and random.random() < SOCIAL_PROB:
            particle_state[chip_idx][idx] = global_best.state[chip_idx][idx]
        particle_state[chip_idx][idx] %= limit


class Particle3p5d:
    def __init__(self, chiplet_layout, router_coordinates, edge_set_file, tsv_list):
        self.state = generate_particle_state_3p5d(chiplet_layout, tsv_list)
        self.state = repair_particle_state(
            self.state,
            chiplet_layout,
            router_coordinates,
            edge_set_file,
        )

        self.mapping_velocity = []
        self.tsv_velocity = {}

        self.fitness_value = float("inf")
        self.cost = float("inf")
        self.variance = 0.0
        self.var_up = 0.0
        self.var_down = 0.0

        self.evaluate(chiplet_layout, router_coordinates, edge_set_file)

    def evaluate(self, chiplet_layout, router_coordinates, edge_set_file):
        fit, cost, variance, var_up, var_down = evaluate_particle_state(
            self.state,
            chiplet_layout,
            router_coordinates,
            edge_set_file,
        )
        self.fitness_value = fit
        self.cost = cost
        self.variance = variance
        self.var_up = var_up
        self.var_down = var_down

    def clone(self):
        return copy.deepcopy(self)


def update_particle(particle,
                    local_best,
                    global_best,
                    chiplet_layout,
                    router_coordinates,
                    edge_set_file):
    particle_state = copy.deepcopy(particle.state)

    flat_mapping = flatten_particle_mapping(particle_state)
    local_mapping = flatten_particle_mapping(local_best.state)
    global_mapping = flatten_particle_mapping(global_best.state) if global_best is not None else flat_mapping

    seq_cognitive = find_swap_sequence(flat_mapping, local_mapping)
    seq_social = find_swap_sequence(flat_mapping, global_mapping)
    particle.mapping_velocity = apply_swap_velocity(
        flat_mapping,
        particle.mapping_velocity,
        seq_cognitive,
        seq_social,
    )

    restore_particle_mapping(particle_state, chiplet_layout, flat_mapping)

    for chip_idx, chip in enumerate(chiplet_layout):
        if chip["type"] != "3d":
            continue

        current_tsv = particle_state[chip_idx][1]
        local_tsv = local_best.state[chip_idx][1]
        global_tsv = global_best.state[chip_idx][1] if global_best is not None else current_tsv

        seq_cognitive_tsv = find_swap_sequence_for_placement(current_tsv, local_tsv)
        seq_social_tsv = find_swap_sequence_for_placement(current_tsv, global_tsv)

        velocity = particle.tsv_velocity.get(chip_idx, [])
        particle.tsv_velocity[chip_idx] = apply_swap_velocity(
            current_tsv,
            velocity,
            seq_cognitive_tsv,
            seq_social_tsv,
        )

    update_attach_router(particle_state, chiplet_layout, local_best, global_best)

    particle.state = repair_particle_state(
        particle_state,
        chiplet_layout,
        router_coordinates,
        edge_set_file,
    )


def particle_output_path(graph_name):
    match = re.search(r"(\d+)$", graph_name)
    if match and graph_name.lower().startswith("graph"):
        return os.path.join("Particles", f"PSO_Particle{match.group(1)}.txt")
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", graph_name.strip()) or "graph"
    return os.path.join("Particles", f"PSO_Particle_{safe}.txt")


def _coord_convention(rows, cols):
    return {
        "origin": "top_left",
        "indexing": "0_based",
        "axis_direction": {
            "x": "left_to_right",
            "y": "top_to_bottom",
        },
        "order": "row_major",
        "router_index_formula": "router_index = y * cols + x",
        "inverse_formula": {
            "x": "router_index % cols",
            "y": "router_index // cols",
        },
        "grid_shape": {
            "rows": int(rows),
            "cols": int(cols),
        },
        "top_left_coord": [0, 0],
        "bottom_right_coord": [int(cols) - 1, int(rows) - 1],
    }


def _serialize_local_interposer(interposer):
    if not isinstance(interposer, dict):
        return None

    out = {
        "rows": int(interposer.get("rows", 0)),
        "cols": int(interposer.get("cols", 0)),
        "chiplets": {},
    }

    chiplets = interposer.get("chiplets")
    if isinstance(chiplets, dict):
        for name, spec in chiplets.items():
            if not isinstance(spec, dict):
                continue
            attach = spec.get("attach_coord", (0, 0))
            r0, r1 = spec.get("range", (0, -1))
            out["chiplets"][str(name)] = {
                "attach_coord": [int(attach[0]), int(attach[1])],
                "range": [int(r0), int(r1)],
            }

    return out


def _build_simple_particle_entry(chip, chip_state):
    entry = {
        "type": chip["type"],
        "name": chip["name"],
        "vl_coord": list(chip["vl_coord"]),
        "range": list(chip["range"]),
        "no_routers": int(chip["no_routers"]),
    }

    if chip["type"] == "3d":
        core_to_router, tsv_place, tsv_assign, base_attach = chip_state
        entry.update({
            "no_levels": int(chip["no_levels"]),
            "base_attach_router": int(base_attach),
            "core_to_router": [int(v) for v in core_to_router],
            "tsv_placement": [int(v) for v in tsv_place],
            "tsv_assignment": [int(v) for v in tsv_assign],
        })
    else:
        core_to_router, base_attach = chip_state
        entry.update({
            "base_attach_router": int(base_attach),
            "core_to_router": [int(v) for v in core_to_router],
        })
        interposer = _serialize_local_interposer(chip.get("interposer"))
        if interposer is not None:
            entry["interposer"] = interposer

    return entry


def write_particle_file(path,
                        graph_name,
                        chip_rows, chip_cols,
                        two5d_width, threeD_height,
                        num_2p5d_units, num_3d_units,
                        best_particle_state,
                        chiplet_layout,
                        best_cost,
                        final_eff_fit,
                        final_var,
                        final_var_up,
                        final_var_down):
    out_dir = os.path.dirname(path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    data = {
        "graph": graph_name,
        "seed": RANDOM_SEED,
        "best_cost": best_cost,
        "effective_fitness": final_eff_fit,
        "variance": final_var,
        "variance_up": final_var_up,
        "variance_down": final_var_down,
        "params": {
            "chip_rows": chip_rows,
            "chip_cols": chip_cols,
            "two5d_width": two5d_width,
            "threeD_height": threeD_height,
            "num_2p5d_units": num_2p5d_units,
            "num_3d_units": num_3d_units,
            "tsv_assignment_mode": int(TSV_ASSIGNMENT_MODE),
            "tsv_assignment_mode_name": _tsv_assignment_mode_name(),
        },
        "topology_hints": {
            "interposer_gap": MIN_INTERPOSER_GAP,
            "chiplet_order": "all_3d_then_all_2p5d",
            "base_interposer_enabled": BASE_INTERPOSER_ENABLED,
            "base_shape": "square" if BASE_INTERPOSER_ENABLED else "none",
            "local_2p5d_shape": "square" if num_2p5d_units > 0 else "none",
        },
        "chromosome_structure": {
            "3d_gene": [
                "core_to_router",
                "tsv_placement",
                "tsv_assignment",
                "base_attach_router",
            ],
            "2p5d_gene": [
                "core_to_router",
                "base_attach_router",
            ],
        },
        "chromosome": best_particle_state,
        "coordinate_conventions": {
            "router_indexing_inside_each_2d_chiplet": _coord_convention(chip_rows, chip_cols),
            "vl_router_coordinates_note": (
                "VL-related router coordinates use 0-based row-major indexing: "
                "(0,0) is top-left and (cols-1, rows-1) is bottom-right."
            ),
        },
        "chiplets": [],
    }

    if BASE_INTERPOSER_ENABLED and BASE_ROWS > 0 and BASE_COLS > 0:
        data["base"] = {"rows": BASE_ROWS, "cols": BASE_COLS}

    for idx, chip in enumerate(chiplet_layout):
        data["chiplets"].append(_build_simple_particle_entry(chip, best_particle_state[idx]))

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


# =========================
# PSO main loop
# =========================

def run_pso_3p5d(graph_name,
                 chip_rows, chip_cols,
                 two5d_width, threeD_height,
                 num_2p5d_units, num_3d_units,
                 iterations, swarm_size,
                 tsv_assignment_mode=TSV_ASSIGNMENT_RANDOM,
                 seed=None):
    if swarm_size <= 0:
        raise ValueError("swarm_size must be positive")

    if create_edge_set is None:
        raise RuntimeError("edge_set_creation_new.create_edge_set not available")

    global RANDOM_SEED, TSV_ASSIGNMENT_MODE
    RANDOM_SEED = int(time.time()) if seed is None else int(seed)
    TSV_ASSIGNMENT_MODE = _validate_tsv_assignment_mode(tsv_assignment_mode)
    random.seed(RANDOM_SEED)
    print(f"Using random seed: {RANDOM_SEED}")
    print(f"Using TSV assignment mode: {_tsv_assignment_mode_name()}")

    start_time = time.time()

    chiplet_layout, total_routers = build_topology(
        chip_rows,
        chip_cols,
        two5d_width,
        threeD_height,
        num_2p5d_units,
        num_3d_units,
    )

    input_graph = graph_input_path(graph_name)
    edge_set_file = edge_set_output_path(graph_name)
    create_edge_set(input_graph, edge_set_file)

    router_coordinates = assign_router_coordinates(total_routers)
    init_normalization_terms(graph_name, edge_set_file, threeD_height)

    tsv_list = list(range(total_routers))
    particles = [
        Particle3p5d(chiplet_layout, router_coordinates, edge_set_file, tsv_list)
        for _ in range(swarm_size)
    ]
    local_best = [particle.clone() for particle in particles]

    global_best = min(local_best, key=lambda p: p.fitness_value).clone()
    best_fitness_snapshot = global_best.fitness_value
    stall_count = 0

    for iteration in range(iterations):
        for idx, particle in enumerate(particles):
            particle.evaluate(chiplet_layout, router_coordinates, edge_set_file)

            if particle.fitness_value < local_best[idx].fitness_value:
                local_best[idx] = particle.clone()

            if particle.fitness_value < global_best.fitness_value:
                global_best = particle.clone()

        if global_best.fitness_value < best_fitness_snapshot:
            best_fitness_snapshot = global_best.fitness_value
            stall_count = 0
        else:
            stall_count += 1

        print(
            f"Iteration {iteration + 1}: "
            f"HopCost = {global_best.cost:.6f} | "
            f"Variance = {global_best.variance:.6f} "
            f"(up {global_best.var_up:.6f}, down {global_best.var_down:.6f}) | "
            f"EffectiveFitness = {global_best.fitness_value:.6f}"
        )

        if stall_count >= CONVERGENCE_STALL_LIMIT:
            print(
                f"Early stopping at iteration {iteration + 1} after "
                f"{CONVERGENCE_STALL_LIMIT} stagnant iterations without improvement."
            )
            break

        for idx, particle in enumerate(particles):
            update_particle(
                particle,
                local_best=local_best[idx],
                global_best=global_best,
                chiplet_layout=chiplet_layout,
                router_coordinates=router_coordinates,
                edge_set_file=edge_set_file,
            )

    for idx, particle in enumerate(particles):
        particle.evaluate(chiplet_layout, router_coordinates, edge_set_file)
        if particle.fitness_value < local_best[idx].fitness_value:
            local_best[idx] = particle.clone()
        if particle.fitness_value < global_best.fitness_value:
            global_best = particle.clone()

    end_time = time.time()

    print("\n=== 3.5D PSO Result ===")
    print(f"Graph:         {graph_name}")
    print(f"Total routers: {total_routers}")
    print(f"Best cost:     {global_best.cost:.6f}")
    print(f"Effective fitness: {global_best.fitness_value:.6f}")
    print(
        f"Variance:      {global_best.variance:.6f} "
        f"(up {global_best.var_up:.6f}, down {global_best.var_down:.6f})"
    )
    print(f"Real time:     {end_time - start_time:.2f} s")

    print("\nBest Particle State (by chiplet):")
    for idx, chip in enumerate(chiplet_layout):
        chip_state = global_best.state[idx]
        if chip["type"] == "3d":
            core_to_router, tsv_place, tsv_assign, base_attach = chip_state
            print(f"  {chip['name']} (3D): VL={chip['vl_coord']}, range={chip['range']}")
            print(f"    Core->Router: {core_to_router}")
            print(f"    TSV place:    {tsv_place}")
            print(f"    TSV assign:   {tsv_assign}")
            print(f"    Base attach router (bottom layer): {base_attach}")
        else:
            core_to_router, base_attach = chip_state
            print(f"  {chip['name']} (2.5D): VL={chip['vl_coord']}, range={chip['range']}")
            print(f"    Core->Router: {core_to_router}")
            print(f"    Base attach router (local interposer): {base_attach}")

    particle_path = particle_output_path(graph_name)
    write_particle_file(
        particle_path,
        graph_name,
        chip_rows,
        chip_cols,
        two5d_width,
        threeD_height,
        num_2p5d_units,
        num_3d_units,
        global_best.state,
        chiplet_layout,
        global_best.cost,
        global_best.fitness_value,
        global_best.variance,
        global_best.var_up,
        global_best.var_down,
    )

    return global_best.state, global_best.cost


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("graph_name")
    parser.add_argument("chip_rows", type=int)
    parser.add_argument("chip_cols", type=int)
    parser.add_argument("two5d_width", type=int)
    parser.add_argument("threeD_height", type=int)
    parser.add_argument("num_2p5d_units", type=int)
    parser.add_argument("num_3d_units", type=int)
    parser.add_argument("iterations", type=int)
    parser.add_argument("swarm_size", type=int)
    parser.add_argument(
        "tsv_assignment_mode",
        type=int,
        choices=[0, 1],
        help="TSV assignment mode: 0=random, 1=elevator_first",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for PSO. Omit to use the current system time.",
    )
    args = parser.parse_args()

    run_pso_3p5d(
        args.graph_name,
        args.chip_rows,
        args.chip_cols,
        args.two5d_width,
        args.threeD_height,
        args.num_2p5d_units,
        args.num_3d_units,
        args.iterations,
        args.swarm_size,
        args.tsv_assignment_mode,
        seed=args.seed,
    )


if __name__ == "__main__":
    main()
