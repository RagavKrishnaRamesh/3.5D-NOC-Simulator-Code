# Full Pipeline Usage

This repo runs a full NoC optimization and simulation flow:

1. Run an optimizer: `GA`, `PSO`, `PSO_DP`, `PSO_QL`, `PSO_DP_QL`, `SA`, `ASA`, or `QL`
2. Write the best particle to `Particles/`
3. Generate YAML topology in `YAML/`
4. Generate traffic table in `TrafficTable/`
5. Run `noxim`
6. Append results to an algorithm-specific run-start CSV, for example `RESULTS_random_sa_20260919_143000.csv`

## Requirements

- Python 3
- The repo's Python dependencies available in your environment
- `bin/noxim` and `bin/power.yaml`
- On Windows, use `--use-wsl` if `bin/noxim` is a Linux binary

The current Windows setup needs `--use-wsl`; otherwise the simulator can fail with:

```text
[WinError 193] %1 is not a valid Win32 application
```

## Full Pipeline Command

Run from the repo root:

```powershell
python run_pipeline.py --algorithm GA --graph 4 --chiprows 2 --chipcols 2 --two5dwidth 4 --threedheight 4 --num2p5d 1 --num3d 1 --population 200 --iterations 1000 --use-wsl
```

General form:

```powershell
python run_pipeline.py --algorithm <GA|PSO|PSO_DP|PSO_QL|PSO_DP_QL|SA|ASA|QL> --graph <graph_number_or_path> --chiprows <rows> --chipcols <cols> --two5dwidth <width> --threedheight <height> --num2p5d <count> --num3d <count> --population <count> --iterations <count> --use-wsl
```

You can also use the dotted aliases:

```powershell
--2.5dwidth <width>
--num2.5d <count>
```

## Dimension Arguments

The dimension arguments are:

```text
chiprows chipcols two5dwidth threedheight num2p5d num3d
```

Example:

```text
2 2 4 4 1 1
```

means:

- each 2D layer/chiplet is `2 x 2`
- each 3D chiplet has height `4`
- each 2.5D complex contains `4` 2D chiplets
- run with `1` 2.5D complex
- run with `1` 3D chiplet

The code supports non-square chiplets such as `4 x 2` or `2 x 4`.

## Common Examples

GA, Graph 4, mixed 3D + 2.5D:

```powershell
python run_pipeline.py --algorithm GA --graph 4 --chiprows 2 --chipcols 2 --two5dwidth 4 --threedheight 4 --num2p5d 1 --num3d 1 --population 200 --iterations 1000 --use-wsl
```

GA, Graph 4, 3D-only with `4 x 4 x 2`:

```powershell
python run_pipeline.py --algorithm GA --graph 4 --chiprows 4 --chipcols 4 --two5dwidth 2 --threedheight 2 --num2p5d 0 --num3d 1 --population 200 --iterations 1000 --use-wsl
```

GA, Graph 4, 3D-only reference dimensions `4 x 2 x 4`:

```powershell
python run_pipeline.py --algorithm GA --graph 4 --chiprows 4 --chipcols 2 --two5dwidth 2 --threedheight 4 --num2p5d 0 --num3d 1 --population 200 --iterations 1000 --use-wsl
```

PSO example:

```powershell
python run_pipeline.py --algorithm PSO --graph 4 --chiprows 2 --chipcols 2 --two5dwidth 4 --threedheight 4 --num2p5d 1 --num3d 1 --population 200 --iterations 1000 --use-wsl
```

SA example:

```powershell
python run_pipeline.py --algorithm SA --graph 4 --chiprows 2 --chipcols 2 --two5dwidth 4 --threedheight 4 --num2p5d 1 --num3d 1 --population 200 --iterations 1000 --use-wsl
```

ASA example:

```powershell
python run_pipeline.py --algorithm ASA --graph 4 --chiprows 2 --chipcols 2 --two5dwidth 4 --threedheight 4 --num2p5d 1 --num3d 1 --population 200 --iterations 1000 --use-wsl
```

Q-learning example:

```powershell
python run_pipeline.py --algorithm QL --graph 4 --chiprows 2 --chipcols 2 --two5dwidth 4 --threedheight 4 --num2p5d 1 --num3d 1 --population 200 --iterations 1000 --use-wsl
```

## Optional Arguments

Use a fixed optimizer seed:

```powershell
--seed 10
```

Use a fixed simulator seed:

```powershell
--sim-seed 10
```

Select TSV assignment mode:

```powershell
--mode elevator
--mode random
```

`--mode random` applies REDELF Ruleset B and chooses randomly among
valid south-or-due-east elevator candidates. `--mode elevator` uses the
baseline elevator-first selection without REDELF south/east or pivot rules.
The older `redelf_random` and `elevator_first` spellings remain accepted, as
do numeric modes: `0` for `elevator`, `1` for `random`.

Append to the same algorithm's results CSV across runs or days by passing its original start time:

```powershell
--results-start-time 20260919_143000
```

Treat graph edges as directed when generating the traffic table:

```powershell
--directed
```

Use custom simulator or power-model paths:

```powershell
--noxim bin/noxim --power bin/power.yaml
```

## Output Files

For Graph 4 with GA, the pipeline writes:

```text
Particles/GA_Particle4.txt
YAML/GA_Particle4.yaml
TrafficTable/GA_Particle4-TrafficTable.txt
LOG/GA_Particle4.log
RESULTS_<mode>_<algorithm>_<YYYYMMDD_HHMMSS>.csv
```

`<mode>` is `random` or `elevator`; `<algorithm>` is `ga`, `pso`, `pso_dp`,
`pso_ql`, `pso_dp_ql`, `sa`, `asa`, or `ql`. Each algorithm has its own CSV.

The CSV includes optimizer metrics and simulator metrics, including:

- `comm_cost` (sum of edge bandwidth times `hop_countij`)
- `Variance`
- `Variance Up`
- `Variance Down`
- `Effective Fitness`
- `Global average delay (cycles)`
- `Network throughput (flits/cycle)`
- `Total energy (J)`
- `Total received packets`

The start time is captured before optimization. The mesh batch runner passes
the same start time to every graph and algorithm, including runs after midnight.
All graphs for an algorithm append to its CSV. If a CSV is locked by Excel,
close it and rerun with the same `--results-start-time`; the pipeline does not
create a second results file for that algorithm.

## Run Simulator Only

If a particle already exists, run only YAML generation, traffic-table generation, and simulation:

```powershell
python run_simulator.py Particles/GA_Particle4.txt Graphs/Graph4.txt --use-wsl
```

or with graph number:

```powershell
python run_simulator.py GA_Particle4.txt 4 --use-wsl
```

For 3D-only particles without a base interposer, the simulator path automatically switches traffic ID space to `particle` when needed.

## Troubleshooting

If `noxim` fails on Windows with `WinError 193`, rerun with:

```powershell
--use-wsl
```

If the graph has missing cores or the particle has invalid mappings, check that:

- `chiprows * chipcols * threedheight * num3d + chiprows * chipcols * two5dwidth * num2p5d` matches the graph core count
- the graph file exists in `Graphs/`
- the optimizer wrote the expected particle file in `Particles/`

Use help for the latest CLI options:

```powershell
python run_pipeline.py --help
python run_simulator.py --help
```

## Threaded PSO variants

`PSO_DP` and `PSO_QL` use `ThreadPoolExecutor` for particle fitness evaluation.
They default to `min(cpu_count, population, 4)` workers. Set
`--parallel-workers 4` explicitly, or set the `PSO_WORKERS` environment variable.
One worker runs sequentially. Particle movement, repair, random draws, best-state
updates, fitness-cache writes and Q-table updates stay on the coordinator thread.
Particle-dependent routing state is isolated per evaluating thread; topology is
fixed for the duration of a run. Run one optimization at a time per module.
CPython's GIL can limit CPU speedup even when several worker threads are used.

| Algorithm | Implementation | DP / memoization | Q-learning |
|---|---|---|---|
| `PSO_DP` | `pso_with_only_dp.py` | Fitness-state, hop-distance and TSV-path reuse | None |
| `PSO_QL` | `pso_with_only_ql.py` | None; every particle is evaluated | Particle-hash states; concrete swap-sequence actions |

Here DP refers to the existing memoization of repeated fitness and path
subproblems. It does not replace the PSO search with an exact placement solver.
The pre-existing `PSO_DP_QL` remains available as a separate legacy combination.

Run either optimizer directly, without invoking Noxim:

```powershell
python pso_with_only_dp.py Graph3 2 2 1 2 0 1 100 100 0 --seed 10 --parallel-workers 4
python pso_with_only_ql.py Graph3 2 2 1 2 0 1 100 100 0 --seed 10 --parallel-workers 4
```

The positional arguments are `graph rows cols two5d_width threeD_height
num_2p5d num_3d iterations population tsv_mode`. TSV mode `0` is Elevator-First
assignment; `1` is REDELF random assignment. This TSV setting is distinct from
Noxim's YAML `routing_algorithm`.

Outputs are separate:

```text
Particles/PSO_DP_Particle3.txt
Particles/PSO_QL_Particle3.txt
Particles/PSO_QL_Particle3.qtable.json
```

PSO+QL first makes the regular inertia/cognitive/social PSO move and evaluates
it. Q-learning then selects an additional ordered sequence of swaps. Each swap
is `(target, chip_index, i, j)`: `("mapping", -1, i, j)` swaps positions in the
flattened core mapping; `("tsv", chip_index, i, j)` swaps TSV placement bits.
Actions contain up to `--max-swaps` swaps, default 8. The empty sequence keeps
the PSO proposal unchanged. Candidate sequences come from personal/global best
differences, the previous velocity and random swaps; previously learned
sequences are also available when the same state is revisited. Q-table action
keys are the actual sequences, rather than names of these proposal strategies.

The state is a stable SHA-256 hash of the complete repaired chromosome:
mapping, TSV placement, TSV assignment and attachment points. A nonempty action
is followed by the existing validity repair. Reward is the decrease in effective
fitness caused by the Q move, measured after repair. The PSO move's improvement
is evaluated separately and is not credited to the Q action. Updates use:

```text
Q(s,a) += alpha * (reward + gamma * max Q(s',a') - Q(s,a))
```

Defaults are `--q-alpha 0.15 --q-gamma 0.90 --q-epsilon 0.10`.
The saved Q-table records each state hash, swap sequence and learned value for
inspection. Learning starts with a fresh table per run. Hashing and the Q table
are policy memory; PSO+QL has no fitness or path memoization.

To include topology generation and simulation, either pipeline accepts
`--algorithm PSO_DP` or `--algorithm PSO_QL`, including aliases `PSO+DP` and
`PSO+QL`. The names `PSO_WITH_ONLY_DP` and `PSO_WITH_ONLY_QL` also work.
For a pure native 3D stack on Windows:

```powershell
python native_3d_mesh/run_pipeline_mesh.py --algorithm PSO_QL --graph 3 --chiprows 2 --chipcols 2 --two5dwidth 1 --threedheight 2 --num2p5d 0 --num3d 1 --population 100 --iterations 100 --seed 10 --parallel-workers 4 --mode elevator --use-wsl
```

The new batch entry points are
`native_3d_mesh/run_all_graphs_pso_with_only_dp.py` and
`native_3d_mesh/run_all_graphs_pso_with_only_ql.py`. They use the settings and topology
sizes in `run_all_mesh_graphs.py`; set `USE_WSL = True` there on Windows or run
the scripts inside WSL. Use `PSO_WORKERS` to select their thread count.

```powershell
python native_3d_mesh/run_all_graphs_pso_with_only_dp.py
python native_3d_mesh/run_all_graphs_pso_with_only_ql.py
```

The previous optimizer and batch filenames remain as compatibility entry points.

Each requested PSO variant has its own native-mesh batch entry point, using the
existing dimensions, TSV modes, seeds, simulation and CSV framework:

| Optimizer | Batch script |
|---|---|
| Base PSO, `pso_3p5d.py` | `native_3d_mesh/run_all_graphs_pso_3p5d.py` |
| PSO + DP, `pso_with_only_dp.py` (alias `pso_dp_3p5d.py`) | `native_3d_mesh/run_all_graphs_pso_dp_3p5d.py` |
| PSO + QL, `pso_with_only_ql.py` (alias `pso_ql_3p5d.py`) | `native_3d_mesh/run_all_graphs_pso_ql_3p5d.py` |

DP's routing state is `(current_router, target_layer, latched)`, under a fixed
particle's TSV assignment. `latched=True` represents descent toward an external
destination: the selected elevator remains fixed during that planar segment.
For intra-stack routing, the native simulator reads the assignment again at each
XY hop. The recurrence adds that segment's latency to the successor state's
remaining latency; its terminal value is zero on the target layer. The cached
value also contains the arrival router and directed TSV crossings. Cache entries
are scoped to one particle evaluation. Whole-fitness memoization separately keys
the full repaired chromosome plus graph, geometry and objective context. DP
evaluates the prescribed routing policy exactly; PSO still searches placements.
It does not guarantee the globally optimal mapping.

QL's state remains the SHA-256 hash of the complete repaired chromosome.
Actions remain concrete ordered mapping/TSV swap sequences, including no-op.
The action space contains all legal indexed sequences of length 1 through
`max_swaps`, plus no-op. PSO-guided proposals and full-support random proposals
sample this fixed space. Only the Q edit and repair determine each learned
transition and reward; PSO supplies additional starting particles for this
off-policy learning. The iteration limit truncates sampling of a continuing
particle-edit process, so the final sampled transition still bootstraps. A true
terminal transition, if explicitly supplied to `q_update_value`, bootstraps zero.
The fixed learning rate and finite run budget provide no convergence guarantee;
complete-particle hashes also limit generalization across different particles.
See [Watkins and Dayan's Q-learning paper](https://www.gatsby.ucl.ac.uk/~dayan/papers/cjch.pdf)
for the update and convergence assumptions, and
[the DP formulation](https://hankyang.seas.harvard.edu/OptimalControlEstimation/formulation.html)
for additive state recurrences.

Upward and downward load variances are population variances over all installed
directed TSV links, including unused links at every layer interface. Each graph
edge contributes its bandwidth once to every crossing on its actual route.
Destination-side ascent starts at that stack's bottom attachment. Overall
variance is `max(variance_up, variance_down)`. The objective retains its 50/50
cost/variance weights; the communication-cost normalizer now uses total bandwidth
and a conservative whole-route bound, including both endpoint legs. Corrected
normalized fitness values should not be compared directly with old CSV values.

Validation:

```powershell
python -m unittest discover -s tests -p test_pso_variants.py -v
```

Tests cover forced overlap between evaluations, cached versus uncached fitness,
exact swap ordering, complete-particle hashes, Bellman updates, and matching
seeded results with one versus four workers in both TSV assignment modes.
