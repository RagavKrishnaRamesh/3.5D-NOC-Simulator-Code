# Full Pipeline Usage

This repo runs a full NoC optimization and simulation flow:

1. Run an optimizer: `GA`, `PSO`, or `SA`
2. Write the best particle to `Particles/`
3. Generate YAML topology in `YAML/`
4. Generate traffic table in `TrafficTable/`
5. Run `noxim`
6. Append results to a dated CSV, for example `RUN_170826.csv`

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
python run_pipeline.py --algorithm <GA|PSO|SA> --graph <graph_number_or_path> --chiprows <rows> --chipcols <cols> --two5dwidth <width> --threedheight <height> --num2p5d <count> --num3d <count> --population <count> --iterations <count> --use-wsl
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
--mode elevator_first
--mode redelf_random
```

`--mode redelf_random` applies REDELF Ruleset B and chooses randomly among
valid south-or-due-east elevator candidates. `--mode elevator_first` uses the
baseline elevator-first selection without REDELF south/east or pivot rules.
Numeric modes are also accepted: `0` for `elevator_first`, `1` for
`redelf_random`.

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
RUN_<date>.csv
```

The CSV includes optimizer metrics and simulator metrics, including:

- `Hopcount`
- `Variance`
- `Variance Up`
- `Variance Down`
- `Effective Fitness`
- `Global average delay (cycles)`
- `Network throughput (flits/cycle)`
- `Total energy (J)`
- `Total received packets`

If the CSV is open in Excel, the pipeline writes to a pending file instead:

```text
RUN_<date>_pending.csv
```

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
