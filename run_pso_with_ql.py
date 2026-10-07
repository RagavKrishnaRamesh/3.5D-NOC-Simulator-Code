#!/usr/bin/env python3
"""Run the full PSO_WITH_QL pipeline; accepts run_pipeline.py options."""
import sys
import run_pipeline

if __name__ == "__main__":
    sys.argv[1:1] = ["--algorithm", "PSO_WITH_QL"]
    run_pipeline.main()
