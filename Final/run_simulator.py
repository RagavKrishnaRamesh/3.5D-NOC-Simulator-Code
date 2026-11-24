#!/usr/bin/env python3
import argparse
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

from pipeline_paths import BIN_DIR, FINAL_DIR, PROJECT_DIR, graph_input_path
from write_traffic_table import _update_config


DEFAULT_NOXIM = BIN_DIR / "noxim"
DEFAULT_POWER = BIN_DIR / "power.yaml"


def _candidate_paths(value, default_dir):
    raw = Path(value)
    if raw.is_absolute():
        bases = [raw]
    elif raw.parent != Path("."):
        bases = [raw, FINAL_DIR / raw]
    else:
        bases = [default_dir / raw, raw]

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
            return cand.resolve()
    checked = ", ".join(str(p) for p in _candidate_paths(value, default_dir))
    raise FileNotFoundError(f"{label} not found. Checked: {checked}")


def _asset_paths(value):
    path = Path(value)
    if path.is_absolute():
        return [path]
    return [FINAL_DIR / path, PROJECT_DIR / path]


def _resolve_noxim_binary(noxim_value):
    raw = Path(noxim_value)
    candidates = _asset_paths(raw)

    if raw.suffix.lower() != ".exe":
        candidates += [path.with_suffix(".exe") for path in candidates]

    for cand in candidates:
        if cand.is_file():
            return cand.resolve()

    checked = ", ".join(str(p) for p in candidates)
    raise FileNotFoundError(f"noxim binary not found. Checked: {checked}")


def _resolve_power_model(power_value):
    candidates = _asset_paths(power_value)
    for path in candidates:
        if path.is_file():
            return path.resolve()
    checked = ", ".join(str(path) for path in candidates)
    raise FileNotFoundError(f"Power model not found. Checked: {checked}")


def _run_checked(cmd, cwd):
    subprocess.run(cmd, cwd=cwd, check=True)


def _relative_to_final(path):
    try:
        return path.relative_to(FINAL_DIR).as_posix()
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


def _simulator_library_dirs():
    for installation in (BIN_DIR / "systemc" / "2.3.4", BIN_DIR / "yaml-cpp"):
        lib64 = installation / "lib64"
        yield lib64 if lib64.is_dir() else installation / "lib"


def _simulator_environment():
    env = os.environ.copy()
    if os.name != "nt":
        lib_dirs = [str(path) for path in _simulator_library_dirs()]
        if env.get("LD_LIBRARY_PATH"):
            lib_dirs.append(env["LD_LIBRARY_PATH"])
        env["LD_LIBRARY_PATH"] = os.pathsep.join(lib_dirs)
    return env


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
    yaml_dir=None,
    traffic_dir=None,
    log_dir=None,
    noxim=DEFAULT_NOXIM,
    seed=None,
    power=DEFAULT_POWER,
    id_space="global",
    directed=False,
    use_wsl=False,
    native_3d_mesh=False,
):
    if use_wsl and os.name != "nt":
        raise SystemExit("--use-wsl is intended for Windows hosts only.")

    particle_path = _resolve_input_path(particle, FINAL_DIR / "Particles", "Particle file")
    graph_path = graph_input_path(graph)
    noxim_path = _resolve_noxim_binary(noxim)
    power_path = _resolve_power_model(power)
    topology_hints = _read_particle_meta(particle_path)

    output_base = Path("native_3d_mesh") if native_3d_mesh else Path()
    yaml_dir = FINAL_DIR / (Path(yaml_dir) if yaml_dir is not None else output_base / "YAML")
    traffic_dir = FINAL_DIR / (Path(traffic_dir) if traffic_dir is not None else output_base / "TrafficTable")
    log_dir = FINAL_DIR / (Path(log_dir) if log_dir is not None else output_base / "LOG")

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
        "native_3d_mesh/generate_yaml_mesh.py" if native_3d_mesh else "generate_yaml.py",
        _relative_to_final(particle_path),
        _relative_to_final(yaml_path),
    ]
    _run_checked(yaml_cmd, FINAL_DIR)

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
        "native_3d_mesh/write_traffic_table_mesh.py" if native_3d_mesh else "write_traffic_table.py",
        _relative_to_final(graph_path),
        "--particle",
        _relative_to_final(particle_path),
        "--output",
        _relative_to_final(traffic_path),
        "--id-space",
        effective_id_space,
    ]
    if directed:
        traffic_cmd.append("--directed")
    _run_checked(traffic_cmd, FINAL_DIR)

    table_reference = _relative_to_final(traffic_path)
    if use_wsl and Path(table_reference).is_absolute():
        table_reference = _windows_to_wsl_path(traffic_path)
    _update_config(yaml_path, table_reference)

    noxim_cmd = [
        str(noxim_path),
        "-config",
        _relative_to_final(yaml_path),
        "-power",
        _relative_to_final(power_path),
    ]
    if seed is not None:
        noxim_cmd.extend(["-seed", str(seed)])

    sim_cmd = noxim_cmd
    if use_wsl:
        wsl_final = _windows_to_wsl_path(FINAL_DIR)
        wsl_libs = ":".join(_windows_to_wsl_path(path) for path in _simulator_library_dirs())
        wsl_args = [
            _windows_to_wsl_path(noxim_path),
            "-config", _windows_to_wsl_path(yaml_path),
            "-power", _windows_to_wsl_path(power_path),
        ]
        if seed is not None:
            wsl_args.extend(["-seed", str(seed)])
        cmd = (
            f"cd {shlex.quote(wsl_final)} && "
            f"export LD_LIBRARY_PATH={shlex.quote(wsl_libs)}"
            '"${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" && '
            f"exec {shlex.join(wsl_args)}"
        )
        sim_cmd = ["wsl", "bash", "-lc", cmd]

    with log_path.open("w", encoding="utf-8") as log_file:
        try:
            proc = subprocess.run(
                sim_cmd,
                cwd=FINAL_DIR,
                env=_simulator_environment(),
                stdout=log_file,
                stderr=subprocess.STDOUT,
                check=False,
            )
        except OSError as exc:
            hint = ""
            if os.name == "nt" and not use_wsl:
                hint = " On Windows, use --use-wsl for the Linux simulator."
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
        help="Graph file path, benchmark name, or index (benchmarks in ../Graphs/).",
    )
    parser.add_argument(
        "--yaml-dir",
        help="Directory for generated YAML files (default: YAML).",
    )
    parser.add_argument(
        "--traffic-dir",
        help="Directory for generated traffic tables (default: TrafficTable).",
    )
    parser.add_argument(
        "--log-dir",
        help="Directory for simulator logs (default: LOG).",
    )
    parser.add_argument(
        "--noxim",
        default=DEFAULT_NOXIM,
        help="Path to noxim binary (default: ../bin/noxim).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Simulator RNG seed. Omit to let noxim use its default time-based seed.",
    )
    parser.add_argument(
        "--power",
        default=DEFAULT_POWER,
        help="Path to power model file (default: ../bin/power.yaml).",
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
        help="Run the Linux simulator via WSL bash on Windows.",
    )
    parser.add_argument("--native-3d-mesh", action="store_true", help="Generate native 3D meshes.")
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
        native_3d_mesh=args.native_3d_mesh,
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
