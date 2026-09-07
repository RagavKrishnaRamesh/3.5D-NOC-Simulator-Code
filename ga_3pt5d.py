"""
GA-based 3.5D NoC / Multi-Chiplet Topology Optimizer

This script implements a genetic algorithm for a heterogeneous 3.5D system
consisting of:
  - 3D chiplets: vertical stacks of identical 2D mesh layers.
  - 2.5D complexes: 2D chiplets packed on square local interposers.
All chiplets connect to a common base interposer via vertical links (VLs).

Core preserved ideas from your code:
  - Chromosome structure (3.5D):
        chromosome = [
            [core_to_router_3d, tsv_placement_3d, tsv_assignment_3d],   # for each 3D chiplet
            [core_to_router_25d],                                      # for each 2.5D complex
            ...
        ]

    * core_to_router_* is a local slice of a GLOBAL permutation of [0..total_routers-1].
    * For 3D chiplets:
        - tsv_placement: 1D list over routers_per_level (bits: TSV present).
        - tsv_assignment: list (len = no_routers) mapping router -> TSV-router.
    * For 2.5D chiplets:
        - only core_to_router list.

  - Global constraint:
        All core_to_router entries across all chiplets collectively form a permutation
        of [0 .. total_routers-1].

  - Routing / latency:
        calculate_count() uses:
          - locate_router()
          - 3D helpers: _same_chiplet_3d_cost, _3d_to_base_cost, ...
          - 2.5D helpers: _2p5d_to_base_cost, ...
        with VL / interposer / intrachip latencies exactly as in your logic.

  - GA operators:
        - generate_chromosome_3p5d
        - fix_core_to_router_mapping_3p5d
        - validate_tsv_placement_3p5d
        - validate_tsv_assignment_3p5d
        - crossover_3p5d
        - mutate_chromosome_3p5d

  - Fitness:
        TOTAL communication cost = sum_over_edges( bandwidth * calculate_count(...) )
        No variance term.

Inputs (runtime arguments):
  - GraphNameWithoutExt:
        Adjacency matrix file "<GraphName>.txt" (your usual format).
        We call create_edge_set(GraphName.txt, edge_set_GraphName.txt).
  - chip_rows, chip_cols:
        Dimensions of a single 2D chiplet tile.
  - two5d_width:
        Number of horizontally stacked 2D chiplets per 2.5D complex.
  - threeD_height:
        Number of vertically stacked 2D layers per 3D chiplet.
  - num_2p5d_units:
        Number of 2.5D complexes.
  - num_3d_units:
        Number of 3D chiplets.
  - iterations:
        GA iterations.
  - population_size:
        GA population size.
"""

import argparse
import sys
import math
import random
import time
import json
import re
import os
# import resource
from copy import deepcopy

# If you already have this from your 3D flow, it will be used to create edge sets.
try:
    from edge_set_creation import create_edge_set
except ImportError:
    create_edge_set = None


# =========================
# Tunable GA / latency parameters
# =========================

INTRACHIP_LATENCY = 1.0       # per-hop inside chiplet
INTERPOSER_LATENCY = 1.0      # per-hop on (local/global) interposers
VL_LATENCY = 1.0              # vertical link latency

ELITE_PERCENTAGE = 0.2
SELECTION_PERCENTAGE = 0.2
MUTATION_STAGNATION = 20      # iterations of no improvement before applying mutations
RANDOM_SEED = None            # will be set from system time at runtime
EARLY_STOP_PATIENCE = 100     # iterations of no improvement before stopping early

# Enforce a minimum empty spacing between any two chiplet stacks on the base interposer.
MIN_INTERPOSER_GAP = 1        # measured in base-interposer grid units

# These are set dynamically in build_topology()
CHIP_ROWS = None
CHIP_COLS = None
BASE_ROWS = None
BASE_COLS = None
BASE_INTERPOSER_ENABLED = True
W_FACTOR=0.5

base_icrt = {}                # (x,y) -> {"type", "chiplet", "range", ...}
INF = float("inf")
TSV_ASSIGNMENT_RANDOM = 0
TSV_ASSIGNMENT_ELEVATOR_FIRST = 1
TSV_ASSIGNMENT_REDELF = TSV_ASSIGNMENT_ELEVATOR_FIRST
TSV_ASSIGNMENT_MODE = TSV_ASSIGNMENT_RANDOM

# Global TSV assignment (built per chromosome before cost eval)
tsv_assignment_global = {}
current_chromosome = None
NUM_3D_CHIPLETS = 0


# =========================
# Base interposer / topology construction
# =========================

def add_base_vl(x, y, t, start_id, end_id, chiplet_name, interposer=None,
                enforce_bounds=True, enforce_gap=True):
    """Register a vertical link stack on the base interposer."""
    if enforce_bounds and not (0 <= x < BASE_COLS and 0 <= y < BASE_ROWS):
        raise ValueError(f"VL ({x},{y}) out of bounds for {BASE_COLS}x{BASE_ROWS}")
    if (x, y) in base_icrt:
        raise ValueError(f"Duplicate VL at ({x},{y})")
    if enforce_gap:
        for (bx, by) in base_icrt.keys():
            if max(abs(x - bx), abs(y - by)) <= MIN_INTERPOSER_GAP:
                raise ValueError(
                    f"VL ({x},{y}) too close to existing stack at ({bx},{by}); "
                    f"need at least {MIN_INTERPOSER_GAP} empty base slot(s) of spacing"
                )

    # Ensure non-overlapping ID ranges
    for meta in base_icrt.values():
        s, e = meta["range"]
        if not (end_id < s or start_id > e):
            raise ValueError(f"ID range {start_id}-{end_id} overlaps with existing {s}-{e}")

    entry = {
        "type": t,          # "3d" or "2.5d"
        "chiplet": chiplet_name,
        "range": (start_id, end_id),
    }
    if t == "2.5d" and interposer is not None:
        entry["interposer"] = interposer

    base_icrt[(x, y)] = entry


def build_2p5d_interposer(rows, cols, chiplet_specs):
    """
    Build local interposer description for one 2.5D complex.

    chiplet_specs: list of (name, (attach_x, attach_y), (start_id, end_id))
        attach_(x,y): local interposer coords of that chiplet's BR router.
    """
    chiplets = {}
    used_ranges = []

    for name, (ax, ay), (s, e) in chiplet_specs:
        if not (0 <= ax < cols and 0 <= ay < rows):
            raise ValueError(f"{name} attach ({ax},{ay}) out of bounds for {cols}x{rows}")
        for (ps, pe) in used_ranges:
            if not (e < ps or s > pe):
                raise ValueError(f"{name} range {s}-{e} overlaps with {ps}-{pe}")
        used_ranges.append((s, e))
        chiplets[name] = {"attach_coord": (ax, ay), "range": (s, e)}

    return {"rows": rows, "cols": cols, "chiplets": chiplets}


def _pack_footprints_on_square(footprints, side, gap):
    """
    Greedy shelf-packing of chiplet footprints into a square.
    Returns dict(key -> (x, y, w, h)) if all fit, otherwise None.
    """
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

        if x > 0 and (x + w > side):
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
    """
    Compute the minimum integer square side (N) such that N x N can hold all
    chiplet footprints using shelf packing with mandatory gap spacing.
    """
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
    """
    Build a square local-interposer packing plan for a 2.5D complex.
    Each sub-chiplet footprint is CHIP_COLS x CHIP_ROWS.
    Returns:
      - side: local interposer side length (rows == cols == side)
      - placements: dict(subchiplet_index -> (x, y, w, h))
    """
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
    """
    Build:
      - global CHIP_ROWS / CHIP_COLS
      - BASE_ROWS / BASE_COLS (square layout when base is enabled)
      - base_icrt entries
      - chiplet_layout: drives chromosome structure

    Assumptions:
      - Each 2D chiplet is chip_rows x chip_cols.
      - Each 3D chiplet = threeD_height stacked 2D layers.
      - Each 2.5D unit packs two5d_width 2D chiplets on a square local interposer
        with MIN_INTERPOSER_GAP spacing between sub-chiplet footprints.
      - ID ranges are contiguous starting at 0.
    """
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
        # Single-chiplet runs do not use a physical base interposer.
        BASE_ROWS = 0
        BASE_COLS = 0
        placements = {footprints[0]["key"]: (0, 0, footprints[0]["w"], footprints[0]["h"])}

    # Place all 3D chiplets
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

    # Place all 2.5D complexes
    for i in range(num_2p5d_units):
        local_rows = local_2p5d_side
        local_cols = local_2p5d_side
        chip_specs = []

        for c in range(two5d_width):
            cs = next_id
            ce = next_id + routers_per_2d - 1
            # Bottom-right of this sub-chiplet footprint within local interposer
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

    return chiplet_layout, next_id  # next_id == total_routers


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
    return (lx, ly, layer)  # 0-based


def _local_coords_2d(global_router_id, start_id):
    idx = global_router_id - start_id
    ly = idx // CHIP_COLS
    lx = idx % CHIP_COLS
    return (lx, ly)  # 0-based


def _locate_in_2p5d(global_router_id, base_coord, meta_2p5d):
    interposer = meta_2p5d["interposer"]
    cols = interposer["cols"]
    rows = interposer["rows"]
    chiplets = interposer["chiplets"]

    for name, spec in chiplets.items():
        s, e = spec["range"]
        if s <= global_router_id <= e:
            lx, ly = _local_coords_2d(global_router_id, s)
            chiplet_to_local_vl = spec["attach_coord"]
            local_br = (cols - 1, rows - 1)
            global_vl = base_coord
            return {
                "type": "2.5d",
                "chiplet": name,
                "local_coords": (lx, ly),
                "chiplet_to_local_interposer_vl": chiplet_to_local_vl,
                "local_interposer_bottom_right": local_br,
                "local_interposer_to_global_vl": global_vl,
            }

    raise ValueError(f"Router {global_router_id} not found in any 2.5D chiplet")


def locate_router(global_router_id):
    base_coord, meta = _find_stack_for_router(global_router_id)
    if meta is None:
        raise ValueError(f"Global router {global_router_id} not mapped in base_icrt")

    t = meta["type"]
    s, e = meta["range"]

    if t == "3d":
        levels = (e - s + 1) // (CHIP_ROWS * CHIP_COLS)
        lx, ly, lz = _local_coords_3d(global_router_id, s, levels)

        # base_attach_router is stored in chromosome later
        return {
            "type": "3d",
            "chiplet": meta["chiplet"],
            "local_coords": (lx, ly, lz),
            "base_attach_coord": base_coord,  # base interposer (x,y)
        }

    if t == "2.5d":
        return _locate_in_2p5d(global_router_id, base_coord, meta)

    raise ValueError(f"Unsupported type '{t}'")



# =========================
# Cost helpers (3D / 2.5D)
# =========================

def _3d_chiplet_params(router_id):
    base_coord, meta = _find_stack_for_router(router_id)
    if meta is None or meta["type"] != "3d":
        raise ValueError(f"Router {router_id} not in a 3D chiplet")
    start_id, end_id = meta["range"]
    routers_per_level = CHIP_ROWS * CHIP_COLS
    levels = (end_id - start_id + 1) // routers_per_level
    return start_id, end_id, levels, routers_per_level


def _resolve_assigned_tsv_router(current_router, start_id, end_id, routers_per_level):
    tsv_r = tsv_assignment_global.get(current_router)
    if tsv_r is None or not (start_id <= tsv_r <= end_id):
        return None

    levels = (end_id - start_id + 1) // routers_per_level
    _, _, current_z = _local_coords_3d(current_router, start_id, levels)
    layer_offset = start_id + current_z * routers_per_level
    local_idx = tsv_r - layer_offset
    if not (0 <= local_idx < routers_per_level):
        return None

    _, meta = _find_stack_for_router(current_router)
    if meta is None:
        return None
    chip_idx = int(meta["chiplet"].split("_")[1])
    tsv_placement = current_chromosome[chip_idx][1]
    if local_idx >= len(tsv_placement) or tsv_placement[local_idx] != 1:
        return None

    return tsv_r


def _walk_3d_to_level(src_router, dest_level, start_id, end_id, levels, routers_per_level):
    current_router = src_router
    cost = 0.0

    while True:
        cx, cy, cz = _local_coords_3d(current_router, start_id, levels)
        if cz == dest_level:
            break

        direction = 1 if dest_level > cz else -1

        tsv_r = _resolve_assigned_tsv_router(
            current_router, start_id, end_id, routers_per_level
        )
        if tsv_r is None:
            return INF, None
        tx, ty, tz = _local_coords_3d(tsv_r, start_id, levels)
        if tz != cz:
            return INF, None

        cost += (abs(cx - tx) + abs(cy - ty)) * INTRACHIP_LATENCY

        next_z = tz + direction
        if next_z < 0 or next_z >= levels:
            return cost, None

        current_router = start_id + next_z * routers_per_level + ty * CHIP_COLS + tx
        cost += VL_LATENCY

    return cost, current_router


def _same_chiplet_3d_cost(src, dest, s_info, d_info):
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
    sx, sy, sz = _local_coords_3d(router_id, start_id, levels)

    chip_name = info["chiplet"]
    chip_idx = int(chip_name.split("_")[1])
    base_attach_router = int(current_chromosome[chip_idx][3])

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
    start_id, end_id, levels, routers_per_level = _3d_chiplet_params(router_id)
    dx, dy, dz = _local_coords_3d(router_id, start_id, levels)

    chip_name = info["chiplet"]
    chip_idx = int(chip_name.split("_")[1])
    base_attach_router = int(current_chromosome[chip_idx][3])

    ax = int(base_attach_router % CHIP_COLS)
    ay = int(base_attach_router // CHIP_COLS)
    attach_router = start_id + ay * CHIP_COLS + ax

    cost = VL_LATENCY
    current_router = attach_router
    if dz != 0:
        walk_cost, current_router = _walk_3d_to_level(
            attach_router, dz, start_id, end_id, levels, routers_per_level
        )
        if current_router is None:
            return INF
        cost += walk_cost

    cx, cy, _ = _local_coords_3d(current_router, start_id, levels)
    cost += (abs(cx - dx) + abs(cy - dy)) * INTRACHIP_LATENCY

    return cost


def _2p5d_to_base_cost(info):
    lx, ly = info["local_coords"]
    att = info["chiplet_to_local_interposer_vl"]

    chip_name = info["chiplet"]
    chip_idx = int(chip_name.split("_")[0][1:])  # "C<i>_<j>"
    chrom_idx = NUM_3D_CHIPLETS + chip_idx  # offset by 3D chiplets in chromosome ordering
    base_attach_router = int(current_chromosome[chrom_idx][1])

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

    li_to_attach = (abs(att[0] - ax) + abs(att[1] - ay)) * INTERPOSER_LATENCY
    li_attach_to_base = VL_LATENCY

    return src_to_br + br_to_li + li_to_attach + li_attach_to_base


def _base_to_2p5d_cost(info):
    return _2p5d_to_base_cost(info)


# =========================
# Pairwise router cost
# =========================

def calculate_count(src_router, dest_router):
    s = locate_router(src_router)
    d = locate_router(dest_router)

    st = s["type"]
    dt = d["type"]

    # 2.5D <-> 2.5D
    if st == "2.5d" and dt == "2.5d":
        s_base = s["local_interposer_to_global_vl"]
        d_base = d["local_interposer_to_global_vl"]
        sx, sy = s["local_coords"]
        dx, dy = d["local_coords"]

        if s_base == d_base:
            if s["chiplet"] == d["chiplet"]:
                return (abs(sx - dx) + abs(sy - dy)) * INTRACHIP_LATENCY

            src_to_br = (abs(CHIP_COLS - 1 - sx) + abs(CHIP_ROWS - 1 - sy)) * INTRACHIP_LATENCY
            dest_to_br = (abs(CHIP_COLS - 1 - dx) + abs(CHIP_ROWS - 1 - dy)) * INTRACHIP_LATENCY

            s_br_loc = s["chiplet_to_local_interposer_vl"]
            d_br_loc = d["chiplet_to_local_interposer_vl"]

            br_to_br = (
                abs(s_br_loc[0] - d_br_loc[0]) +
                abs(s_br_loc[1] - d_br_loc[1])
            ) * INTERPOSER_LATENCY

            return src_to_br + dest_to_br + br_to_br + 2 * VL_LATENCY

        cost_src_to_base = _2p5d_to_base_cost(s)
        cost_dest_from_base = _base_to_2p5d_cost(d)
        base_to_base = (
            abs(s_base[0] - d_base[0]) +
            abs(s_base[1] - d_base[1])
        ) * INTERPOSER_LATENCY
        return cost_src_to_base + base_to_base + cost_dest_from_base

    # 3D <-> 3D
    if st == "3d" and dt == "3d":
        if s["chiplet"] == d["chiplet"]:
            return _same_chiplet_3d_cost(src_router, dest_router, s, d)

        cost_src_to_base = _3d_to_base_cost(src_router, s)
        cost_dest_from_base = _base_to_3d_cost(dest_router, d)
        s_base = s["base_attach_coord"]
        d_base = d["base_attach_coord"]
        base_to_base = (
            abs(s_base[0] - d_base[0]) +
            abs(s_base[1] - d_base[1])
        ) * INTERPOSER_LATENCY
        return cost_src_to_base + base_to_base + cost_dest_from_base

    # 3D -> 2.5D
    if st == "3d" and dt == "2.5d":
        cost_src_to_base = _3d_to_base_cost(src_router, s)
        c_base = d["local_interposer_to_global_vl"]
        s_base = s["base_attach_coord"]
        base_walk = (
            abs(s_base[0] - c_base[0]) +
            abs(s_base[1] - c_base[1])
        ) * INTERPOSER_LATENCY
        cost_dest_from_base = _base_to_2p5d_cost(d)
        return cost_src_to_base + base_walk + cost_dest_from_base

    # 2.5D -> 3D
    if st == "2.5d" and dt == "3d":
        cost_src_to_base = _2p5d_to_base_cost(s)
        s_base = s["local_interposer_to_global_vl"]
        d_base = d["base_attach_coord"]
        base_walk = (
            abs(s_base[0] - d_base[0]) +
            abs(s_base[1] - d_base[1])
        ) * INTERPOSER_LATENCY
        cost_dest_from_base = _base_to_3d_cost(dest_router, d)
        return cost_src_to_base + base_walk + cost_dest_from_base

    raise ValueError(f"Unsupported type combination: {st} -> {dt}")


# =========================
# Optional: cost normalization from adjacency
# =========================

def compute_max_cost_from_adj(adj):
    n = len(adj)
    max_cost = 0.0
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            bw = adj[i][j]
            if isinstance(bw, str):
                if bw.upper() == "INF":
                    continue
                bw = float(bw)
            if bw == INF or bw <= 0:
                continue
            c = calculate_count(i, j) * bw
            if c > max_cost:
                max_cost = c
    return max_cost


def normalize_cost(src, dest, adj, max_cost):
    if max_cost <= 0:
        return 0.0
    bw = adj[src][dest]
    if isinstance(bw, str):
        if bw.upper() == "INF":
            return 0.0
        bw = float(bw)
    if bw == INF or bw <= 0:
        return 0.0
    return (calculate_count(src, dest) * bw) / max_cost

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


def init_normalization_terms(graph_name, edge_set_file, threeD_height):
    global MAX_COMM_COST, VAR_COMM_SQ

    input_graph = graph_input_path(graph_name)
    with open(input_graph, "r") as f:
        no_of_cores = int(f.readline().strip())

    max_bw = 0.0
    total_bw = 0.0
    with open(edge_set_file, "r") as f:
        for line in f:
            vals = line.split()
            if len(vals) < 3:
                continue
            bw = float(vals[2])
            if bw > max_bw:
                max_bw = bw
            total_bw += bw

    if max_bw <= 0.0:
        max_bw = 1.0
    if total_bw <= 0.0:
        total_bw = 1.0

    base_hops = 0
    if BASE_INTERPOSER_ENABLED and BASE_ROWS > 0 and BASE_COLS > 0:
        base_hops = (BASE_ROWS - 1 + BASE_COLS - 1)

    max_hops = (
        (CHIP_ROWS - 1 + CHIP_COLS - 1) * threeD_height
        + (threeD_height - 1)
        + base_hops
    )

    if max_hops <= 0:
        max_hops = 1

    MAX_COMM_COST = max_bw * max_hops * no_of_cores
    VAR_COMM_SQ = total_bw * total_bw

# =========================
# Chromosome & TSV helpers
# =========================

def _validate_tsv_assignment_mode(mode):
    mode = int(mode)
    if mode not in (TSV_ASSIGNMENT_RANDOM, TSV_ASSIGNMENT_ELEVATOR_FIRST):
        raise ValueError(
            "TSV assignment mode must be 0 (random) or 1 (redelf)"
        )
    return mode


def _tsv_assignment_mode_name(mode=None):
    mode = TSV_ASSIGNMENT_MODE if mode is None else _validate_tsv_assignment_mode(mode)
    if mode == TSV_ASSIGNMENT_RANDOM:
        return "random"
    return "redelf"


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


def _is_south_or_due_east(candidate_local_idx, source_local_idx):
    cx = candidate_local_idx % CHIP_COLS
    cy = candidate_local_idx // CHIP_COLS
    sx = source_local_idx % CHIP_COLS
    sy = source_local_idx // CHIP_COLS
    return cy > sy or (cy == sy and cx >= sx)


def _redelf_pivot_local_index(tsv_local_indices):
    if not tsv_local_indices:
        raise ValueError("tsv_local_indices cannot be empty")
    return max(tsv_local_indices, key=lambda t: (t // CHIP_COLS, t % CHIP_COLS))


def _select_redelf_tsv_local_index(router_local_idx,
                                  desired_tsv_local_indices,
                                  opposite_tsv_local_indices=None):
    """
    Apply REDELF Ruleset B with south as the primary direction and east as the
    secondary direction. In this code's TSV model, vertical links are
    bidirectional and repeated at the same local coordinates on every layer, so
    desired/opposite sets are usually identical.
    """
    if not desired_tsv_local_indices:
        raise ValueError("desired_tsv_local_indices cannot be empty")

    desired = sorted(set(desired_tsv_local_indices))
    opposite = sorted(set(
        desired if opposite_tsv_local_indices is None else opposite_tsv_local_indices
    ))

    southeast_candidates = [
        t for t in desired if _is_south_or_due_east(t, router_local_idx)
    ]
    selected_by_b1 = bool(southeast_candidates)

    if selected_by_b1:
        chosen = _nearest_tsv_local_index(router_local_idx, southeast_candidates)
    else:
        chosen = _redelf_pivot_local_index(desired)

    if selected_by_b1 and chosen != router_local_idx and opposite:
        opposite_pivot = _redelf_pivot_local_index(opposite)
        if _is_south_or_due_east(chosen, opposite_pivot):
            chosen = _redelf_pivot_local_index(desired)

    return chosen


def _select_tsv_local_index(router_local_idx, candidate_local_indices):
    if not candidate_local_indices:
        raise ValueError("candidate_local_indices cannot be empty")
    if TSV_ASSIGNMENT_MODE == TSV_ASSIGNMENT_RANDOM:
        return random.choice(candidate_local_indices)
    if TSV_ASSIGNMENT_MODE == TSV_ASSIGNMENT_REDELF:
        return _select_redelf_tsv_local_index(
            router_local_idx,
            candidate_local_indices,
        )
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

def generate_chromosome_3p5d(chiplet_layout, tsv_list):
    total_routers = sum(chip["no_routers"] for chip in chiplet_layout)
    global_core_perm = random.sample(range(total_routers), total_routers)

    chromosome = []
    idx = 0

    for chip in chiplet_layout:
        chip_type = chip["type"]
        no_routers = chip["no_routers"]

        core_to_router = global_core_perm[idx:idx + no_routers]
        idx += no_routers

        if chip_type == "3d":
            no_levels = chip["no_levels"]
            routers_per_level = no_routers // no_levels

            tsv_placement = [random.choice([0, 1]) for _ in range(routers_per_level)]
            tsv_assignment = _build_initial_tsv_assignment(
                chip["range"][0],
                no_levels,
                routers_per_level,
                tsv_placement,
            )

            # NEW: base interposer attach router (bottom layer only)
            base_attach_router = random.randrange(routers_per_level)

            chip_gene = [
                core_to_router,
                tsv_placement,
                tsv_assignment,
                base_attach_router
            ]

        elif chip_type == "2.5d":
            # NEW: base interposer attach router on local interposer
            local_rows = chip["interposer"]["rows"]
            local_cols = chip["interposer"]["cols"]
            local_area = local_rows * local_cols
            if local_area <= 0:
                raise ValueError(f"Invalid local interposer size for {chip['name']}: {local_rows}x{local_cols}")
            base_attach_router = random.randrange(local_area)

            chip_gene = [
                core_to_router,
                base_attach_router
            ]

        else:
            raise ValueError(f"Unknown chiplet type: {chip_type}")

        chromosome.append(chip_gene)

    return chromosome



def _validate_tsv_placement_single_3d(tsv_placement, router_coordinates, base_offset, routers_per_level):
    initial_tsv_count = tsv_placement.count(1)
    max_tsvs = max(2, math.floor(0.25 * routers_per_level))

    def is_manhattan_distance_greater_than_1(i, j):
        r1 = base_offset + i
        r2 = base_offset + j
        x1, y1, z1 = router_coordinates[r1]
        x2, y2, z2 = router_coordinates[r2]
        if z1 != z2:
            return True
        return abs(x1 - x2) + abs(y1 - y2) > 1

    def find_valid_tsv_position(tp):
        available = [idx for idx, b in enumerate(tp) if b == 0]
        random.shuffle(available)
        for i in available:
            if tp.count(1) >= max_tsvs:
                break
            ok = True
            for j, b in enumerate(tp):
                if b == 1 and not is_manhattan_distance_greater_than_1(i, j):
                    ok = False
                    break
            if ok:
                return i
        return None

    # Ensure minimum TSVs
    if tsv_placement.count(1) < 2:
        need = min(2 - tsv_placement.count(1), max_tsvs - tsv_placement.count(1))
        zeros = [i for i, b in enumerate(tsv_placement) if b == 0]
        for _ in range(need):
            if not zeros:
                break
            idx = random.choice(zeros)
            zeros.remove(idx)
            tsv_placement[idx] = 1

    # Resolve conflicts
    tsv_indices = [i for i, b in enumerate(tsv_placement) if b == 1]
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
        for a_i, i in enumerate(tsv_indices):
            for j in tsv_indices[a_i+1:]:
                if not is_manhattan_distance_greater_than_1(i, j):
                    conflicts.append((i, j))
        for i, j in conflicts:
            if tsv_placement.count(1) > 2:
                kill = random.choice([i, j])
                tsv_placement[kill] = 0

    # Attempt to restore up to initial count within constraints
    restored = 0
    attempts = 0
    max_attempts = routers_per_level
    while (tsv_placement.count(1) < max_tsvs and
           restored < (initial_tsv_count - tsv_placement.count(1)) and
           attempts < max_attempts):
        pos = find_valid_tsv_position(tsv_placement)
        if pos is not None:
            tsv_placement[pos] = 1
            restored += 1
        attempts += 1

    # Trim excess
    while tsv_placement.count(1) > max_tsvs:
        idxs = [i for i, b in enumerate(tsv_placement) if b == 1]
        if len(idxs) > 2:
            tsv_placement[random.choice(idxs)] = 0
        else:
            break

    # Final guarantee: at least 2
    if tsv_placement.count(1) < 2:
        zeros = [i for i, b in enumerate(tsv_placement) if b == 0]
        while tsv_placement.count(1) < 2 and zeros:
            pos = find_valid_tsv_position(tsv_placement)
            if pos is not None:
                tsv_placement[pos] = 1
            else:
                idx = random.choice(zeros)
                zeros.remove(idx)
                tsv_placement[idx] = 1

    return tsv_placement


def validate_tsv_placement_3p5d(chromosome, chiplet_layout, router_coordinates):
    offset = 0
    for idx, chip in enumerate(chiplet_layout):
        no_routers = chip["no_routers"]
        if chip["type"] == "3d":
            no_levels = chip["no_levels"]
            routers_per_level = no_routers // no_levels
            core_to_router, tsv_placement, tsv_assignment, base_attach = chromosome[idx]
            tsv_placement = _validate_tsv_placement_single_3d(
                tsv_placement,
                router_coordinates,
                base_offset=offset,
                routers_per_level=routers_per_level
            )
            chromosome[idx][1] = tsv_placement
        offset += no_routers
    return chromosome



def _count_vertical_communications_3d_chip(core_to_router, router_coordinates, edge_set_file, chip_range):
    start, end = chip_range
    vertical = 0
    with open(edge_set_file, "r") as f:
        for line in f:
            vals = line.split()
            if len(vals) < 3:
                continue
            src_core = int(vals[0])
            dest_core = int(vals[1])
            if src_core in core_to_router and dest_core in core_to_router:
                # core_to_router stores a chip-local ordering; convert back to
                # global router ids before comparing against the chip range.
                src_router = start + core_to_router.index(src_core)
                dest_router = start + core_to_router.index(dest_core)
                if not (start <= src_router < end and start <= dest_router < end):
                    continue
                z1 = router_coordinates[src_router][2]
                z2 = router_coordinates[dest_router][2]
                if z1 != z2:
                    vertical += 1
    return vertical


def _validate_tsv_assignment_single_3d(tsv_placement, no_routers, no_levels,
                                      core_to_router, router_coordinates,
                                      edge_set_file, base_offset, routers_per_level):
    tsv_assignment = [0] * no_routers
    chip_range = (base_offset, base_offset + no_routers)
    vertical_comms = _count_vertical_communications_3d_chip(
        core_to_router, router_coordinates, edge_set_file, chip_range
    )

    for layer in range(no_levels):
        layer_offset = base_offset + layer * routers_per_level
        tsv_list = [layer_offset + i for i, b in enumerate(tsv_placement) if b == 1]

        if tsv_list:
            max_assign = max(1, vertical_comms // len(tsv_list)) + 1
            tsv_count = {t: 0 for t in tsv_list}
            for r in range(layer_offset, layer_offset + routers_per_level):
                if TSV_ASSIGNMENT_MODE == TSV_ASSIGNMENT_REDELF:
                    candidate_tsvs = tsv_list
                else:
                    available = [t for t, c in tsv_count.items() if c < max_assign]
                    candidate_tsvs = available if available else tsv_list
                candidate_local_indices = [t - layer_offset for t in candidate_tsvs]
                chosen = layer_offset + _select_tsv_local_index(
                    r - layer_offset,
                    candidate_local_indices,
                )
                local_idx = r - base_offset
                tsv_assignment[local_idx] = chosen
                tsv_count[chosen] += 1
        else:
            for r in range(layer_offset, layer_offset + routers_per_level):
                local_idx = r - base_offset
                tsv_assignment[local_idx] = layer_offset

    return tsv_assignment


def validate_tsv_assignment_3p5d(chromosome, chiplet_layout, router_coordinates, edge_set_file):
    offset = 0
    for idx, chip in enumerate(chiplet_layout):
        no_routers = chip["no_routers"]
        if chip["type"] == "3d":
            no_levels = chip["no_levels"]
            routers_per_level = no_routers // no_levels
            core_to_router, tsv_placement, _, base_attach = chromosome[idx]
            tsv_assignment = _validate_tsv_assignment_single_3d(
                tsv_placement,
                no_routers,
                no_levels,
                core_to_router,
                router_coordinates,
                edge_set_file,
                base_offset=offset,
                routers_per_level=routers_per_level
            )
            chromosome[idx][2] = tsv_assignment
        offset += no_routers
    return chromosome


def _trace_3d_vertical_pairs(start_router, target_level, chip, tsv_assignment):
    """
    Return the ordered vertical TSV links traversed inside one 3D chiplet when
    moving from start_router to target_level.
    """
    start_id, end_id = chip["range"]
    no_levels = chip["no_levels"]
    routers_per_level = chip["no_routers"] // no_levels

    current_router = start_router
    traversed_pairs = []

    while True:
        local_idx = current_router - start_id
        current_level = local_idx // routers_per_level
        if current_level == target_level:
            break

        direction = 1 if target_level > current_level else -1

        tsv_router = tsv_assignment.get(current_router, current_router)
        if not (start_id <= tsv_router <= end_id):
            tsv_router = current_router

        tsv_local_idx = tsv_router - start_id
        tsv_level = tsv_local_idx // routers_per_level
        if tsv_level != current_level:
            tsv_router = current_router
            tsv_local_idx = local_idx

        next_level = current_level + direction
        if next_level < 0 or next_level >= no_levels:
            break

        pos_in_layer = tsv_local_idx % routers_per_level
        neighbor_router = start_id + next_level * routers_per_level + pos_in_layer
        traversed_pairs.append((tsv_router, neighbor_router))
        current_router = neighbor_router

    return traversed_pairs


def tsv_variance_3p5d(chromosome, chiplet_layout, router_coordinates, edge_set_file):
    core_to_router_map = build_core_to_router_map(chromosome, chiplet_layout)
    tsv_assignment = build_global_tsv_assignment(chromosome, chiplet_layout)

    router_to_chip = {}
    for idx, chip in enumerate(chiplet_layout):
        if chip["type"] == "3d":
            start_id, end_id = chip["range"]
            for rid in range(start_id, end_id + 1):
                router_to_chip[rid] = idx

    tsv_traffic = {}
    for chip_idx, chip in enumerate(chiplet_layout):
        if chip["type"] != "3d":
            continue
        no_routers = chip["no_routers"]
        no_levels = chip["no_levels"]
        start_id, end_id = chip["range"]
        routers_per_level = no_routers // no_levels
        tsv_place = chromosome[chip_idx][1]

        for layer in range(no_levels - 1):
            base_offset = start_id + layer * routers_per_level
            for i, bit in enumerate(tsv_place):
                if bit == 1:
                    lower = base_offset + i                    
                    upper = lower + routers_per_level
                    tsv_traffic[(lower, upper)] = 0.0
                    tsv_traffic[(upper, lower)] = 0.0

    with open(edge_set_file, "r") as f:
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

            src_chip_idx = router_to_chip.get(src_router)
            dest_chip_idx = router_to_chip.get(dest_router)

            # Same 3D chiplet: trace the direct in-stack path.
            if src_chip_idx is not None and src_chip_idx == dest_chip_idx:
                src_level = router_coordinates[src_router][2]
                dest_level = router_coordinates[dest_router][2]
                if src_level == dest_level:
                    continue

                chip = chiplet_layout[src_chip_idx]
                traversed_pairs = _trace_3d_vertical_pairs(
                    src_router,
                    dest_level,
                    chip,
                    tsv_assignment,
                )
                for pair in traversed_pairs:
                    if pair in tsv_traffic:
                        tsv_traffic[pair] += bw
                continue

            # Different chiplets: count the source-side descent to base for 3D
            # sources, then the destination-side ascent from base for 3D sinks.
            if src_chip_idx is not None:
                src_level = router_coordinates[src_router][2]
                if src_level != 0:
                    chip = chiplet_layout[src_chip_idx]
                    traversed_pairs = _trace_3d_vertical_pairs(
                        src_router,
                        0,
                        chip,
                        tsv_assignment,
                    )
                    for pair in traversed_pairs:
                        if pair in tsv_traffic:
                            tsv_traffic[pair] += bw

            if dest_chip_idx is not None:
                dest_level = router_coordinates[dest_router][2]
                if dest_level != 0:
                    chip = chiplet_layout[dest_chip_idx]
                    traversed_pairs = _trace_3d_vertical_pairs(
                        dest_router,
                        0,
                        chip,
                        tsv_assignment,
                    )
                    # The helper traces destination -> base. Reverse each link to
                    # represent the actual base -> destination traffic direction.
                    for lower_pair in traversed_pairs:
                        reversed_pair = (lower_pair[1], lower_pair[0])
                        if reversed_pair in tsv_traffic:
                            tsv_traffic[reversed_pair] += bw

    up_vals = []
    down_vals = []
    for (a, b), v in tsv_traffic.items():
        if router_coordinates[a][2] < router_coordinates[b][2]:
            up_vals.append(v)
        else:
            down_vals.append(v)

    def _variance(lst):
        if not lst:
            return 0.0
        m = sum(lst) / len(lst)
        return sum((x - m) ** 2 for x in lst) / len(lst)

    return _variance(up_vals), _variance(down_vals)

def fix_core_to_router_mapping_3p5d(chromosome, chiplet_layout):
    total_routers = sum(chip["no_routers"] for chip in chiplet_layout)

    flat = []
    for chip_idx, chip in enumerate(chiplet_layout):
        core_to_router = chromosome[chip_idx][0]
        flat.extend(core_to_router)

    actual_set = set(range(total_routers))
    missing = list(actual_set - set(flat))
    repeated_indices = []
    seen = {}

    for i, val in enumerate(flat):
        if val in seen:
            repeated_indices.append(i)
        else:
            seen[val] = i

    random.shuffle(repeated_indices)
    limit = min(len(missing), len(repeated_indices))
    for k in range(limit):
        flat[repeated_indices[k]] = missing[k]

    idx = 0
    for chip_idx, chip in enumerate(chiplet_layout):
        n = chip["no_routers"]
        chromosome[chip_idx][0] = flat[idx:idx + n]
        idx += n

    return chromosome


def crossover_3p5d(parents, chiplet_layout):
    parent1, parent2 = parents
    child1, child2 = [], []

    for chip_idx, chip in enumerate(chiplet_layout):
        chip_type = chip["type"]
        no_routers = chip["no_routers"]

        if chip_type == "3d":
            p1_core, p1_tsv, _, p1_attach = parent1[chip_idx]
            p2_core, p2_tsv, _, p2_attach = parent2[chip_idx]

            cut = no_routers // 2
            c1_core = p1_core[:cut] + p2_core[cut:]
            c2_core = p2_core[:cut] + p1_core[cut:]

            cut_tsv = len(p1_tsv) // 2
            c1_tsv = p1_tsv[:cut_tsv] + p2_tsv[cut_tsv:]
            c2_tsv = p2_tsv[:cut_tsv] + p1_tsv[cut_tsv:]

            c1_attach = random.choice([p1_attach, p2_attach])
            c2_attach = random.choice([p1_attach, p2_attach])

            child1.append([c1_core, c1_tsv, [0]*no_routers, c1_attach])
            child2.append([c2_core, c2_tsv, [0]*no_routers, c2_attach])

        elif chip_type == "2.5d":
            p1_core, p1_attach = parent1[chip_idx]
            p2_core, p2_attach = parent2[chip_idx]

            cut = no_routers // 2
            c1_core = p1_core[:cut] + p2_core[cut:]
            c2_core = p2_core[:cut] + p1_core[cut:]

            c1_attach = random.choice([p1_attach, p2_attach])
            c2_attach = random.choice([p1_attach, p2_attach])

            child1.append([c1_core, c1_attach])
            child2.append([c2_core, c2_attach])

    child1 = fix_core_to_router_mapping_3p5d(child1, chiplet_layout)
    child2 = fix_core_to_router_mapping_3p5d(child2, chiplet_layout)

    return child1, child2



def mutate_chromosome_3p5d(chromosome, chiplet_layout, router_coordinates, edge_set_file):
    child = deepcopy(chromosome)

    for chip_idx, chip in enumerate(chiplet_layout):
        chip_type = chip["type"]
        no_routers = chip["no_routers"]

        if chip_type == "3d":
            no_levels = chip["no_levels"]
            routers_per_level = no_routers // no_levels
            core_to_router, tsv_placement, _, base_attach = child[chip_idx]

            if no_routers > 1:
                pivot = random.randint(0, no_routers - 1)
                if random.choice(("left", "right")) == "left":
                    core_to_router = core_to_router[:pivot][::-1] + core_to_router[pivot:]
                else:
                    core_to_router = core_to_router[:pivot] + core_to_router[pivot:][::-1]

            if routers_per_level > 1:
                pivot = random.randint(0, routers_per_level - 1)
                if random.choice(("left", "right")) == "left":
                    tsv_placement = tsv_placement[:pivot][::-1] + tsv_placement[pivot:]
                else:
                    tsv_placement = tsv_placement[:pivot] + tsv_placement[pivot:][::-1]

            child[chip_idx] = [core_to_router, tsv_placement, [0]*no_routers, base_attach]

        elif chip_type == "2.5d":
            core_to_router, base_attach = child[chip_idx]
            if no_routers > 1:
                pivot = random.randint(0, no_routers - 1)
                if random.choice(("left", "right")) == "left":
                    core_to_router = core_to_router[:pivot][::-1] + core_to_router[pivot:]
                else:
                    core_to_router = core_to_router[:pivot] + core_to_router[pivot:][::-1]
            child[chip_idx] = [core_to_router, base_attach]

    child = fix_core_to_router_mapping_3p5d(child, chiplet_layout)
    child = validate_tsv_placement_3p5d(child, chiplet_layout, router_coordinates)
    child = validate_tsv_assignment_3p5d(child, chiplet_layout, router_coordinates, edge_set_file)

    return child



# =========================
# Router coordinates
# =========================

def assign_router_coordinates(total_routers):
    """
    Build router_coordinates[router_id] = (x,y,z)
    for TSV helper logic.
    """
    coords = {}
    for (bx, by), meta in base_icrt.items():
        s, e = meta["range"]
        t = meta["type"]
        if t == "3d":
            levels = (e - s + 1) // (CHIP_ROWS * CHIP_COLS)
            for rid in range(s, e + 1):
                lx, ly, lz = _local_coords_3d(rid, s, levels)
                coords[rid] = (lx, ly, lz)
        else:
            for rid in range(s, e + 1):
                lx, ly = _local_coords_2d(rid, s)
                coords[rid] = (lx, ly, 0)

    if len(coords) != total_routers:
        raise RuntimeError("Router coordinate map incomplete")
    return coords


# =========================
# Cost evaluation
# =========================

def build_core_to_router_map(chromosome, chiplet_layout):
    mapping = {}
    offset = 0
    for idx, chip in enumerate(chiplet_layout):
        core_to_router = chromosome[idx][0]
        for local_r, core in enumerate(core_to_router):
            mapping[core] = offset + local_r
        offset += chip["no_routers"]
    return mapping



def build_global_tsv_assignment(chromosome, chiplet_layout):
    assignment = {}
    offset = 0
    for idx, chip in enumerate(chiplet_layout):
        if chip["type"] == "3d":
            _, _, local_tsv, _ = chromosome[idx]
            for local_r, tsv_r in enumerate(local_tsv):
                assignment[offset + local_r] = tsv_r
        offset += chip["no_routers"]
    return assignment



def cost_function_3p5d(chromosome, chiplet_layout, edge_set_file):
    global tsv_assignment_global
    global current_chromosome
    current_chromosome = chromosome


    core_to_router_map = build_core_to_router_map(chromosome, chiplet_layout)
    tsv_assignment_global = build_global_tsv_assignment(chromosome, chiplet_layout)

    total_cost = 0.0
    with open(edge_set_file, "r") as f:
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

            link_cost = calculate_count(src_router, dest_router)
            total_cost += link_cost * bw

    return total_cost


def fitness_terms_3p5d(chromosome, chiplet_layout, router_coordinates, edge_set_file):
    cost = cost_function_3p5d(chromosome, chiplet_layout, edge_set_file)
    var_up, var_down = tsv_variance_3p5d(chromosome, chiplet_layout, router_coordinates, edge_set_file)
    variance = max(var_up, var_down)

    if MAX_COMM_COST <= 0.0:
        norm_cost = cost
    else:
        norm_cost = (W_FACTOR * cost) / MAX_COMM_COST

    if VAR_COMM_SQ <= 0.0:
        norm_var = variance
    else:
        norm_var = ((1.0 - W_FACTOR) * variance) / VAR_COMM_SQ

    effective_fitness = norm_cost + norm_var
    return effective_fitness, cost, variance, var_up, var_down


# =========================
# GA main loop
# =========================

def run_ga_3p5d(graph_name,
                chip_rows, chip_cols,
                two5d_width, threeD_height,
                num_2p5d_units, num_3d_units,
                iterations, population_size,
                tsv_assignment_mode=TSV_ASSIGNMENT_RANDOM,
                seed=None):

    if create_edge_set is None:
        raise RuntimeError("edge_set_creation_new.create_edge_set not available")

    global RANDOM_SEED, TSV_ASSIGNMENT_MODE
    RANDOM_SEED = int(time.time()) if seed is None else int(seed)
    TSV_ASSIGNMENT_MODE = _validate_tsv_assignment_mode(tsv_assignment_mode)
    random.seed(RANDOM_SEED)
    print(f"Using random seed: {RANDOM_SEED}")
    print(f"Using TSV assignment mode: {_tsv_assignment_mode_name()}")

    start_time = time.time()

    # --------------------------------------------------
    # 1. Build topology
    # --------------------------------------------------
    chiplet_layout, total_routers = build_topology(
        chip_rows, chip_cols,
        two5d_width, threeD_height,
        num_2p5d_units, num_3d_units
    )

    # --------------------------------------------------
    # 2. Build edge-set from adjacency matrix
    # --------------------------------------------------
    input_graph = graph_input_path(graph_name)
    edge_set_file = edge_set_output_path(graph_name)
    create_edge_set(input_graph, edge_set_file)

    # --------------------------------------------------
    # 3. Router coordinates (for TSV logic)
    # --------------------------------------------------
    router_coordinates = assign_router_coordinates(total_routers)
    init_normalization_terms(graph_name, edge_set_file, threeD_height)

    # --------------------------------------------------
    # 4. Initial population
    # --------------------------------------------------
    tsv_list = list(range(total_routers))
    population = []

    for _ in range(population_size):
        chrom = generate_chromosome_3p5d(chiplet_layout, tsv_list)
        chrom = fix_core_to_router_mapping_3p5d(chrom, chiplet_layout)
        chrom = validate_tsv_placement_3p5d(chrom, chiplet_layout, router_coordinates)
        chrom = validate_tsv_assignment_3p5d(
            chrom, chiplet_layout, router_coordinates, edge_set_file
        )
        population.append(chrom)

    # --------------------------------------------------
    # 5. Evaluate initial population (EFFECTIVE FITNESS)
    # --------------------------------------------------
    pop_with_cost = []
    for chrom in population:
        eff_fit, cost, _, _, _ = fitness_terms_3p5d(
            chrom, chiplet_layout, router_coordinates, edge_set_file
        )
        pop_with_cost.append((chrom, eff_fit, cost))

    best_fitness = float("inf")
    best_cost = float("inf")
    best_chromosome = None
    stable_iters = 0
    no_improve_iters = 0

    # --------------------------------------------------
    # 6. GA iterations
    # --------------------------------------------------
    for iteration in range(iterations):
        pop_with_cost.sort(key=lambda x: x[1])
        current_best_fitness = pop_with_cost[0][1]

        if current_best_fitness < best_fitness:
            best_fitness = current_best_fitness
            best_cost = pop_with_cost[0][2]
            best_chromosome = pop_with_cost[0][0]
            stable_iters = 0
            no_improve_iters = 0
        else:
            stable_iters += 1
            no_improve_iters += 1

        if no_improve_iters >= EARLY_STOP_PATIENCE:
            print(f"Early stopping at iteration {iteration + 1} after {EARLY_STOP_PATIENCE} stagnant iterations without improvement.")
            break

        # ---------- Elitism ----------
        num_elite = max(1, int(ELITE_PERCENTAGE * population_size))
        elites = [c for c, _, _ in pop_with_cost[:num_elite]]

        # ---------- Selection ----------
        sel_size = max(2, int(SELECTION_PERCENTAGE * population_size))
        selection_pool = pop_with_cost[:sel_size]

        # ---------- Reproduction ----------
        new_population = elites[:]
        while len(new_population) < population_size:
            p1, _, _ = random.choice(selection_pool)
            p2, _, _ = random.choice(selection_pool)

            child1, child2 = crossover_3p5d((p1, p2), chiplet_layout)

            for child in (child1, child2):
                child = fix_core_to_router_mapping_3p5d(child, chiplet_layout)
                child = validate_tsv_placement_3p5d(
                    child, chiplet_layout, router_coordinates
                )
                child = validate_tsv_assignment_3p5d(
                    child, chiplet_layout, router_coordinates, edge_set_file
                )
                new_population.append(child)
                if len(new_population) >= population_size:
                    break

        # ---------- Mutation on stagnation ----------
        if stable_iters >= MUTATION_STAGNATION:
            for i in range(num_elite, len(new_population)):
                new_population[i] = mutate_chromosome_3p5d(
                    new_population[i],
                    chiplet_layout,
                    router_coordinates,
                    edge_set_file,
                )
            stable_iters = 0

        # ---------- Re-evaluate ----------
        pop_with_cost = [
            (chrom, *fitness_terms_3p5d(chrom, chiplet_layout, router_coordinates, edge_set_file)[:2])
            for chrom in new_population
        ]

        # ---------- Ensure global best survives ----------
        if best_chromosome is not None:
            if all(ch != best_chromosome for ch, _, _ in pop_with_cost):
                pop_with_cost[-1] = (best_chromosome, best_fitness, best_cost)

        # ---------- Logging ----------
        gen_best = min(pop_with_cost, key=lambda x: x[1])
        if gen_best[1] < best_fitness:
            best_fitness = gen_best[1]
            best_cost = gen_best[2]
            best_chromosome = gen_best[0]
            stable_iters = 0
            no_improve_iters = 0
        eff_fit, hop_cost, var, var_up, var_down = fitness_terms_3p5d(
            gen_best[0], chiplet_layout, router_coordinates, edge_set_file
        )
        print(
            f"Iteration {iteration + 1}: "
            f"HopCost = {hop_cost:.6f} | "
            f"Variance = {var:.6f} (up {var_up:.6f}, down {var_down:.6f}) | "
            f"EffectiveFitness = {eff_fit:.6f}"
        )

    # --------------------------------------------------
    # 7. Final result
    # --------------------------------------------------
    end_time = time.time()

    # Compute variance terms for the best chromosome
    final_eff_fit = None
    final_var = None
    final_var_up = None
    final_var_down = None
    if best_chromosome is not None:
        final_eff_fit, _, final_var, final_var_up, final_var_down = fitness_terms_3p5d(
            best_chromosome, chiplet_layout, router_coordinates, edge_set_file
        )

    print("\n=== 3.5D GA Result ===")
    print(f"Graph:         {graph_name}")
    print(f"Total routers: {total_routers}")
    print(f"Best cost:     {best_cost:.6f}")
    if final_eff_fit is not None:
        print(f"Effective fitness: {final_eff_fit:.6f}")
    if final_var is not None:
        print(f"Variance:      {final_var:.6f} (up {final_var_up:.6f}, down {final_var_down:.6f})")
    print(f"Real time:     {end_time - start_time:.2f} s")

    print("\nBest Chromosome (by chiplet):")
    for idx, chip in enumerate(chiplet_layout):
        if chip["type"] == "3d":
            core_to_router, tsv_place, tsv_assign, base_attach = best_chromosome[idx]
            print(f"  {chip['name']} (3D): VL={chip['vl_coord']}, range={chip['range']}")
            print(f"    Core->Router: {core_to_router}")
            print(f"    TSV place:    {tsv_place}")
            print(f"    TSV assign:   {tsv_assign}")
            print(f"    Base attach router (bottom layer): {base_attach}")
        else:
            core_to_router, base_attach = best_chromosome[idx]
            print(f"  {chip['name']} (2.5D): VL={chip['vl_coord']}, range={chip['range']}")
            print(f"    Core->Router: {core_to_router}")
            print(f"    Base attach router (local interposer): {base_attach}")

    if best_chromosome is not None:
        particle_path = particle_output_path(graph_name)
        write_particle_file(
            particle_path,
            graph_name,
            chip_rows, chip_cols,
            two5d_width, threeD_height,
            num_2p5d_units, num_3d_units,
            best_chromosome,
            chiplet_layout,
            best_cost,
            final_eff_fit,
            final_var,
            final_var_up,
            final_var_down,
        )

    return best_chromosome, best_cost


def particle_output_path(graph_name):
    match = re.search(r"(\d+)$", graph_name)
    if match and graph_name.lower().startswith("graph"):
        return os.path.join("Particles", f"GA_Particle{match.group(1)}.txt")
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", graph_name.strip()) or "graph"
    return os.path.join("Particles", f"GA_Particle_{safe}.txt")


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
    """
    Convert local interposer metadata into JSON-friendly plain ints.
    """
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


def _build_simple_particle_entry(chip, gene):
    entry = {
        "type": chip["type"],
        "name": chip["name"],
        "vl_coord": list(chip["vl_coord"]),
        "range": list(chip["range"]),
        "no_routers": int(chip["no_routers"]),
    }

    if chip["type"] == "3d":
        core_to_router, tsv_place, tsv_assign, base_attach = gene
        entry.update({
            "no_levels": int(chip["no_levels"]),
            "base_attach_router": int(base_attach),
            "core_to_router": [int(v) for v in core_to_router],
            "tsv_placement": [int(v) for v in tsv_place],
            "tsv_assignment": [int(v) for v in tsv_assign],
        })
    else:
        core_to_router, base_attach = gene
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
                        best_chromosome,
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
        "chromosome": best_chromosome,
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
        data["base"] = {
            "rows": BASE_ROWS,
            "cols": BASE_COLS,
        }

    for idx, chip in enumerate(chiplet_layout):
        entry = _build_simple_particle_entry(chip, best_chromosome[idx])
        data["chiplets"].append(entry)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")



# =========================
# CLI entry
# =========================

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
    parser.add_argument("population_size", type=int)
    parser.add_argument(
        "tsv_assignment_mode",
        type=int,
        choices=[0, 1],
        help="TSV assignment mode: 0=random, 1=redelf",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for GA. Omit to use the current system time.",
    )
    args = parser.parse_args()

    run_ga_3p5d(
        args.graph_name,
        args.chip_rows, args.chip_cols,
        args.two5d_width, args.threeD_height,
        args.num_2p5d_units, args.num_3d_units,
        args.iterations, args.population_size,
        args.tsv_assignment_mode,
        seed=args.seed,
    )


if __name__ == "__main__":
    main()
