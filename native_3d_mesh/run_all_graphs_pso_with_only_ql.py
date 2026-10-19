#!/usr/bin/env python3
"""Run every graph through the native 3D mesh pipeline with pso_with_only_ql."""

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from native_3d_mesh import run_all_mesh_graphs as runner

def main():
    runner.ALGORITHMS = ["PSO_QL"]
    runner.main()


if __name__ == "__main__":
    main()
