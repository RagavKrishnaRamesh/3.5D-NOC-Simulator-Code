#!/usr/bin/env python3
"""Compatibility entry point for run_all_graphs_pso_with_only_ql.py."""

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from native_3d_mesh.run_all_graphs_pso_with_only_ql import main

if __name__ == "__main__":
    main()
