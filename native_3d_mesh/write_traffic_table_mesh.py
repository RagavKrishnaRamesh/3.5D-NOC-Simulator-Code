#!/usr/bin/env python3
"""Generate traffic tables using native 3D mesh global-id allocation."""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import write_traffic_table as legacy
from native_3d_mesh.generate_yaml_mesh import with_native_mesh_graph


def main():
    return with_native_mesh_graph(legacy.main)


if __name__ == "__main__":
    main()
