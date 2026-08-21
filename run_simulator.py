#!/usr/bin/env python3
import argparse
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path


def _candidate_paths(value, default_dir):
    raw = Path(value)
    bases = []
    if raw.is_absolute() or raw.parent != Path("."):
        bases.append(raw)
    else:
        bases.append(default_dir / raw)
        bases.append(raw)

    out = []
    seen = set()
    for base in bases:
        for cand in (base, base.with_suffix(".txt") if base.suffix == "" else base):
            key = str(cand)
            if key not in seen:
                seen.add(key)
                out.append(cand)
    return out


def _resolve_input_path(value, default_dir, label):
    for cand in _candidate_paths(value, default_dir):
        if cand.is_file():
            return cand
    checked = ", ".join(str(p) for p in _candidate_paths(value, default_dir))
    raise FileNotFoundError(f"{label} not found. Checked: {checked}")


def _resolve_graph_path(graph_value, repo_root):
    graphs_dir = repo_root / "Graphs"
    graph_str = str(graph_value).strip()
    if graph_str.isdigit():
        return _resolve_input_path(f"Graph{int(graph_str)}.txt", graphs_dir, "Graph file")
    return _resolve_input_path(graph_str, graphs_dir, "Graph file")


def _resolve_particle_path(particle_value, repo_root):
    particles_dir = repo_root / "Particles"
    return _resolve_input_path(particle_value, particles_dir, "Particle file")


def _resolve_noxim_binary(noxim_value, repo_root):
    raw = Path(noxim_value)
    candidates = []
    if raw.is_absolute():
        candidates.append(raw)
    else:
        candidates.append(repo_root / raw)

    if raw.suffix.lower() != ".exe":
        for base in list(candidates):
            candidates.append(base.with_suffix(".exe"))

    for cand in candidates:
        if cand.is_file():
            return cand

    checked = ", ".join(str(p) for p in candidates)
    raise FileNotFoundError(f"noxim binary not found. Checked: {checked}")


def _run_checked(cmd, cwd):
    subprocess.run(cmd, cwd=cwd, check=True)


def _rel_to_repo(path, repo_root):
    try:
        return path.relative_to(repo_root).as_posix()
    except ValueError:
        return str(path)


def _windows_to_wsl_path(path):
    resolved = Path(path).resolve()
    drive = resolved.drive.rstrip(":")
    if not drive:
        raise ValueError(f"Cannot convert path to WSL path: {resolved}")
    posix = resolved.as_posix()
    prefix = f"{drive}:/"
    if not posix.startswith(prefix):
        raise ValueError(f"Cannot convert path to WSL path: {resolved}")
    return f"/mnt/{drive.lower()}/{posix[len(prefix):]}"


def _read_particle_meta(particle_path):
    with Path(particle_path).open("r", encoding="utf-8") as f:
        data = json.load(f)
    hints = data.get("topology_hints")
    if not isinstance(hints, dict):
        hints = {}
    return hints


def run_simulation(
    particle,
    graph,
    yaml_dir="YAML",
    traffic_dir="TrafficTable",
    log_dir="LOG",
    noxim="bin/noxim",
    seed=None,
    power="bin/power.yaml",
    id_space="global",
    directed=False,
    use_wsl=False,
):
    repo_root = Path(__file__).resolve().parent
    particle_path = _resolve_particle_path(particle, repo_root)
    graph_path = _resolve_graph_path(graph, repo_root)
    noxim_path = _resolve_noxim_binary(noxim, repo_root)
    topology_hints = _read_particle_meta(particle_path)

    power_path = Path(power)
    if not power_path.is_absolute():
        power_path = repo_root / power_path
    if not power_path.is_file():
        raise FileNotFoundError(f"Power model not found: {power_path}")

    yaml_dir = Path(yaml_dir)
    if not yaml_dir.is_absolute():
        yaml_dir = repo_root / yaml_dir
    traffic_dir = Path(traffic_dir)
    if not traffic_dir.is_absolute():
        traffic_dir = repo_root / traffic_dir
    log_dir = Path(log_dir)
    if not log_dir.is_absolute():
        log_dir = repo_root / log_dir

    yaml_dir.mkdir(parents=True, exist_ok=True)
    traffic_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)

    base = particle_path.stem
    yaml_path = yaml_dir / f"{base}.yaml"
    traffic_path = traffic_dir / f"{base}-TrafficTable.txt"
    log_path = log_dir / f"{base}.log"

    py = sys.executable
    yaml_cmd = [
        py,
        "generate_yaml.py",
        _rel_to_repo(particle_path, repo_root),
        _rel_to_repo(yaml_path, repo_root),
    ]
    _run_checked(yaml_cmd, repo_root)

    effective_id_space = id_space
    if (
        effective_id_space == "global"
        and topology_hints.get("base_interposer_enabled") is False
    ):
        effective_id_space = "particle"
        print(
            "Detected base_interposer_enabled=false in particle; "
            "using --id-space particle."
        )

    traffic_cmd = [
        py,
        "write_traffic_table.py",
        _rel_to_repo(graph_path, repo_root),
        "--particle",
        _rel_to_repo(particle_path, repo_root),
        "--output",
        _rel_to_repo(traffic_path, repo_root),
        "--id-space",
        effective_id_space,
        "--update-config",
        _rel_to_repo(yaml_path, repo_root),
    ]
    if directed:
        traffic_cmd.append("--directed")
    _run_checked(traffic_cmd, repo_root)

    noxim_cmd = [
        str(noxim_path),
        "-config",
        _rel_to_repo(yaml_path, repo_root),
        "-power",
        _rel_to_repo(power_path, repo_root),
    ]
    if seed is not None:
        noxim_cmd.extend(["-seed", str(seed)])

    sim_cmd = noxim_cmd
    if use_wsl:
        if os.name != "nt":
            raise SystemExit("--use-wsl is intended for Windows hosts only.")
        wsl_repo = _windows_to_wsl_path(repo_root)
        cmd = (
            "cd {repo} && source bin/env.sh && "
            "{noxim} -config {yaml} -power {power}{seed_arg}"
        ).format(
            repo=shlex.quote(wsl_repo),
            noxim=shlex.quote(_rel_to_repo(noxim_path, repo_root)),
            yaml=shlex.quote(_rel_to_repo(yaml_path, repo_root)),
            power=shlex.quote(_rel_to_repo(power_path, repo_root)),
            seed_arg=(
                ""
                if seed is None
                else f" -seed {shlex.quote(str(seed))}"
            ),
        )
        sim_cmd = ["wsl", "bash", "-lc", cmd]

    with log_path.open("w", encoding="utf-8") as log_file:
        try:
            proc = subprocess.run(
                sim_cmd,
                cwd=repo_root,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                check=False,
            )
        except OSError as exc:
            hint = ""
            if os.name == "nt" and not use_wsl:
                hint = " On Windows, use --use-wsl for Linux-built bin/noxim."
            raise SystemExit(f"Failed to start simulator: {exc}.{hint}") from exc
    if proc.returncode != 0:
        raise SystemExit(
            f"noxim failed with exit code {proc.returncode}. See log: {log_path}"
        )

    return {
        "particle": particle_path,
        "graph": graph_path,
        "yaml": yaml_path,
        "traffic_table": traffic_path,
        "traffic_id_space": effective_id_space,
        "log": log_path,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Generate 3D-multimesh YAML + traffic table for one particle and run noxim."
    )
    parser.add_argument(
        "particle",
        help="Particle file name/path (resolved in Particles/ when relative).",
    )
    parser.add_argument(
        "graph",
        help="Graph file name/path or graph index (resolved in Graphs/ when relative).",
    )
    parser.add_argument(
        "--yaml-dir",
        default="YAML",
        help="Directory for generated YAML files (default: YAML).",
    )
    parser.add_argument(
        "--traffic-dir",
        default="TrafficTable",
        help="Directory for generated traffic tables (default: TrafficTable).",
    )
    parser.add_argument(
        "--log-dir",
        default="LOG",
        help="Directory for simulator logs (default: LOG).",
    )
    parser.add_argument(
        "--noxim",
        default="bin/noxim",
        help="Path to noxim binary (default: bin/noxim).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Simulator RNG seed. Omit to let noxim use its default time-based seed.",
    )
    parser.add_argument(
        "--power",
        default="bin/power.yaml",
        help="Path to power model file (default: bin/power.yaml).",
    )
    parser.add_argument(
        "--id-space",
        choices=("global", "particle"),
        default="global",
        help="Traffic table ID space forwarded to write_traffic_table.py.",
    )
    parser.add_argument(
        "--directed",
        action="store_true",
        help="Use directed graph edges when generating the traffic table.",
    )
    parser.add_argument(
        "--use-wsl",
        action="store_true",
        help="Run noxim via WSL bash (use this on Windows with Linux-built bin/noxim).",
    )
    args = parser.parse_args()

    result = run_simulation(
        args.particle,
        args.graph,
        yaml_dir=args.yaml_dir,
        traffic_dir=args.traffic_dir,
        log_dir=args.log_dir,
        noxim=args.noxim,
        seed=args.seed,
        power=args.power,
        id_space=args.id_space,
        directed=args.directed,
        use_wsl=args.use_wsl,
    )

    print(f"Particle: {result['particle']}")
    print(f"Graph: {result['graph']}")
    print(f"YAML: {result['yaml']}")
    print(f"Traffic Table: {result['traffic_table']}")
    print(f"Traffic ID Space: {result['traffic_id_space']}")
    print(
        "Seed: "
        + (str(args.seed) if args.seed is not None else "system time (noxim default)")
    )
    print(f"Log: {result['log']}")
    print("Simulation completed successfully.")


if __name__ == "__main__":
    main()
