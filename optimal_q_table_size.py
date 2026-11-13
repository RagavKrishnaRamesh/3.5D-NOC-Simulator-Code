"""Sweep a state-row LRU cache for PSO + Q-learning on one 32-core graph.

Run the full experiment (51 capacities, including vanilla PSO)::

    python optimal_q_table_size.py

Run a small real-graph smoke experiment::

    python optimal_q_table_size.py --swarm-size 4 --iterations 3 --sizes 0 2 12

Outputs are metrics.csv, results.xlsx (with a dual-axis XY chart), settings.json,
and each capacity's best_particle.json. Results are checkpointed after every
completed run. No third-party dependencies or simulator are required.
"""

from __future__ import annotations

import argparse
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import csv
import gc
from html import escape
import json
from pathlib import Path
import sys
import time
import zipfile

import csv_to_excel_results as excel
import pso_with_only_ql as ql


pso = ql.pso
ROOT = Path(__file__).resolve().parent
DEFAULT_SIZES = tuple(range(0, 500_001, 10_000))
# Same topology used for 32-core graphs by run_all_mesh_graphs.py: 36 router
# slots, of which four carry padding/dummy cores rather than graph vertices.
TOPOLOGY = dict(chip_rows=3, chip_cols=3, two5d_width=2, threeD_height=2,
                num_2p5d_units=1, num_3d_units=1)
METRIC_COLUMNS = (
    "capacity_rows", "algorithm", "graph", "seed", "swarm_size",
    "iterations_completed", "runtime_seconds", "effective_fitness", "cost",
    "variance", "variance_up", "variance_down", "normalized_variance",
    "final_rows", "peak_rows", "stored_q_values", "q_updates",
    "policy_cache_hits", "policy_cache_misses", "policy_cache_hit_rate",
    "evictions", "q_total_reward", "fitness_evaluations", "workers",
    "total_router_slots",
)


class LRUQTable(OrderedDict):
    """Q rows compatible with ql.q_update_value, bounded by state-row count.

    Reads and updates refresh recency. Only insertion evicts. Policy hit/miss
    counts are recorded separately, exactly once per particle's Q decision;
    internal Bellman lookups do not inflate those statistics.
    """

    def __init__(self, capacity):
        if capacity < 1:
            raise ValueError("LRU capacity must be positive; zero uses vanilla PSO")
        super().__init__()
        self.capacity = capacity
        self.peak_rows = 0
        self.evictions = 0
        self.policy_hits = 0
        self.policy_misses = 0

    def get(self, key, default=None):
        if key not in self:
            return default
        return self[key]

    def __getitem__(self, key):
        value = super().__getitem__(key)
        self.move_to_end(key)
        return value

    def __setitem__(self, key, value):
        if key not in self and len(self) >= self.capacity:
            self.popitem(last=False)
            self.evictions += 1
        super().__setitem__(key, value)
        self.move_to_end(key)
        self.peak_rows = max(self.peak_rows, len(self))

    def setdefault(self, key, default=None):
        if key not in self:
            self[key] = default
        return self.get(key)

    def record_policy_lookup(self, state):
        if state in self:
            self.policy_hits += 1
        else:
            self.policy_misses += 1


@dataclass(frozen=True)
class ExperimentConfig:
    graph: str
    swarm_size: int = 1000
    iterations: int = 500
    seed: int = 10
    workers: int = 4
    tsv_assignment_mode: int = pso.TSV_ASSIGNMENT_RANDOM
    q_alpha: float = ql.Q_LEARNING_ALPHA
    q_gamma: float = ql.Q_LEARNING_GAMMA
    q_epsilon: float = ql.Q_LEARNING_EPSILON
    max_swaps: int = 8
    print_interval: int = 10


def select_graph(requested=None):
    if requested is not None:
        path = Path(requested)
        if not path.is_file():
            name = path.name
            if name.isdigit():
                name = f"Graph{name}"
            path = ROOT / "Graphs" / (name if name.endswith(".txt") else name + ".txt")
        candidates = [path]
    else:
        candidates = sorted((ROOT / "Graphs").glob("Graph*.txt"),
                            key=lambda path: (int(path.stem[5:])
                                              if path.stem[5:].isdigit() else sys.maxsize,
                                              path.name))
    for path in candidates:
        with path.open(encoding="utf-8") as handle:
            core_count = int(handle.readline().strip())
        if core_count == 32:
            return path.resolve()
    raise ValueError("A graph declaring exactly 32 cores is required")


def run_capacity(config, capacity, run_dir):
    """Use the existing PSO/QL primitives, with a true PSO-only zero baseline.

    The loop deliberately follows pso_with_only_ql.py. Early stopping is omitted
    so all capacities receive the same iteration budget. A shared worker count
    and evaluator are used for both algorithms. No DP or fitness memoization.
    """
    if capacity < 0:
        raise ValueError("Capacity cannot be negative")
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    table = LRUQTable(capacity) if capacity else None
    gc.collect()
    pso.RANDOM_SEED = config.seed
    pso.TSV_ASSIGNMENT_MODE = pso._validate_tsv_assignment_mode(config.tsv_assignment_mode)
    pso.random.seed(config.seed)
    start = time.perf_counter()
    layout, total_routers = pso.build_topology(**TOPOLOGY)
    edge_file = str(run_dir / "edges.txt")
    pso.create_edge_set(config.graph, edge_file)
    coordinates = pso.assign_router_coordinates(total_routers)
    pso.init_normalization_terms(config.graph, edge_file, TOPOLOGY["threeD_height"])
    executor = (ThreadPoolExecutor(max_workers=config.workers, thread_name_prefix="q-size")
                if config.workers > 1 else None)
    updates, total_reward = 0, 0.0
    try:
        particles = [pso.Particle3p5d(layout, coordinates, edge_file,
                                    list(range(total_routers)), evaluate_initial=False)
                     for _ in range(config.swarm_size)]
        ql.evaluate_particles(particles, layout, coordinates, edge_file, executor)
        personal_best = [particle.clone() for particle in particles]
        global_best = min(personal_best, key=lambda particle: particle.fitness_value).clone()
        for iteration in range(config.iterations):
            for index, particle in enumerate(particles):
                pso.update_particle(particle, personal_best[index], global_best,
                                    layout, coordinates, edge_file)
            ql.evaluate_particles(particles, layout, coordinates, edge_file, executor)
            global_best = ql._update_bests(particles, personal_best, global_best)
            if table is not None:
                transitions = []
                for index, particle in enumerate(particles):
                    state = ql.q_state_key(particle.state)
                    table.record_policy_lookup(state)
                    actions = ql.build_swap_actions(particle, personal_best[index], global_best,
                                                    layout, config.max_swaps)
                    actions = list(dict.fromkeys([*actions, *table.get(state, {})]))
                    action = ql.q_choose_action(table, state, actions, config.q_epsilon)
                    transitions.append((state, action, particle.fitness_value))
                    if action:
                        proposed = ql.apply_swap_action(particle.state, action, layout)
                        particle.state = pso.repair_particle_state(proposed, layout, coordinates,
                                                                  edge_file)
                ql.evaluate_particles(particles, layout, coordinates, edge_file, executor)
                for particle, (state, action, old_fitness) in zip(particles, transitions):
                    reward = old_fitness - particle.fitness_value
                    ql.q_update_value(table, state, action, reward,
                                      ql.q_state_key(particle.state), config.q_alpha, config.q_gamma,
                                      next_action_count=ql.q_action_count(particle.state,
                                                                        config.max_swaps))
                    updates += 1
                    total_reward += reward
                global_best = ql._update_bests(particles, personal_best, global_best)
            completed = iteration + 1
            if completed == 1 or completed == config.iterations or completed % config.print_interval == 0:
                print(f"  capacity={capacity:,} iteration={completed}/{config.iterations} "
                      f"fitness={global_best.fitness_value:.8f} "
                      f"rows={len(table) if table is not None else 0:,}", flush=True)
    finally:
        if executor is not None:
            executor.shutdown(wait=True)
    elapsed = time.perf_counter() - start
    decisions = config.swarm_size * config.iterations if capacity else 0
    metrics = dict(
        capacity_rows=capacity, algorithm="PSO_QL_LRU" if capacity else "PSO",
        graph=Path(config.graph).name, seed=config.seed, swarm_size=config.swarm_size,
        iterations_completed=config.iterations, runtime_seconds=elapsed,
        effective_fitness=global_best.fitness_value, cost=global_best.cost,
        variance=global_best.variance, variance_up=global_best.var_up,
        variance_down=global_best.var_down,
        normalized_variance=pso.normalized_variance_value(global_best.variance),
        final_rows=len(table) if table is not None else 0,
        peak_rows=table.peak_rows if table is not None else 0,
        stored_q_values=sum(len(row) for row in table.values()) if table is not None else 0,
        q_updates=updates, policy_cache_hits=table.policy_hits if table is not None else 0,
        policy_cache_misses=table.policy_misses if table is not None else 0,
        policy_cache_hit_rate=table.policy_hits / decisions if decisions else 0.0,
        evictions=table.evictions if table is not None else 0, q_total_reward=total_reward,
        fitness_evaluations=config.swarm_size * (1 + config.iterations * (2 if capacity else 1)),
        workers=config.workers, total_router_slots=total_routers,
    )
    # Export is outside the measured runtime and kept separate from pipeline outputs.
    pso.write_particle_file(str(run_dir / "best_particle.json"), config.graph,
                            **TOPOLOGY, best_particle_state=global_best.state,
                            chiplet_layout=layout, best_cost=global_best.cost,
                            final_eff_fit=global_best.fitness_value,
                            final_var=global_best.variance, final_var_up=global_best.var_up,
                            final_var_down=global_best.var_down, optimizer_metadata=metrics)
    return metrics


def chart_title(text):
    return ('<c:title><c:tx><c:rich><a:bodyPr/><a:lstStyle/><a:p><a:r>'
            f'<a:t>{escape(text)}</a:t></a:r></a:p></c:rich></c:tx>'
            '<c:overlay val="0"/></c:title>')


def chart_reference(column, values):
    points = ''.join(f'<c:pt idx="{index}"><c:v>{value}</c:v></c:pt>'
                     for index, value in enumerate(values))
    return (f'<c:numRef><c:f>Metrics!${column}$2:${column}${len(values) + 1}</c:f>'
            '<c:numCache><c:formatCode>General</c:formatCode>'
            f'<c:ptCount val="{len(values)}"/>{points}</c:numCache></c:numRef>')


def chart_xml(metrics):
    capacities = [row["capacity_rows"] for row in metrics]
    series = []
    for index, (name, field, color, x_axis, y_axis) in enumerate((
        ("Runtime (seconds)", "runtime_seconds", "2878B5", 10, 20),
        ("Effective fitness (lower is better)", "effective_fitness", "D95F02", 40, 30),
    )):
        column = excel.column_name(METRIC_COLUMNS.index(field) + 1)
        series.append(
            '<c:scatterChart><c:scatterStyle val="lineMarker"/><c:ser>'
            f'<c:idx val="{index}"/><c:order val="{index}"/>'
            f'<c:tx><c:v>{escape(name)}</c:v></c:tx>'
            f'<c:spPr><a:ln w="25400"><a:solidFill><a:srgbClr val="{color}"/>'
            '</a:solidFill></a:ln></c:spPr>'
            '<c:marker><c:symbol val="circle"/><c:size val="4"/></c:marker>'
            f'<c:xVal>{chart_reference("A", capacities)}</c:xVal>'
            f'<c:yVal>{chart_reference(column, [row[field] for row in metrics])}</c:yVal>'
            '<c:smooth val="0"/></c:ser>'
            f'<c:axId val="{x_axis}"/><c:axId val="{y_axis}"/></c:scatterChart>')
    axes = []
    for axis, cross, position, title, hidden in (
        (10, 20, "b", "Q-table capacity (state rows)", False),
        (20, 10, "l", "Runtime (seconds)", False),
        (40, 30, "b", "", True),
        (30, 40, "r", "Effective fitness (lower is better)", False),
    ):
        bounds = (f'<c:max val="{max(1, max(capacities))}"/><c:min val="0"/>'
                  if axis in (10, 40) else '')
        axes.append(
            f'<c:valAx><c:axId val="{axis}"/><c:scaling><c:orientation val="minMax"/>'
            f'{bounds}</c:scaling><c:delete val="{int(hidden)}"/>'
            f'<c:axPos val="{position}"/>{chart_title(title) if title else ""}'
            '<c:numFmt formatCode="0.######" sourceLinked="0"/>'
            '<c:majorTickMark val="out"/><c:minorTickMark val="none"/>'
            '<c:tickLblPos val="nextTo"/>'
            f'<c:crossAx val="{cross}"/><c:crosses val="{"max" if axis == 30 else "autoZero"}"/>'
            '<c:crossBetween val="midCat"/></c:valAx>')
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<c:chartSpace xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        '<c:chart>' + chart_title("Q-table capacity vs runtime and effective fitness") +
        '<c:plotArea><c:layout/>' + ''.join(series + axes) + '</c:plotArea>'
        '<c:legend><c:legendPos val="b"/><c:overlay val="0"/></c:legend>'
        '<c:plotVisOnly val="1"/><c:dispBlanksAs val="gap"/></c:chart></c:chartSpace>'
    )


def relationship_xml(kind, target):
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/{kind}" '
        f'Target="{target}"/></Relationships>'
    )


def write_workbook(path, metrics, settings):
    """Write native Excel cells and an editable scatter chart using OOXML."""
    if not metrics:
        raise ValueError("At least one completed capacity is needed for the workbook")
    sheets = [
        ("Metrics", [list(METRIC_COLUMNS)] + [[row[key] for key in METRIC_COLUMNS] for row in metrics]),
        ("Settings", [["Setting", "Value"]] + [
            [key, json.dumps(value) if isinstance(value, (dict, list, bool)) else value]
            for key, value in settings.items()]),
        ("Chart", [["Q-table capacity experiment"],
                   ["Blue: runtime (left axis); orange: effective fitness (right axis)."],
                   ["Capacity is a row limit; see Metrics for actual peak rows."],
                   ["Size 0 is vanilla PSO. Lower effective fitness is better."]]),
    ]
    types = excel.content_types_xml(sheets).replace('</Types>', (
        '<Override PartName="/xl/drawings/drawing1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.drawing+xml"/>'
        '<Override PartName="/xl/charts/chart1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.drawingml.chart+xml"/></Types>'))
    drawing = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<xdr:wsDr xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        '<xdr:twoCellAnchor><xdr:from><xdr:col>0</xdr:col><xdr:colOff>0</xdr:colOff>'
        '<xdr:row>6</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:from>'
        '<xdr:to><xdr:col>12</xdr:col><xdr:colOff>0</xdr:colOff>'
        '<xdr:row>35</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:to>'
        '<xdr:graphicFrame macro=""><xdr:nvGraphicFramePr>'
        '<xdr:cNvPr id="2" name="Q-table capacity chart"/><xdr:cNvGraphicFramePr/>'
        '</xdr:nvGraphicFramePr><xdr:xfrm><a:off x="0" y="0"/>'
        '<a:ext cx="0" cy="0"/></xdr:xfrm><a:graphic>'
        '<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/chart">'
        '<c:chart xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" r:id="rId1"/>'
        '</a:graphicData></a:graphic></xdr:graphicFrame><xdr:clientData/>'
        '</xdr:twoCellAnchor></xdr:wsDr>'
    )
    path = Path(path)
    temporary = path.with_suffix(".tmp.xlsx")
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in (
            ("[Content_Types].xml", types), ("_rels/.rels", excel.root_rels_xml()),
            ("xl/workbook.xml", excel.workbook_xml(sheets)),
            ("xl/_rels/workbook.xml.rels", excel.workbook_rels_xml(sheets)),
            ("xl/styles.xml", excel.styles_xml()),
            ("xl/drawings/drawing1.xml", drawing),
            ("xl/worksheets/_rels/sheet3.xml.rels", relationship_xml("drawing", "../drawings/drawing1.xml")),
            ("xl/drawings/_rels/drawing1.xml.rels", relationship_xml("chart", "../charts/chart1.xml")),
            ("xl/charts/chart1.xml", chart_xml(metrics)),
        ):
            archive.writestr(name, data)
        for index, (_, rows) in enumerate(sheets, 1):
            worksheet = excel.worksheet_xml(rows)
            if index == 1:
                worksheet = worksheet.replace('<cols>', (
                    '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" '
                    'topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
                    '</sheetView></sheetViews><cols>'))
                worksheet = worksheet.replace('</worksheet>',
                                              f'<autoFilter ref="A1:Y{len(rows)}"/></worksheet>')
            if index == 3:
                worksheet = worksheet.replace('</worksheet>', '<drawing r:id="rId1"/></worksheet>')
            archive.writestr(f"xl/worksheets/sheet{index}.xml", worksheet)
    temporary.replace(path)


def save_results(output_dir, metrics, settings):
    temporary = output_dir / "metrics.tmp.csv"
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=METRIC_COLUMNS)
        writer.writeheader()
        writer.writerows(metrics)
    temporary.replace(output_dir / "metrics.csv")
    write_workbook(output_dir / "results.xlsx", metrics, settings)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--graph", help="32-core graph path/name/number; default first such graph (Graph4)")
    parser.add_argument("--swarm-size", type=int, default=1000)
    parser.add_argument("--iterations", type=int, default=500)
    parser.add_argument("--sizes", nargs="+", type=int, help="Override the default 0, 10000, ..., 500000 sweep")
    parser.add_argument("--seed", type=int, default=10)
    parser.add_argument("--parallel-workers", type=int, default=None)
    parser.add_argument("--tsv-assignment-mode", type=int, choices=(0, 1), default=pso.TSV_ASSIGNMENT_RANDOM)
    parser.add_argument("--q-alpha", type=float, default=ql.Q_LEARNING_ALPHA)
    parser.add_argument("--q-gamma", type=float, default=ql.Q_LEARNING_GAMMA)
    parser.add_argument("--q-epsilon", type=float, default=ql.Q_LEARNING_EPSILON)
    parser.add_argument("--max-swaps", type=int, default=8)
    parser.add_argument("--print-interval", type=int, default=10)
    parser.add_argument("--output-dir", type=Path, help="New directory for this experiment's outputs")
    parser.add_argument("--dry-run", action="store_true", help="Print the graph and sweep without running optimizers")
    args = parser.parse_args(argv)
    if min(args.swarm_size, args.iterations, args.max_swaps, args.print_interval) < 1:
        parser.error("swarm-size, iterations, max-swaps and print-interval must be positive")
    if not (0 < args.q_alpha <= 1 and 0 <= args.q_gamma <= 1 and 0 <= args.q_epsilon <= 1):
        parser.error("Require 0 < q-alpha <= 1 and 0 <= q-gamma/q-epsilon <= 1")
    args.sizes = sorted(set(args.sizes if args.sizes is not None else DEFAULT_SIZES))
    if not args.sizes or min(args.sizes) < 0:
        parser.error("sizes must be non-negative row counts")
    try:
        args.graph = select_graph(args.graph)
        args.parallel_workers = ql._resolve_workers(args.parallel_workers, args.swarm_size)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    return args


def main(argv=None):
    args = parse_args(argv)
    config = ExperimentConfig(str(args.graph), args.swarm_size, args.iterations, args.seed,
                              args.parallel_workers, args.tsv_assignment_mode,
                              args.q_alpha, args.q_gamma, args.q_epsilon, args.max_swaps,
                              args.print_interval)
    settings = dict(
        **asdict(config), topology=TOPOLOGY, graph_core_count=32,
        capacities=args.sizes, maximum_possible_rows=args.swarm_size * args.iterations,
        early_stopping=False, dp=False, fitness_cache=False,
        eviction_policy="LRU state rows; reads and updates refresh recency",
        zero_capacity="Vanilla PSO; no Q actions, Q evaluation pass, hashes or Q updates",
        runtime_scope="Wall seconds: setup, initialization, optimization, worker shutdown; excludes exports",
        cache_hit_scope="One state lookup per Q action decision; excludes Bellman/update lookups",
        fitness="Existing fitness_value / effective_fitness; lower is better",
        comparison="Fixed iteration budget; QL uses an extra evaluation pass versus vanilla PSO",
        timing_order="Ascending capacity; single run per capacity with the same seed",
        created_utc=datetime.now(timezone.utc).isoformat(),
    )
    print(f"Graph: {args.graph.name} (32 cores); swarm={config.swarm_size}, "
          f"iterations={config.iterations}, seed={config.seed}, workers={config.workers}")
    print(f"Capacities ({len(args.sizes)}): {', '.join(f'{size:,}' for size in args.sizes)}")
    print("Size 0: vanilla PSO. Positive sizes: PSO + QL with LRU state rows. Early stopping: off.")
    if args.dry_run:
        return 0
    output_dir = (args.output_dir or ROOT / "BatchOutputs" / "optimal_q_table_size" /
                  datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f_UTC")).resolve()
    # A new directory prevents accidentally mixing or replacing prior measurements.
    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir / "settings.json").write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    print(f"Output: {output_dir}", flush=True)
    metrics = []
    for index, capacity in enumerate(args.sizes, 1):
        print(f"[{index}/{len(args.sizes)}] Starting capacity {capacity:,}", flush=True)
        row = run_capacity(config, capacity, output_dir / f"capacity_{capacity}")
        metrics.append(row)
        save_results(output_dir, metrics, settings)
        print(f"  Saved: {row['runtime_seconds']:.3f}s, fitness={row['effective_fitness']:.8f}, "
              f"peak rows={row['peak_rows']:,}, evictions={row['evictions']:,}", flush=True)
    print(f"Excel metrics and chart: {output_dir / 'results.xlsx'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
