# Full-Pipeline · 3.5D NoC PSO

This folder contains the three PSO variants and the Python scripts that turn a benchmark into a particle, simulation log, results CSV, and Excel workbook. The scripts read the benchmark graphs from [the project's Graphs folder](../Graphs/) and use Noxim, its power model, and its runtime libraries from [the project's bin folder](../bin/).

| Algorithm | Optimizer entry point | Fitness evaluation |
| --- | --- | --- |
| `PSO` | `pso_3p5d.py` | Serial route evaluation |
| `PSO_DP` | `pso_with_only_dp.py` | Serial evaluation with route and particle caches |
| `PSO_DP_MT` | `pso_dp_multithreaded.py` | The shared DP evaluator with worker threads |

The theory guide covers particle encoding, swap updates, TSV routing and fitness, the DP recurrence, and thread scheduling. [PSO.pdf](PSO.pdf) · [PSO.md](PSO.md) · [PSO.tex](PSO.tex)

## Run the pipeline

Run these commands from `Final/` within the project checkout. Use Python 3.10 or newer. The scripts use the standard library, including for Excel export. The project's Noxim binary and SystemC runtime are for x86-64 Linux. Ubuntu 22.04 or newer provides the required runtime libraries. On Windows, use an Ubuntu WSL distribution and pass `--use-wsl` when launching with Windows Python. Inside WSL or Linux, use `python3` and omit that flag.

For a fresh Git checkout, restore your benchmark files to the project’s `Graphs/` folder or pass their file paths with `--graph`.

This example runs all three optimizers on Graph 3 using one two-layer stack with four routers per layer. It uses identical optimizer and simulator seeds across the variants.

```powershell
python run_pipeline.py --algorithm ALL --graph 3 --chiprows 2 --chipcols 2 --two5dwidth 1 --threedheight 2 --num2p5d 0 --num3d 1 --population 8 --iterations 12 --seed 10 --sim-seed 11 --parallel-workers 4 --use-wsl
```

Replace `ALL` with `PSO`, `PSO_DP`, or `PSO_DP_MT` to run a single variant. Pass `--parallel-workers` with `PSO_DP_MT` or `ALL`. The threaded variant reads `PSO_WORKERS` if no count is supplied, then defaults to the smallest of the CPU count, swarm size, and four. The effective count is capped at the swarm size. One worker uses the serial execution path.

### Set up a run

- `--graph` accepts a benchmark number or name from `../Graphs/`, or a graph file path. Use repeated `--graph` arguments for graphs that share dimensions. A graph file starts with the core count and contains a square bandwidth matrix. `INF` marks absent edges.
- `--chiprows` and `--chipcols` specify one plane. `--threedheight` is the number of planes per 3D stack, and `--two5dwidth` is the number of planar chiplets per 2.5D complex. Capacity is `chiprows * chipcols * (threedheight * num3d + two5dwidth * num2p5d)` and must cover the graph's core count.
- `--mode random` uses REDELF-based TSV assignment and is the default. `--mode elevator` uses elevator-first assignment.
- `--seed` sets the optimizer seed. `--sim-seed` sets the simulator seed and defaults to the supplied optimizer seed. With both omitted, the optimizer and simulator use time-based seeds.
- `--native-3d-mesh` emits one native mesh per 3D stack with sparse internal TSVs. The default emits one planar mesh per layer with explicit vertical links between layers. Both modes use the project's Noxim binary.
- `--directed` makes the simulation traffic generator read both directions from the matrix. The optimizer's edge set uses the upper triangle.
- `--noxim` and `--power` can select a compatible simulator and power model. Their defaults are `../bin/noxim` and `../bin/power.yaml`. Override paths can be absolute or relative to `Final/` or the project root.

A mixed example for Graph 4 uses one 2.5D complex containing four 2×2 chiplets and one 3D stack containing four 2×2 layers.

```powershell
python run_pipeline.py --algorithm ALL --graph 4 --chiprows 2 --chipcols 2 --two5dwidth 4 --threedheight 4 --num2p5d 1 --num3d 1 --population 8 --iterations 12 --seed 10 --sim-seed 11 --use-wsl --native-3d-mesh
```

## Outputs

| Artifact | Location |
| --- | --- |
| Optimizer edge list | `EdgeSet/edge_set_Graph3.txt` |
| Best particle (JSON) | `Particles/PSO_Particle3.txt`, `Particles/PSO_DP_Particle3.txt`, `Particles/PSO_DP_MT_Particle3.txt` |
| Topology, traffic table, and log | `YAML/`, `TrafficTable/`, and `LOG/`, named after the particle |
| Variant CSV and Excel workbook | `RESULTS_<mode>_<algorithm>_<YYYYMMDD_HHMMSS>.csv` and matching `.xlsx` |
| Comparison workbook from `ALL` | `RESULTS_<mode>_pso_comparison_<YYYYMMDD_HHMMSS>.xlsx` |

The native mesh option writes its simulation files and reports under `native_3d_mesh/`. The edge list and particles use the shared directories in both topology modes. Rerunning a variant for the same graph replaces its named particle and simulation artifacts. Use `--results-start-time YYYYMMDD_HHMMSS` to append new rows to an existing run CSV, for example when running graphs with different dimensions. Run invocations that use the same outputs sequentially. Close CSVs and workbooks in Excel before updating them.

Each variant workbook has **Static Results** and **Dynamic Results** sheets. The comparison workbook has both sheets for each of the three variants. The CSVs also record effective fitness, optimizer and simulator timings, and worker count. Repeat rows are preserved in Excel. Use the CSV when you need each row's run settings and seeds.

## Run stages separately

The three optimizer scripts take the same positional arguments in this order. The final positional argument selects TSV assignment mode, where `0` means elevator and `1` means random.

```powershell
python pso_3p5d.py Graph3 2 2 1 2 0 1 12 8 1 --seed 10
python pso_with_only_dp.py Graph3 2 2 1 2 0 1 12 8 1 --seed 10
python pso_dp_multithreaded.py Graph3 2 2 1 2 0 1 12 8 1 --seed 10 --parallel-workers 4
```

The two DP optimizer entry points also accept `--no-fitness-cache` to disable whole-particle result reuse. Per-particle route DP remains active.

To regenerate simulator inputs and rerun Noxim from an existing particle, use `run_simulator.py`. To regenerate Excel from a CSV, use `csv_to_excel_results.py`. A three-CSV export accepts the files in PSO, PSO_DP, and PSO_DP_MT order and requires `-o` for the comparison workbook name.

```powershell
python run_simulator.py Particles/PSO_DP_MT_Particle3.txt 3 --seed 11 --use-wsl
python csv_to_excel_results.py RESULTS_random_pso_dp_mt_20261123_120000.csv
python csv_to_excel_results.py RESULTS_random_pso_20261123_120000.csv RESULTS_random_pso_dp_20261123_120000.csv RESULTS_random_pso_dp_mt_20261123_120000.csv -o comparison.xlsx
```

## Repository layout

| Path | Purpose |
| --- | --- |
| `run_pipeline.py` | Runs one or all three variants, collects metrics, and exports reports |
| `edge_set_creation.py` and `pipeline_paths.py` | Graph preprocessing and lookup of shared project inputs |
| `generate_yaml.py` and `write_traffic_table.py` | Layered topology and traffic input generation |
| `native_3d_mesh/` | Native 3D topology generator and router-ID adapter |
| `run_simulator.py` | Generates simulation inputs, launches Noxim, and captures its log |
| `csv_to_excel_results.py` | Builds `.xlsx` reports from pipeline CSVs |
| `../Graphs/` | Shared benchmark graphs |
| `../src/` and `../bin/` | Shared simulator source, build file, Linux binary, libraries, and power model |

To rebuild the project simulator from this folder on x86-64 Linux or in WSL, use GNU Make and a C++14 compiler. If the Linux binary lacks execute permission, restore it with `chmod +x ../bin/noxim`.

```bash
make -C ../bin -j4
```

To rebuild the theory PDF from this folder, run pdfLaTeX twice to populate its table of contents.

```text
pdflatex -interaction=nonstopmode -halt-on-error PSO.tex
pdflatex -interaction=nonstopmode -halt-on-error PSO.tex
```
