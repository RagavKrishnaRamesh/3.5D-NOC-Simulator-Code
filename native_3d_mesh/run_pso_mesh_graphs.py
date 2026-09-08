#!/usr/bin/env python3
"""Run the native 3D mesh full pipeline for every graph using PSO only."""

from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from native_3d_mesh import run_all_mesh_graphs as runner


if __name__ == "__main__":
    runner.ALGORITHMS = ["PSO"]
    runner.main()
