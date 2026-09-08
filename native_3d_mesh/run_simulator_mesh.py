#!/usr/bin/env python3
"""Run the simulator using native dim_z>1 meshes for 3D chiplets."""

import argparse
import os
import shlex
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import run_simulator as legacy


def run_simulation(
    particle,
    graph,
    yaml_dir="native_3d_mesh/YAML",
    traffic_dir="native_3d_mesh/TrafficTable",
    log_dir="native_3d_mesh/LOG",
    noxim="bin/noxim",
    seed=None,
    power="bin/power.yaml",
    id_space="global",
    directed=False,
    use_wsl=False,
):
    particle_path = legacy._resolve_particle_path(particle, REPO_ROOT)
    graph_path = legacy._resolve_graph_path(graph, REPO_ROOT)
    noxim_path = legacy._resolve_noxim_binary(noxim, REPO_ROOT)
    topology_hints = legacy._read_particle_meta(particle_path)

    power_path = Path(power)
    if not power_path.is_absolute():
        power_path = REPO_ROOT / power_path
    if not power_path.is_file():
        raise FileNotFoundError(f"Power model not found: {power_path}")

    yaml_dir = Path(yaml_dir)
    if not yaml_dir.is_absolute():
        yaml_dir = REPO_ROOT / yaml_dir
    traffic_dir = Path(traffic_dir)
    if not traffic_dir.is_absolute():
        traffic_dir = REPO_ROOT / traffic_dir
    log_dir = Path(log_dir)
    if not log_dir.is_absolute():
        log_dir = REPO_ROOT / log_dir

    yaml_dir.mkdir(parents=True, exist_ok=True)
    traffic_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)

    base = particle_path.stem
    yaml_path = yaml_dir / f"{base}.yaml"
    traffic_path = traffic_dir / f"{base}-TrafficTable.txt"
    log_path = log_dir / f"{base}.log"

    py = sys.executable
    legacy._run_checked(
        [
            py,
            "native_3d_mesh/generate_yaml_mesh.py",
            legacy._rel_to_repo(particle_path, REPO_ROOT),
            legacy._rel_to_repo(yaml_path, REPO_ROOT),
        ],
        REPO_ROOT,
    )

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

    legacy._run_checked(
        [
            py,
            "native_3d_mesh/write_traffic_table_mesh.py",
            legacy._rel_to_repo(graph_path, REPO_ROOT),
            "--particle",
            legacy._rel_to_repo(particle_path, REPO_ROOT),
            "--output",
            legacy._rel_to_repo(traffic_path, REPO_ROOT),
            "--id-space",
            effective_id_space,
            "--update-config",
            legacy._rel_to_repo(yaml_path, REPO_ROOT),
        ],
        REPO_ROOT,
    )

    sim_cmd = [
        str(noxim_path),
        "-config",
        legacy._rel_to_repo(yaml_path, REPO_ROOT),
        "-power",
        legacy._rel_to_repo(power_path, REPO_ROOT),
    ]
    if seed is not None:
        sim_cmd.extend(["-seed", str(seed)])
    if directed:
        sim_cmd.append("-directed")

    if use_wsl:
        if os.name != "nt":
            raise SystemExit("--use-wsl is intended for Windows hosts only.")
        wsl_repo = legacy._windows_to_wsl_path(REPO_ROOT)
        cmd = (
            "cd {repo} && source bin/env.sh && "
            "{noxim} -config {yaml} -power {power}{seed_arg}{directed_arg}"
        ).format(
            repo=shlex.quote(wsl_repo),
            noxim=shlex.quote(legacy._rel_to_repo(noxim_path, REPO_ROOT)),
            yaml=shlex.quote(legacy._rel_to_repo(yaml_path, REPO_ROOT)),
            power=shlex.quote(legacy._rel_to_repo(power_path, REPO_ROOT)),
            seed_arg=(
                ""
                if seed is None
                else f" -seed {shlex.quote(str(seed))}"
            ),
            directed_arg=" -directed" if directed else "",
        )
        sim_cmd = ["wsl", "bash", "-lc", cmd]

    sim_env = os.environ.copy()
    systemc_lib = REPO_ROOT / "bin" / "systemc" / "2.3.4" / "lib"
    existing_library_path = sim_env.get("LD_LIBRARY_PATH")
    sim_env["LD_LIBRARY_PATH"] = (
        str(systemc_lib)
        if not existing_library_path
        else f"{systemc_lib}{os.pathsep}{existing_library_path}"
    )

    with log_path.open("w", encoding="utf-8", errors="replace") as log:
        result = subprocess.run(
            sim_cmd,
            cwd=REPO_ROOT,
            env=sim_env,
            text=True,
            stdout=log,
            stderr=subprocess.STDOUT,
            check=False,
        )
    if result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, sim_cmd)

    return {
        "yaml": yaml_path,
        "traffic_table": traffic_path,
        "log": log_path,
    }


def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate native-3D mesh YAML + traffic table and run noxim."
    )
    parser.add_argument("particle")
    parser.add_argument("graph")
    parser.add_argument("--yaml-dir", default="native_3d_mesh/YAML")
    parser.add_argument("--traffic-dir", default="native_3d_mesh/TrafficTable")
    parser.add_argument("--log-dir", default="native_3d_mesh/LOG")
    parser.add_argument("--noxim", default="bin/noxim")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--power", default="bin/power.yaml")
    parser.add_argument("--id-space", choices=("global", "particle"), default="global")
    parser.add_argument("--directed", action="store_true")
    parser.add_argument("--use-wsl", action="store_true")
    return parser.parse_args()


def main():
    args = parse_args()
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
    print(f"YAML: {result['yaml']}")
    print(f"Traffic Table: {result['traffic_table']}")
    print(f"Log: {result['log']}")


if __name__ == "__main__":
    main()
