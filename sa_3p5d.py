import argparse
import re
import sys
import math
import random
import time
import json
import os
from copy import deepcopy
try:
    from edge_set_creation import create_edge_set
except Exception:
    create_edge_set = None
INTRACHIP_LATENCY = 1.0
INTERPOSER_LATENCY = 1.0
VL_LATENCY = 1.0
MUTATION_STAGNATION = 50
MIN_INTERPOSER_GAP = 1
CHIP_ROWS = None
CHIP_COLS = None
BASE_ROWS = None
BASE_COLS = None
BASE_INTERPOSER_ENABLED = True
W_FACTOR = 0.5
base_icrt = {}
INF = float('inf')
tsv_assignment_global = {}
current_chromosome = None
CHIPLET_NAME_TO_INDEX = {}
MAX_COMM_COST = 1.0
VAR_COMM_SQ = 1.0
RANDOM_SEED = None
TSV_ASSIGNMENT_ELEVATOR_FIRST = 0
TSV_ASSIGNMENT_REDELF_RANDOM = 1
TSV_ASSIGNMENT_REDELF = TSV_ASSIGNMENT_REDELF_RANDOM
TSV_ASSIGNMENT_RANDOM = TSV_ASSIGNMENT_REDELF_RANDOM
TSV_ASSIGNMENT_MODE = TSV_ASSIGNMENT_REDELF_RANDOM

class SAParams:

    # Sets up default simulated annealing parameters.
    def __init__(self):
        self.MAX_STEPS = 200000
        self.INIT_TEMP = 10.0
        self.MIN_TEMP = 1e-05
        self.COOLING_RATE = 0.999972
        self.TSV_MUTATION_PROB = 0.1
        self.ATTACH_MUTATION_PROB = 0.05
        self.REVERSE_MUTATION_PROB = 0.2
        self.NO_SA_RUNS = 1
        self.USE_FITNESS_TERMS = True
        self.STAGNATION_PATIENCE = 100

# Registers a vertical link slot on the base interposer.
def add_base_vl(x, y, t, start_id, end_id, chiplet_name, interposer=None, enforce_bounds=True, enforce_gap=True):
    if enforce_bounds and not (0 <= x < BASE_COLS and 0 <= y < BASE_ROWS):
        raise ValueError(f'VL ({x},{y}) out of bounds for {BASE_COLS}x{BASE_ROWS}')
    if (x, y) in base_icrt:
        raise ValueError(f'Duplicate VL at ({x},{y})')
    if enforce_gap:
        for bx, by in base_icrt.keys():
            if max(abs(x - bx), abs(y - by)) <= MIN_INTERPOSER_GAP:
                raise ValueError(
                    f'VL ({x},{y}) too close to existing stack at ({bx},{by}); '
                    f'need at least {MIN_INTERPOSER_GAP} empty base slot(s) of spacing'
                )
    for meta in base_icrt.values():
        s, e = meta['range']
        if not (end_id < s or start_id > e):
            raise ValueError(f'ID range {start_id}-{end_id} overlaps with existing {s}-{e}')
    entry = {'type': t, 'chiplet': chiplet_name, 'range': (start_id, end_id)}
    if t == '2.5d' and interposer is not None:
        entry['interposer'] = interposer
    base_icrt[x, y] = entry

# Creates the metadata for a single 2.5D interposer.
def build_2p5d_interposer(rows, cols, chiplet_specs):
    chiplets = {}
    used_ranges = []
    for name, (ax, ay), (s, e) in chiplet_specs:
        if not (0 <= ax < cols and 0 <= ay < rows):
            raise ValueError(f'{name} attach ({ax},{ay}) out of bounds for {cols}x{rows}')
        for ps, pe in used_ranges:
            if not (e < ps or s > pe):
                raise ValueError(f'{name} range {s}-{e} overlaps with {ps}-{pe}')
        used_ranges.append((s, e))
        chiplets[name] = {'attach_coord': (ax, ay), 'range': (s, e)}
    return {'rows': rows, 'cols': cols, 'chiplets': chiplets}


def _pack_footprints_on_square(footprints, side, gap):
    placements = {}
    x = 0
    y = 0
    row_h = 0
    for fp in footprints:
        key = fp['key']
        w = fp['w']
        h = fp['h']
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
    if not footprints:
        return (0, {})
    max_w = max((fp['w'] for fp in footprints))
    max_h = max((fp['h'] for fp in footprints))
    total_area = sum((fp['w'] * fp['h'] for fp in footprints))
    side = max(max_w, max_h, int(math.ceil(math.sqrt(total_area))))
    while True:
        placements = _pack_footprints_on_square(footprints, side, gap)
        if placements is not None:
            return (side, placements)
        side += 1


def _compute_square_local_2p5d_plan(two5d_width, gap):
    if two5d_width <= 0:
        return (0, {})
    local_footprints = []
    for c in range(two5d_width):
        local_footprints.append({
            'key': c,
            'w': CHIP_COLS,
            'h': CHIP_ROWS,
        })
    return _compute_square_base_plan(local_footprints, gap)

# Builds the chiplet layout and base interposer grid.
def build_topology(chip_rows, chip_cols, two5d_width, threeD_height, num_2p5d_units, num_3d_units):
    global CHIP_ROWS, CHIP_COLS, BASE_ROWS, BASE_COLS, base_icrt, CHIPLET_NAME_TO_INDEX
    global BASE_INTERPOSER_ENABLED
    CHIP_ROWS = chip_rows
    CHIP_COLS = chip_cols
    base_icrt = {}
    routers_per_2d = CHIP_ROWS * CHIP_COLS
    chiplet_layout = []
    next_id = 0
    local_2p5d_side = 0
    local_2p5d_placements = {}
    if num_2p5d_units > 0:
        local_2p5d_side, local_2p5d_placements = _compute_square_local_2p5d_plan(two5d_width, MIN_INTERPOSER_GAP)
    num_slots = num_3d_units + num_2p5d_units
    if num_slots <= 0:
        raise ValueError('At least one chiplet unit is required')
    BASE_INTERPOSER_ENABLED = num_slots > 1
    footprints = []
    for i in range(num_3d_units):
        footprints.append({
            'key': ('3d', i),
            'w': CHIP_COLS,
            'h': CHIP_ROWS,
        })
    for i in range(num_2p5d_units):
        footprints.append({
            'key': ('2.5d', i),
            'w': local_2p5d_side,
            'h': local_2p5d_side,
        })
    if BASE_INTERPOSER_ENABLED:
        side, placements = _compute_square_base_plan(footprints, MIN_INTERPOSER_GAP)
        BASE_ROWS = side
        BASE_COLS = side
    else:
        BASE_ROWS = 0
        BASE_COLS = 0
        placements = {footprints[0]['key']: (0, 0, footprints[0]['w'], footprints[0]['h'])}
    for i in range(num_3d_units):
        no_levels = threeD_height
        no_routers = routers_per_2d * no_levels
        start_id = next_id
        end_id = next_id + no_routers - 1
        px, py, pw, ph = placements[('3d', i)]
        if BASE_INTERPOSER_ENABLED:
            vlx = px + pw - 1
            vly = py + ph - 1
        else:
            vlx, vly = (0, 0)
        add_base_vl(
            vlx,
            vly,
            '3d',
            start_id,
            end_id,
            f'3D_{i}',
            enforce_bounds=BASE_INTERPOSER_ENABLED,
            enforce_gap=BASE_INTERPOSER_ENABLED,
        )
        chiplet_layout.append({'type': '3d', 'name': f'3D_{i}', 'no_routers': no_routers, 'no_levels': no_levels, 'vl_coord': (vlx, vly), 'range': (start_id, end_id)})
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
            chip_specs.append((f'C{i}_{c}', (att_x, att_y), (cs, ce)))
            next_id += routers_per_2d
        interposer = build_2p5d_interposer(local_rows, local_cols, chip_specs)
        start_id = chip_specs[0][2][0]
        end_id = chip_specs[-1][2][1]
        px, py, pw, ph = placements[('2.5d', i)]
        if BASE_INTERPOSER_ENABLED:
            vlx = px + pw - 1
            vly = py + ph - 1
        else:
            vlx, vly = (0, 0)
        add_base_vl(
            vlx,
            vly,
            '2.5d',
            start_id,
            end_id,
            f'2p5D_{i}',
            interposer=interposer,
            enforce_bounds=BASE_INTERPOSER_ENABLED,
            enforce_gap=BASE_INTERPOSER_ENABLED,
        )
        chiplet_layout.append({'type': '2.5d', 'name': f'2p5D_{i}', 'no_routers': routers_per_2d * two5d_width, 'vl_coord': (vlx, vly), 'range': (start_id, end_id), 'interposer': interposer})
    CHIPLET_NAME_TO_INDEX = {chip['name']: idx for idx, chip in enumerate(chiplet_layout)}
    return (chiplet_layout, next_id)

# Finds which base stack owns a router id.
def _find_stack_for_router(global_router_id):
    for (bx, by), meta in base_icrt.items():
        s, e = meta['range']
        if s <= global_router_id <= e:
            return ((bx, by), meta)
    return (None, None)

# Gets local 3D coordinates for a global router id.
def _local_coords_3d(global_router_id, start_id, levels):
    size = CHIP_ROWS * CHIP_COLS
    idx = global_router_id - start_id
    layer = idx // size
    within = idx % size
    ly = within // CHIP_COLS
    lx = within % CHIP_COLS
    return (lx, ly, layer)

# Gets local 2D coordinates for a global router id.
def _local_coords_2d(global_router_id, start_id):
    idx = global_router_id - start_id
    ly = idx // CHIP_COLS
    lx = idx % CHIP_COLS
    return (lx, ly)

# Resolves router details inside a 2.5D complex.
def _locate_in_2p5d(global_router_id, base_coord, meta_2p5d):
    interposer = meta_2p5d['interposer']
    cols = interposer['cols']
    rows = interposer['rows']
    chiplets = interposer['chiplets']
    for name, spec in chiplets.items():
        s, e = spec['range']
        if s <= global_router_id <= e:
            lx, ly = _local_coords_2d(global_router_id, s)
            chiplet_to_local_vl = spec['attach_coord']
            local_br = (cols - 1, rows - 1)
            global_vl = base_coord
            return {'type': '2.5d', 'chiplet': name, 'local_coords': (lx, ly), 'chiplet_to_local_interposer_vl': chiplet_to_local_vl, 'local_interposer_bottom_right': local_br, 'local_interposer_to_global_vl': global_vl}
    raise ValueError(f'Router {global_router_id} not found in any 2.5D chiplet')

# Maps a router id to its chiplet type and coordinates.
def locate_router(global_router_id):
    base_coord, meta = _find_stack_for_router(global_router_id)
    if meta is None:
        raise ValueError(f'Global router {global_router_id} not mapped in base_icrt')
    t = meta['type']
    s, e = meta['range']
    if t == '3d':
        levels = (e - s + 1) // (CHIP_ROWS * CHIP_COLS)
        lx, ly, lz = _local_coords_3d(global_router_id, s, levels)
        return {'type': '3d', 'chiplet': meta['chiplet'], 'local_coords': (lx, ly, lz), 'base_attach_coord': base_coord}
    if t == '2.5d':
        return _locate_in_2p5d(global_router_id, base_coord, meta)
    raise ValueError(f"Unsupported type '{t}'")

# Returns start/end/levels metadata for a 3D chiplet.
def _3d_chiplet_params(router_id):
    base_coord, meta = _find_stack_for_router(router_id)
    if meta is None or meta['type'] != '3d':
        raise ValueError(f'Router {router_id} not in a 3D chiplet')
    start_id, end_id = meta['range']
    routers_per_level = CHIP_ROWS * CHIP_COLS
    levels = (end_id - start_id + 1) // routers_per_level
    return (start_id, end_id, levels, routers_per_level)

# Walks through TSV assignments one level at a time.
def _resolve_assigned_tsv_router(current_router, start_id, end_id, routers_per_level):
    tsv_r = tsv_assignment_global.get(current_router)
    if tsv_r is None or not (start_id <= tsv_r <= end_id):
        return None
    _, _, current_z = _local_coords_3d(current_router, start_id, (end_id - start_id + 1) // routers_per_level)
    layer_offset = start_id + current_z * routers_per_level
    local_idx = tsv_r - layer_offset
    if not (0 <= local_idx < routers_per_level):
        return None
    _, meta = _find_stack_for_router(current_router)
    if meta is None:
        return None
    chip_idx = CHIPLET_NAME_TO_INDEX.get(meta['chiplet'])
    if chip_idx is None:
        return None
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
        tsv_r = _resolve_assigned_tsv_router(current_router, start_id, end_id, routers_per_level)
        if tsv_r is None:
            return (INF, None)
        tx, ty, tz = _local_coords_3d(tsv_r, start_id, levels)
        if tz != cz:
            return (INF, None)
        cost += (abs(cx - tx) + abs(cy - ty)) * INTRACHIP_LATENCY
        next_z = tz + direction
        if next_z < 0 or next_z >= levels:
            return (INF, None)
        current_router = start_id + next_z * routers_per_level + ty * CHIP_COLS + tx
        cost += VL_LATENCY
    return (cost, current_router)

# Computes hop cost when staying within one 3D chiplet.
def _same_chiplet_3d_cost(src, dest, s_info, d_info):
    start_id, end_id, levels, routers_per_level = _3d_chiplet_params(src)
    sx, sy, sz = _local_coords_3d(src, start_id, levels)
    dx, dy, dz = _local_coords_3d(dest, start_id, levels)
    if sz == dz:
        return (abs(sx - dx) + abs(sy - dy)) * INTRACHIP_LATENCY
    cost, current_router = _walk_3d_to_level(src, dz, start_id, end_id, levels, routers_per_level)
    if current_router is None:
        return INF
    cx, cy, _ = _local_coords_3d(current_router, start_id, levels)
    cost += (abs(cx - dx) + abs(cy - dy)) * INTRACHIP_LATENCY
    return cost

# Calculates cost from a 3D router up to the base.
def _3d_to_base_cost(router_id, info):
    start_id, end_id, levels, routers_per_level = _3d_chiplet_params(router_id)
    sx, sy, sz = _local_coords_3d(router_id, start_id, levels)
    chip_name = info['chiplet']
    chip_idx = CHIPLET_NAME_TO_INDEX[chip_name]
    base_attach_router = current_chromosome[chip_idx][3]
    ax = base_attach_router % CHIP_COLS
    ay = base_attach_router // CHIP_COLS
    cost = 0.0
    current_router = router_id
    if sz != 0:
        cost, current_router = _walk_3d_to_level(router_id, 0, start_id, end_id, levels, routers_per_level)
        if current_router is None:
            return INF
    cx, cy, _ = _local_coords_3d(current_router, start_id, levels)
    cost += (abs(cx - ax) + abs(cy - ay)) * INTRACHIP_LATENCY
    cost += VL_LATENCY
    return cost

# Calculates cost from the base down to a 3D router.
def _base_to_3d_cost(router_id, info):
    start_id, end_id, levels, routers_per_level = _3d_chiplet_params(router_id)
    dx, dy, dz = _local_coords_3d(router_id, start_id, levels)
    chip_name = info['chiplet']
    chip_idx = CHIPLET_NAME_TO_INDEX[chip_name]
    base_attach_router = current_chromosome[chip_idx][3]
    ax = base_attach_router % CHIP_COLS
    ay = base_attach_router // CHIP_COLS
    attach_router = start_id + ay * CHIP_COLS + ax
    cost = VL_LATENCY
    current_router = attach_router
    if dz != 0:
        walk_cost, current_router = _walk_3d_to_level(attach_router, dz, start_id, end_id, levels, routers_per_level)
        if current_router is None:
            return INF
        cost += walk_cost
    cx, cy, _ = _local_coords_3d(current_router, start_id, levels)
    cost += (abs(cx - dx) + abs(cy - dy)) * INTRACHIP_LATENCY
    return cost

# Calculates cost from a 2.5D router up to the base.
def _2p5d_to_base_cost(info):
    lx, ly = info['local_coords']
    att = info['chiplet_to_local_interposer_vl']
    complex_name = base_icrt[info['local_interposer_to_global_vl']]['chiplet']
    complex_idx = CHIPLET_NAME_TO_INDEX[complex_name]
    base_attach_router = current_chromosome[complex_idx][1]
    interposer = base_icrt[info['local_interposer_to_global_vl']]['interposer']
    rows = interposer['rows']
    cols = interposer['cols']
    local_area = rows * cols
    if local_area <= 0:
        return INF
    base_attach_router %= local_area
    ax = base_attach_router % cols
    ay = base_attach_router // cols
    src_to_br = (abs(CHIP_COLS - 1 - lx) + abs(CHIP_ROWS - 1 - ly)) * INTRACHIP_LATENCY
    br_to_li = VL_LATENCY
    li_to_attach = (abs(att[0] - ax) + abs(att[1] - ay)) * INTERPOSER_LATENCY
    li_attach_to_base = VL_LATENCY
    return src_to_br + br_to_li + li_to_attach + li_attach_to_base

# Calculates cost from the base down to a 2.5D router.
def _base_to_2p5d_cost(info):
    return _2p5d_to_base_cost(info)

# Computes pairwise hop cost between two routers.
def calculate_count(src_router, dest_router):
    s = locate_router(src_router)
    d = locate_router(dest_router)
    st = s['type']
    dt = d['type']
    if st == '2.5d' and dt == '2.5d':
        s_base = s['local_interposer_to_global_vl']
        d_base = d['local_interposer_to_global_vl']
        sx, sy = s['local_coords']
        dx, dy = d['local_coords']
        if s_base == d_base:
            if s['chiplet'] == d['chiplet']:
                return (abs(sx - dx) + abs(sy - dy)) * INTRACHIP_LATENCY
            src_to_br = (abs(CHIP_COLS - 1 - sx) + abs(CHIP_ROWS - 1 - sy)) * INTRACHIP_LATENCY
            dest_to_br = (abs(CHIP_COLS - 1 - dx) + abs(CHIP_ROWS - 1 - dy)) * INTRACHIP_LATENCY
            s_br_loc = s['chiplet_to_local_interposer_vl']
            d_br_loc = d['chiplet_to_local_interposer_vl']
            br_to_br = (abs(s_br_loc[0] - d_br_loc[0]) + abs(s_br_loc[1] - d_br_loc[1])) * INTERPOSER_LATENCY
            return src_to_br + dest_to_br + br_to_br + 2 * VL_LATENCY
        cost_src_to_base = _2p5d_to_base_cost(s)
        cost_dest_from_base = _base_to_2p5d_cost(d)
        base_to_base = (abs(s_base[0] - d_base[0]) + abs(s_base[1] - d_base[1])) * INTERPOSER_LATENCY
        return cost_src_to_base + base_to_base + cost_dest_from_base
    if st == '3d' and dt == '3d':
        if s['chiplet'] == d['chiplet']:
            return _same_chiplet_3d_cost(src_router, dest_router, s, d)
        cost_src_to_base = _3d_to_base_cost(src_router, s)
        cost_dest_from_base = _base_to_3d_cost(dest_router, d)
        s_base = s['base_attach_coord']
        d_base = d['base_attach_coord']
        base_to_base = (abs(s_base[0] - d_base[0]) + abs(s_base[1] - d_base[1])) * INTERPOSER_LATENCY
        return cost_src_to_base + base_to_base + cost_dest_from_base
    if st == '3d' and dt == '2.5d':
        cost_src_to_base = _3d_to_base_cost(src_router, s)
        c_base = d['local_interposer_to_global_vl']
        s_base = s['base_attach_coord']
        base_walk = (abs(s_base[0] - c_base[0]) + abs(s_base[1] - c_base[1])) * INTERPOSER_LATENCY
        cost_dest_from_base = _base_to_2p5d_cost(d)
        return cost_src_to_base + base_walk + cost_dest_from_base
    if st == '2.5d' and dt == '3d':
        cost_src_to_base = _2p5d_to_base_cost(s)
        s_base = s['local_interposer_to_global_vl']
        d_base = d['base_attach_coord']
        base_walk = (abs(s_base[0] - d_base[0]) + abs(s_base[1] - d_base[1])) * INTERPOSER_LATENCY
        cost_dest_from_base = _base_to_3d_cost(dest_router, d)
        return cost_src_to_base + base_walk + cost_dest_from_base
    raise ValueError(f'Unsupported type combination: {st} -> {dt}')

# Builds an edge list if no helper is available.
def _fallback_create_edge_set(adj_file, edge_set_file):
    with open(adj_file, 'r') as f:
        n = int(f.readline().strip())
        rows = []
        for _ in range(n):
            parts = f.readline().strip().split()
            if len(parts) < n:
                parts = [p for p in re.split('[,\\s]+', ' '.join(parts)) if p]
            rows.append(parts)
    with open(edge_set_file, 'w') as out:
        for i in range(n):
            for j in range(n):
                if i == j:
                    continue
                if j >= len(rows[i]):
                    continue
                val = rows[i][j]
                if isinstance(val, str) and val.upper() == 'INF':
                    continue
                try:
                    bw = float(val)
                except Exception:
                    continue
                if bw <= 0 or math.isinf(bw) or math.isnan(bw):
                    continue
                out.write(f'{i} {j} {bw}\n')

# Computes normalization constants for cost and variance.
def init_normalization_terms(graph_name, edge_set_file, threeD_height):
    global MAX_COMM_COST, VAR_COMM_SQ
    input_graph = graph_input_path(graph_name)
    with open(input_graph, 'r') as f:
        no_of_cores = int(f.readline().strip())
    max_bw = 0.0
    total_bw = 0.0
    with open(edge_set_file, 'r') as f:
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
    max_hops = (CHIP_ROWS - 1 + CHIP_COLS - 1) * threeD_height + (threeD_height - 1) + (BASE_ROWS - 1 + BASE_COLS - 1)
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
    if not raw.lower().endswith('.txt'):
        candidates.append(f'{raw}.txt')
    base = os.path.basename(raw)
    candidates.append(os.path.join('Graphs', base))
    if not base.lower().endswith('.txt'):
        candidates.append(os.path.join('Graphs', f'{base}.txt'))
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    return os.path.join('Graphs', f'{base}.txt' if not base.lower().endswith('.txt') else base)


def edge_set_output_path(graph_name):
    base = os.path.splitext(os.path.basename(str(graph_name)))[0]
    os.makedirs('EdgeSet', exist_ok=True)
    return os.path.join('EdgeSet', f'edge_set_{base}.txt')


def _validate_tsv_assignment_mode(mode):
    mode = int(mode)
    if mode not in (TSV_ASSIGNMENT_ELEVATOR_FIRST, TSV_ASSIGNMENT_REDELF_RANDOM):
        raise ValueError(
            'TSV assignment mode must be 0 (elevator_first) or 1 (redelf_random)'
        )
    return mode


def _tsv_assignment_mode_name(mode=None):
    mode = TSV_ASSIGNMENT_MODE if mode is None else _validate_tsv_assignment_mode(mode)
    if mode == TSV_ASSIGNMENT_ELEVATOR_FIRST:
        return 'elevator_first'
    return 'redelf_random'


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
        raise ValueError('tsv_local_indices cannot be empty')
    return max(tsv_local_indices, key=lambda t: (t // CHIP_COLS, t % CHIP_COLS))


def _select_elevator_first_tsv_local_index(router_local_idx, candidate_local_indices):
    return _nearest_tsv_local_index(router_local_idx, candidate_local_indices)


def _select_redelf_random_tsv_local_index(router_local_idx, desired_tsv_local_indices, opposite_tsv_local_indices=None):
    if not desired_tsv_local_indices:
        raise ValueError('desired_tsv_local_indices cannot be empty')

    desired = sorted(set(desired_tsv_local_indices))
    opposite = sorted(set(desired if opposite_tsv_local_indices is None else opposite_tsv_local_indices))
    southeast_candidates = [t for t in desired if _is_south_or_due_east(t, router_local_idx)]
    selected_by_b1 = bool(southeast_candidates)

    if selected_by_b1:
        chosen = random.choice(southeast_candidates)
    else:
        chosen = _redelf_pivot_local_index(desired)

    if selected_by_b1 and chosen != router_local_idx and opposite:
        opposite_pivot = _redelf_pivot_local_index(opposite)
        if _is_south_or_due_east(chosen, opposite_pivot):
            chosen = _redelf_pivot_local_index(desired)

    return chosen


def _select_tsv_local_index(router_local_idx, candidate_local_indices):
    if not candidate_local_indices:
        raise ValueError('candidate_local_indices cannot be empty')
    if TSV_ASSIGNMENT_MODE == TSV_ASSIGNMENT_ELEVATOR_FIRST:
        return _select_elevator_first_tsv_local_index(router_local_idx, candidate_local_indices)
    if TSV_ASSIGNMENT_MODE == TSV_ASSIGNMENT_REDELF_RANDOM:
        return _select_redelf_random_tsv_local_index(router_local_idx, candidate_local_indices)
    raise ValueError(f'Unsupported TSV assignment mode: {TSV_ASSIGNMENT_MODE}')


# Creates a random chromosome for every chiplet.
def _build_initial_tsv_assignment(start_id, no_levels, routers_per_level, tsv_placement):
    local_tsvs = [idx for idx, bit in enumerate(tsv_placement) if bit == 1]
    assignment = []
    for layer in range(no_levels):
        layer_offset = start_id + layer * routers_per_level
        for local_idx in range(routers_per_level):
            if local_tsvs:
                chosen = _select_tsv_local_index(local_idx, local_tsvs)
                assignment.append(layer_offset + chosen)
            else:
                assignment.append(layer_offset + local_idx)
    return assignment


def _max_tsv_count(routers_per_level):
    return min(routers_per_level, max(2, math.floor(0.25 * routers_per_level)))


def _rebuild_legal_tsv_placement(selected_positions, routers_per_level, target_count=None):
    if routers_per_level <= 0:
        return []

    def _placement_compatible(a, b):
        ax = a % CHIP_COLS
        ay = a // CHIP_COLS
        bx = b % CHIP_COLS
        by = b // CHIP_COLS

        # Match the Tabu placement rule: reject only same-row / same-column
        # neighbors within a 1-cell neighborhood. Diagonals remain legal.
        if ax == bx and abs(ay - by) <= 1:
            return False
        if ay == by and abs(ax - bx) <= 1:
            return False
        return True

    desired_count = max(2, len(selected_positions)) if target_count is None else int(target_count)
    desired_count = min(_max_tsv_count(routers_per_level), desired_count, routers_per_level)

    preferred = [idx for idx in dict.fromkeys(selected_positions) if 0 <= idx < routers_per_level]
    others = [idx for idx in range(routers_per_level) if idx not in preferred]
    best_chosen = []

    attempts = max(8, routers_per_level * 2)
    for attempt in range(attempts):
        pref_order = preferred[:]
        other_order = others[:]
        random.shuffle(pref_order)
        random.shuffle(other_order)

        if attempt == 0:
            candidates = pref_order + other_order
        else:
            candidates = other_order + pref_order

        chosen = []
        for idx in candidates:
            if all(_placement_compatible(idx, placed) for placed in chosen):
                chosen.append(idx)
                if len(chosen) == desired_count:
                    break

        if len(chosen) > len(best_chosen):
            best_chosen = chosen
        if len(best_chosen) == desired_count:
            break

    placement = [0] * routers_per_level
    for idx in best_chosen:
        placement[idx] = 1
    return placement


def _seed_initial_tsv_placement(routers_per_level):
    candidates = list(range(routers_per_level))
    random.shuffle(candidates)
    max_tsvs = _max_tsv_count(routers_per_level)
    if max_tsvs < 2:
        raise ValueError(
            f'Cannot seed 2 legal TSVs on a {CHIP_ROWS}x{CHIP_COLS} layer '
            f'with {routers_per_level} routers per level'
        )
    target = random.randint(2, max_tsvs)
    return _rebuild_legal_tsv_placement(candidates, routers_per_level, target_count=target)


def generate_chromosome_3p5d(chiplet_layout, tsv_list):
    total_routers = sum((chip['no_routers'] for chip in chiplet_layout))
    global_core_perm = random.sample(range(total_routers), total_routers)
    chromosome = []
    idx = 0
    for chip in chiplet_layout:
        chip_type = chip['type']
        no_routers = chip['no_routers']
        core_to_router = global_core_perm[idx:idx + no_routers]
        idx += no_routers
        if chip_type == '3d':
            no_levels = chip['no_levels']
            routers_per_level = no_routers // no_levels
            tsv_placement = _seed_initial_tsv_placement(routers_per_level)
            tsv_assignment = _build_initial_tsv_assignment(chip['range'][0], no_levels, routers_per_level, tsv_placement)
            base_attach_router = random.randrange(routers_per_level)
            chip_gene = [core_to_router, tsv_placement, tsv_assignment, base_attach_router]
        elif chip_type == '2.5d':
            local_rows = chip['interposer']['rows']
            local_cols = chip['interposer']['cols']
            local_area = local_rows * local_cols
            if local_area <= 0:
                raise ValueError(f"Invalid local interposer size for {chip['name']}: {local_rows}x{local_cols}")
            base_attach_router = random.randrange(local_area)
            chip_gene = [core_to_router, base_attach_router]
        else:
            raise ValueError(f'Unknown chiplet type: {chip_type}')
        chromosome.append(chip_gene)
    return chromosome

# Repairs the core-to-router permutation.
def fix_core_to_router_mapping_3p5d(chromosome, chiplet_layout):
    total_routers = sum((chip['no_routers'] for chip in chiplet_layout))
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
        n = chip['no_routers']
        chromosome[chip_idx][0] = flat[idx:idx + n]
        idx += n
    return chromosome

# Checks TSV placement bits for one 3D chiplet.
def _validate_tsv_placement_single_3d(tsv_placement, router_coordinates, base_offset, routers_per_level):
    selected_positions = [idx for idx, bit in enumerate(tsv_placement) if bit == 1]
    return _rebuild_legal_tsv_placement(selected_positions, routers_per_level)

# Validates TSV placement for all 3D chiplets.
def validate_tsv_placement_3p5d(chromosome, chiplet_layout, router_coordinates):
    for idx, chip in enumerate(chiplet_layout):
        no_routers = chip['no_routers']
        if chip['type'] == '3d':
            no_levels = chip['no_levels']
            routers_per_level = no_routers // no_levels
            core_to_router, tsv_placement, tsv_assignment, base_attach = chromosome[idx]
            tsv_placement = _validate_tsv_placement_single_3d(
                tsv_placement,
                router_coordinates,
                base_offset=chip['range'][0],
                routers_per_level=routers_per_level,
            )
            chromosome[idx][1] = tsv_placement
    return chromosome

# Assigns coordinates to every router id.
def assign_router_coordinates(total_routers):
    coords = {}
    for (bx, by), meta in base_icrt.items():
        s, e = meta['range']
        t = meta['type']
        if t == '3d':
            levels = (e - s + 1) // (CHIP_ROWS * CHIP_COLS)
            for rid in range(s, e + 1):
                lx, ly, lz = _local_coords_3d(rid, s, levels)
                coords[rid] = (lx, ly, lz)
        else:
            for rid in range(s, e + 1):
                lx, ly = _local_coords_2d(rid, s)
                coords[rid] = (lx, ly, 0)
    if len(coords) != total_routers:
        raise RuntimeError('Router coordinate map incomplete')
    return coords

# Counts how many communications stay inside one 3D chiplet but cross layers.
def _count_vertical_communications_3d_chip(core_to_router, router_coordinates, edge_set_file, chip_range):
    start_id, end_id = chip_range
    vertical = 0

    with open(edge_set_file, 'r') as f:
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

            if not (start_id <= src_router < end_id and start_id <= dest_router < end_id):
                continue

            if router_coordinates[src_router][2] != router_coordinates[dest_router][2]:
                vertical += 1

    return vertical


# Repairs TSV assignments inside one chiplet.
def _validate_tsv_assignment_single_3d(tsv_placement, no_routers, no_levels, core_to_router, router_coordinates, edge_set_file, base_offset, routers_per_level):
    tsv_assignment = [0] * no_routers

    for layer in range(no_levels):
        layer_offset = base_offset + layer * routers_per_level
        tsv_list = [layer_offset + i for i, b in enumerate(tsv_placement) if b == 1]
        fallback = layer_offset
        if tsv_list:
            routers = list(range(layer_offset, layer_offset + routers_per_level))
            if TSV_ASSIGNMENT_MODE == TSV_ASSIGNMENT_REDELF_RANDOM:
                random.shuffle(routers)

            for r in routers:
                candidate_local_indices = [tsv - layer_offset for tsv in tsv_list]
                chosen = layer_offset + _select_tsv_local_index(
                    r - layer_offset,
                    candidate_local_indices,
                )
                local_idx = r - base_offset
                tsv_assignment[local_idx] = chosen
        else:
            for r in range(layer_offset, layer_offset + routers_per_level):
                local_idx = r - base_offset
                tsv_assignment[local_idx] = fallback
    return tsv_assignment

# Validates TSV assignments across all chiplets.
def validate_tsv_assignment_3p5d(chromosome, chiplet_layout, router_coordinates, edge_set_file):
    for idx, chip in enumerate(chiplet_layout):
        no_routers = chip['no_routers']
        if chip['type'] == '3d':
            no_levels = chip['no_levels']
            routers_per_level = no_routers // no_levels
            core_to_router, tsv_placement, _, _ = chromosome[idx]
            tsv_assignment = _validate_tsv_assignment_single_3d(
                tsv_placement,
                no_routers,
                no_levels,
                core_to_router,
                router_coordinates,
                edge_set_file,
                base_offset=chip['range'][0],
                routers_per_level=routers_per_level,
            )
            chromosome[idx][2] = tsv_assignment
    return chromosome

# Maps each core to its global router.
def build_core_to_router_map(chromosome, chiplet_layout):
    mapping = {}
    for idx, chip in enumerate(chiplet_layout):
        start_id = chip['range'][0]
        core_to_router = chromosome[idx][0]
        for local_r, core in enumerate(core_to_router):
            mapping[core] = start_id + local_r
    return mapping

# Builds the global TSV assignment lookup.
def build_global_tsv_assignment(chromosome, chiplet_layout):
    assignment = {}
    for idx, chip in enumerate(chiplet_layout):
        if chip['type'] == '3d':
            start_id = chip['range'][0]
            _, _, local_tsv, _ = chromosome[idx]
            for local_r, tsv_r in enumerate(local_tsv):
                assignment[start_id + local_r] = tsv_r
    return assignment

# Calculates total communication cost for a chromosome.
def cost_function_3p5d(chromosome, chiplet_layout, edge_set_file):
    global tsv_assignment_global
    global current_chromosome
    current_chromosome = chromosome
    core_to_router_map = build_core_to_router_map(chromosome, chiplet_layout)
    tsv_assignment_global = build_global_tsv_assignment(chromosome, chiplet_layout)
    total_cost = 0.0
    with open(edge_set_file, 'r') as f:
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


def _trace_3d_vertical_pairs(start_router, target_level, chip):
    """
    Return the ordered vertical TSV links traversed inside one 3D chiplet when
    moving from start_router to target_level.
    """
    start_id, end_id = chip['range']
    no_levels = chip['no_levels']
    routers_per_level = chip['no_routers'] // no_levels
    current_router = start_router
    traversed_pairs = []

    while True:
        _, _, current_level = _local_coords_3d(current_router, start_id, no_levels)
        if current_level == target_level:
            break

        direction = 1 if target_level > current_level else -1
        tsv_r = _resolve_assigned_tsv_router(current_router, start_id, end_id, routers_per_level)
        if tsv_r is None:
            break

        tx, ty, tz = _local_coords_3d(tsv_r, start_id, no_levels)
        if tz != current_level:
            break

        next_level = tz + direction
        if next_level < 0 or next_level >= no_levels:
            break

        neighbor_router = start_id + next_level * routers_per_level + ty * CHIP_COLS + tx
        traversed_pairs.append((tsv_r, neighbor_router))
        current_router = neighbor_router

    return traversed_pairs


# Computes TSV up/down traffic variance.
def tsv_variance_3p5d(chromosome, chiplet_layout, router_coordinates, edge_set_file):
    global tsv_assignment_global
    global current_chromosome
    current_chromosome = chromosome
    core_to_router_map = build_core_to_router_map(chromosome, chiplet_layout)
    tsv_assignment = build_global_tsv_assignment(chromosome, chiplet_layout)
    tsv_assignment_global = tsv_assignment
    router_to_chip = {}
    for idx, chip in enumerate(chiplet_layout):
        if chip['type'] == '3d':
            start_id, end_id = chip['range']
            for rid in range(start_id, end_id + 1):
                router_to_chip[rid] = idx
    tsv_traffic = {}
    for chip_idx, chip in enumerate(chiplet_layout):
        if chip['type'] != '3d':
            continue
        no_routers = chip['no_routers']
        no_levels = chip['no_levels']
        start_id, end_id = chip['range']
        routers_per_level = no_routers // no_levels
        tsv_place = chromosome[chip_idx][1]
        for layer in range(no_levels - 1):
            base_offset = start_id + layer * routers_per_level
            for i, bit in enumerate(tsv_place):
                if bit == 1:
                    lower = base_offset + i
                    upper = lower + routers_per_level
                    tsv_traffic[lower, upper] = 0.0
                    tsv_traffic[upper, lower] = 0.0
    with open(edge_set_file, 'r') as f:
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

            if src_chip_idx is not None and src_chip_idx == dest_chip_idx:
                src_level = router_coordinates[src_router][2]
                dest_level = router_coordinates[dest_router][2]
                if src_level == dest_level:
                    continue

                chip = chiplet_layout[src_chip_idx]
                traversed_pairs = _trace_3d_vertical_pairs(src_router, dest_level, chip)
                for pair in traversed_pairs:
                    if pair in tsv_traffic:
                        tsv_traffic[pair] += bw
                continue

            # Cross-chiplet traffic still uses source-side descent and/or
            # destination-side ascent inside 3D stacks, so include it here.
            if src_chip_idx is not None:
                src_level = router_coordinates[src_router][2]
                if src_level != 0:
                    chip = chiplet_layout[src_chip_idx]
                    traversed_pairs = _trace_3d_vertical_pairs(src_router, 0, chip)
                    for pair in traversed_pairs:
                        if pair in tsv_traffic:
                            tsv_traffic[pair] += bw

            if dest_chip_idx is not None:
                dest_level = router_coordinates[dest_router][2]
                if dest_level != 0:
                    chip = chiplet_layout[dest_chip_idx]
                    traversed_pairs = _trace_3d_vertical_pairs(dest_router, 0, chip)
                    for lower_pair in traversed_pairs:
                        reversed_pair = (lower_pair[1], lower_pair[0])
                        if reversed_pair in tsv_traffic:
                            tsv_traffic[reversed_pair] += bw
    up_vals, down_vals = ([], [])
    for (a, b), v in tsv_traffic.items():
        if router_coordinates[a][2] < router_coordinates[b][2]:
            up_vals.append(v)
        else:
            down_vals.append(v)

    # Returns the variance of a list of values.
    def _variance(lst):
        if not lst:
            return 0.0
        m = sum(lst) / len(lst)
        return sum(((x - m) ** 2 for x in lst)) / len(lst)
    return (_variance(up_vals), _variance(down_vals))

# Combines cost and variance into effective fitness.
def fitness_terms_3p5d(chromosome, chiplet_layout, router_coordinates, edge_set_file):
    cost = cost_function_3p5d(chromosome, chiplet_layout, edge_set_file)
    var_up, var_down = tsv_variance_3p5d(chromosome, chiplet_layout, router_coordinates, edge_set_file)
    variance = max(var_up, var_down)
    if MAX_COMM_COST <= 0.0:
        norm_cost = cost
    else:
        norm_cost = W_FACTOR * cost / MAX_COMM_COST
    if VAR_COMM_SQ <= 0.0:
        norm_var = variance
    else:
        norm_var = (1.0 - W_FACTOR) * variance / VAR_COMM_SQ
    effective_fitness = norm_cost + norm_var
    return (effective_fitness, cost, variance, var_up, var_down)

# Flattens the chromosome mapping into one list.
def _flatten_core_to_router(chromosome, chiplet_layout):
    flat = []
    for chip_idx, chip in enumerate(chiplet_layout):
        flat.extend(chromosome[chip_idx][0])
    return flat

# Restores a flat mapping back into the chromosome.
def _unflatten_core_to_router(flat, chromosome, chiplet_layout):
    idx = 0
    for chip_idx, chip in enumerate(chiplet_layout):
        n = chip['no_routers']
        chromosome[chip_idx][0] = flat[idx:idx + n]
        idx += n

# Applies a neighbor mutation and repairs it.
def perturb_chromosome_sa(chromosome, chiplet_layout, router_coordinates, edge_set_file, sa_params):
    child = deepcopy(chromosome)
    r = random.random()
    if r < sa_params.ATTACH_MUTATION_PROB:
        chip_idx = random.randrange(len(chiplet_layout))
        chip = chiplet_layout[chip_idx]
        if chip['type'] == '3d':
            no_routers = chip['no_routers']
            routers_per_level = no_routers // chip['no_levels']
            child[chip_idx][3] = random.randrange(routers_per_level)
        else:
            local_rows = chip['interposer']['rows']
            local_cols = chip['interposer']['cols']
            local_area = local_rows * local_cols
            child[chip_idx][1] = random.randrange(local_area)
    elif r < sa_params.ATTACH_MUTATION_PROB + sa_params.TSV_MUTATION_PROB:
        three_d_indices = [i for i, c in enumerate(chiplet_layout) if c['type'] == '3d']
        if three_d_indices:
            chip_idx = random.choice(three_d_indices)
            no_routers = chiplet_layout[chip_idx]['no_routers']
            routers_per_level = no_routers // chiplet_layout[chip_idx]['no_levels']
            bit = random.randrange(routers_per_level)
            child[chip_idx][1][bit] = 1 - child[chip_idx][1][bit]
            child[chip_idx][2] = [0] * no_routers
    else:
        flat = _flatten_core_to_router(child, chiplet_layout)
        n = len(flat)
        if n >= 2:
            if random.random() < sa_params.REVERSE_MUTATION_PROB and n >= 4:
                i = random.randrange(0, n - 1)
                j = random.randrange(i + 1, n)
                flat[i:j] = reversed(flat[i:j])
            else:
                i, j = random.sample(range(n), 2)
                flat[i], flat[j] = (flat[j], flat[i])
        _unflatten_core_to_router(flat, child, chiplet_layout)
    child = fix_core_to_router_mapping_3p5d(child, chiplet_layout)
    child = validate_tsv_placement_3p5d(child, chiplet_layout, router_coordinates)
    child = validate_tsv_assignment_3p5d(child, chiplet_layout, router_coordinates, edge_set_file)
    return child

# Selects the energy metric based on settings.
def _energy(chromosome, chiplet_layout, router_coordinates, edge_set_file, sa_params):
    if sa_params.USE_FITNESS_TERMS:
        eff, *_ = fitness_terms_3p5d(chromosome, chiplet_layout, router_coordinates, edge_set_file)
        return eff
    return cost_function_3p5d(chromosome, chiplet_layout, edge_set_file)

# Estimates the starting temperature for SA.
def _estimate_initial_temperature(current, current_e, chiplet_layout, router_coordinates, edge_set_file, sa_params, samples=40, target_accept=0.8):
    if not (0.0 < target_accept < 1.0):
        return sa_params.INIT_TEMP
    uphill_deltas = []
    sample_count = max(8, int(samples))
    for _ in range(sample_count):
        cand = perturb_chromosome_sa(current, chiplet_layout, router_coordinates, edge_set_file, sa_params)
        cand_e = _energy(cand, chiplet_layout, router_coordinates, edge_set_file, sa_params)
        delta = cand_e - current_e
        if math.isfinite(delta) and delta > 0:
            uphill_deltas.append(delta)
    if not uphill_deltas:
        return sa_params.INIT_TEMP
    avg_delta = sum(uphill_deltas) / len(uphill_deltas)
    temp = -avg_delta / math.log(target_accept)
    if not math.isfinite(temp) or temp <= 0.0:
        return sa_params.INIT_TEMP
    return temp

# Runs simulated annealing for the 3.5D topology.
def run_sa_3p5d(graph_name, chip_rows, chip_cols, two5d_width, threeD_height, num_2p5d_units, num_3d_units, iterations, population_size, sa_params=None, tsv_assignment_mode=TSV_ASSIGNMENT_RANDOM, seed=None):
    if sa_params is None:
        sa_params = SAParams()
    sa_params.MAX_STEPS = iterations
    global RANDOM_SEED, TSV_ASSIGNMENT_MODE
    seed_value = int(time.time()) if seed is None else int(seed)
    RANDOM_SEED = seed_value
    TSV_ASSIGNMENT_MODE = _validate_tsv_assignment_mode(tsv_assignment_mode)
    random.seed(seed_value)
    print(f'Using random seed: {seed_value}')
    print(f'Using TSV assignment mode: {_tsv_assignment_mode_name()}')
    start_time = time.time()
    chiplet_layout, total_routers = build_topology(chip_rows, chip_cols, two5d_width, threeD_height, num_2p5d_units, num_3d_units)
    input_graph = graph_input_path(graph_name)
    edge_set_file = edge_set_output_path(graph_name)
    if create_edge_set is not None:
        create_edge_set(input_graph, edge_set_file)
    else:
        _fallback_create_edge_set(input_graph, edge_set_file)
    router_coordinates = assign_router_coordinates(total_routers)
    init_normalization_terms(graph_name, edge_set_file, threeD_height)
    tsv_list = list(range(total_routers))
    init_pool = []
    pool_n = max(1, int(population_size))
    for _ in range(pool_n):
        chrom = generate_chromosome_3p5d(chiplet_layout, tsv_list)
        chrom = fix_core_to_router_mapping_3p5d(chrom, chiplet_layout)
        chrom = validate_tsv_placement_3p5d(chrom, chiplet_layout, router_coordinates)
        chrom = validate_tsv_assignment_3p5d(chrom, chiplet_layout, router_coordinates, edge_set_file)
        init_pool.append(chrom)
    current = min(init_pool, key=lambda c: _energy(c, chiplet_layout, router_coordinates, edge_set_file, sa_params))
    current_e = _energy(current, chiplet_layout, router_coordinates, edge_set_file, sa_params)
    best = deepcopy(current)
    best_e = current_e
    T = _estimate_initial_temperature(current, current_e, chiplet_layout, router_coordinates, edge_set_file, sa_params)
    if T <= 0:
        T = sa_params.INIT_TEMP
    initial_T = T
    stall_count = 0
    best_snapshot = best_e
    for step in range(sa_params.MAX_STEPS):
        cand = perturb_chromosome_sa(current, chiplet_layout, router_coordinates, edge_set_file, sa_params)
        cand_e = _energy(cand, chiplet_layout, router_coordinates, edge_set_file, sa_params)
        delta = cand_e - current_e
        if delta < 0 or random.random() < math.exp(-delta / max(T, 1e-12)):
            current = cand
            current_e = cand_e
            if current_e < best_e:
                best = deepcopy(current)
                best_e = current_e
        if best_e < best_snapshot:
            best_snapshot = best_e
            stall_count = 0
        else:
            stall_count += 1
        allow_early_stop = (
            (step + 1) >= max(50, sa_params.STAGNATION_PATIENCE)
            and T <= max(sa_params.MIN_TEMP * 10.0, initial_T * 0.25)
        )
        if allow_early_stop and stall_count >= sa_params.STAGNATION_PATIENCE:
            print(f'Early stopping at iteration {step + 1} after {sa_params.STAGNATION_PATIENCE} stagnant iterations without improvement.')
            break
        T *= sa_params.COOLING_RATE
        if T < sa_params.MIN_TEMP:
            break
        if sa_params.MAX_STEPS <= 20000 or (step + 1) % 200 == 0:
            if sa_params.USE_FITNESS_TERMS:
                _, cost, var, var_up, var_down = fitness_terms_3p5d(best, chiplet_layout, router_coordinates, edge_set_file)
                print(f'Iteration {step + 1}: Best Fitness = {best_e:.6f} | Cost={cost:.6f} | Var={var:.6f} | T={T:.6g}')
            else:
                print(f'Iteration {step + 1}: Best Cost = {best_e:.6f}')
    end_time = time.time()
    if sa_params.USE_FITNESS_TERMS:
        eff, cost, var, var_up, var_down = fitness_terms_3p5d(best, chiplet_layout, router_coordinates, edge_set_file)
        best_cost = cost
    else:
        best_cost = best_e
        var_up, var_down = tsv_variance_3p5d(best, chiplet_layout, router_coordinates, edge_set_file)
        var = max(var_up, var_down)
    print('\n=== 3.5D SA Result ===')
    print(f'Graph:         {graph_name}')
    print(f'Total routers: {total_routers}')
    print(f'Best cost:     {best_cost:.6f}')
    print(f'TSV var up:    {var_up:.6f}')
    print(f'TSV var down:  {var_down:.6f}')
    print(f'TSV var max:   {var:.6f}')
    print(f'Real time:     {end_time - start_time:.2f} s')
    print('\nBest Chromosome (by chiplet):')
    for idx, chip in enumerate(chiplet_layout):
        if chip['type'] == '3d':
            core_to_router, tsv_place, tsv_assign, base_attach = best[idx]
            print(f"  {chip['name']} (3D): VL={chip['vl_coord']}, range={chip['range']}")
            print(f'    Core->Router: {core_to_router}')
            print(f'    TSV place:    {tsv_place}')
            print(f'    TSV assign:   {tsv_assign}')
            print(f'    Base attach router (bottom layer): {base_attach}')
        else:
            core_to_router, base_attach = best[idx]
            print(f"  {chip['name']} (2.5D): VL={chip['vl_coord']}, range={chip['range']}")
            print(f'    Core->Router: {core_to_router}')
            print(f'    Base attach router (local interposer): {base_attach}')

    particle_path = particle_output_path(graph_name)
    write_particle_file(
        particle_path,
        graph_name,
        chip_rows, chip_cols,
        two5d_width, threeD_height,
        num_2p5d_units, num_3d_units,
        best,
        chiplet_layout,
        best_cost,
        best_e if sa_params.USE_FITNESS_TERMS else None,
        var,
        var_up,
        var_down,
    )

    return (best, best_cost)


def particle_output_path(graph_name):
    match = re.search(r'(\d+)$', graph_name)
    if match and graph_name.lower().startswith('graph'):
        return os.path.join('Particles', f'SA_Particle{match.group(1)}.txt')
    safe = re.sub(r'[^A-Za-z0-9_.-]+', '_', graph_name.strip()) or 'graph'
    return os.path.join('Particles', f'SA_Particle_{safe}.txt')


def _coord_convention(rows, cols):
    return {
        'origin': 'top_left',
        'indexing': '0_based',
        'axis_direction': {
            'x': 'left_to_right',
            'y': 'top_to_bottom',
        },
        'order': 'row_major',
        'router_index_formula': 'router_index = y * cols + x',
        'inverse_formula': {
            'x': 'router_index % cols',
            'y': 'router_index // cols',
        },
        'grid_shape': {
            'rows': int(rows),
            'cols': int(cols),
        },
        'top_left_coord': [0, 0],
        'bottom_right_coord': [int(cols) - 1, int(rows) - 1],
    }


def _serialize_local_interposer(interposer):
    if not isinstance(interposer, dict):
        return None
    out = {
        'rows': int(interposer.get('rows', 0)),
        'cols': int(interposer.get('cols', 0)),
        'chiplets': {},
    }
    chiplets = interposer.get('chiplets')
    if isinstance(chiplets, dict):
        for name, spec in chiplets.items():
            if not isinstance(spec, dict):
                continue
            attach = spec.get('attach_coord', (0, 0))
            r0, r1 = spec.get('range', (0, -1))
            out['chiplets'][str(name)] = {
                'attach_coord': [int(attach[0]), int(attach[1])],
                'range': [int(r0), int(r1)],
            }
    return out


def _build_simple_particle_entry(chip, gene):
    entry = {
        'type': chip['type'],
        'name': chip['name'],
        'vl_coord': list(chip['vl_coord']),
        'range': list(chip['range']),
        'no_routers': int(chip['no_routers']),
    }

    if chip['type'] == '3d':
        core_to_router, tsv_place, tsv_assign, base_attach = gene
        entry.update({
            'no_levels': int(chip['no_levels']),
            'base_attach_router': int(base_attach),
            'core_to_router': [int(v) for v in core_to_router],
            'tsv_placement': [int(v) for v in tsv_place],
            'tsv_assignment': [int(v) for v in tsv_assign],
        })
    else:
        core_to_router, base_attach = gene
        entry.update({
            'base_attach_router': int(base_attach),
            'core_to_router': [int(v) for v in core_to_router],
        })
        interposer = _serialize_local_interposer(chip.get('interposer'))
        if interposer is not None:
            entry['interposer'] = interposer

    return entry


def write_particle_file(path, graph_name, chip_rows, chip_cols, two5d_width, threeD_height, num_2p5d_units, num_3d_units, best_chromosome, chiplet_layout, best_cost, final_eff_fit, final_var, final_var_up, final_var_down):
    out_dir = os.path.dirname(path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    data = {
        'graph': graph_name,
        'seed': RANDOM_SEED,
        'best_cost': best_cost,
        'effective_fitness': final_eff_fit,
        'variance': final_var,
        'variance_up': final_var_up,
        'variance_down': final_var_down,
        'params': {
            'chip_rows': chip_rows,
            'chip_cols': chip_cols,
            'two5d_width': two5d_width,
            'threeD_height': threeD_height,
            'num_2p5d_units': num_2p5d_units,
            'num_3d_units': num_3d_units,
            'tsv_assignment_mode': int(TSV_ASSIGNMENT_MODE),
            'tsv_assignment_mode_name': _tsv_assignment_mode_name(),
        },
        'topology_hints': {
            'interposer_gap': MIN_INTERPOSER_GAP,
            'chiplet_order': 'all_3d_then_all_2p5d',
            'base_interposer_enabled': BASE_INTERPOSER_ENABLED,
            'base_shape': 'square' if BASE_INTERPOSER_ENABLED else 'none',
            'local_2p5d_shape': 'square' if num_2p5d_units > 0 else 'none',
        },
        'chromosome_structure': {
            '3d_gene': [
                'core_to_router',
                'tsv_placement',
                'tsv_assignment',
                'base_attach_router',
            ],
            '2p5d_gene': [
                'core_to_router',
                'base_attach_router',
            ],
        },
        'chromosome': best_chromosome,
        'coordinate_conventions': {
            'router_indexing_inside_each_2d_chiplet': _coord_convention(chip_rows, chip_cols),
            'vl_router_coordinates_note': (
                'VL-related router coordinates use 0-based row-major indexing: '
                '(0,0) is top-left and (cols-1, rows-1) is bottom-right.'
            ),
        },
        'chiplets': [],
    }

    if BASE_INTERPOSER_ENABLED and BASE_ROWS > 0 and BASE_COLS > 0:
        data['base'] = {
            'rows': BASE_ROWS,
            'cols': BASE_COLS,
        }

    for idx, chip in enumerate(chiplet_layout):
        data['chiplets'].append(_build_simple_particle_entry(chip, best_chromosome[idx]))

    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)
        f.write('\n')

# Parses CLI inputs and launches the optimizer.
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
        help="TSV assignment mode: 0=elevator_first, 1=redelf_random",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for SA. Omit to use the current system time.",
    )
    args = parser.parse_args()
    run_sa_3p5d(
        args.graph_name,
        args.chip_rows,
        args.chip_cols,
        args.two5d_width,
        args.threeD_height,
        args.num_2p5d_units,
        args.num_3d_units,
        args.iterations,
        args.population_size,
        tsv_assignment_mode=args.tsv_assignment_mode,
        seed=args.seed,
    )
if __name__ == '__main__':
    main()
