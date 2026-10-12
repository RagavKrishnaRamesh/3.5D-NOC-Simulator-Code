#!/usr/bin/env python3
"""Run native 3D mesh PSO on all or k random graphs.

This wrapper uses the original PSO optimizer, without DP caching or Q-learning,
and reuses the pure-3D graph selection/dimension rules from run_all_graphs_3d.py.
"""

from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from native_3d_mesh import run_all_graphs_3d as runner_3d
from native_3d_mesh import run_all_mesh_graphs as runner


if __name__ == "__main__":
    runner.ALGORITHMS = ["PSO"]
    runner_3d.main()
