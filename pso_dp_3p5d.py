"""Compatibility entry point; use pso_with_only_dp.py for threaded PSO+DP."""

import sys
import pso_with_only_dp as _implementation

if __name__ == "__main__":
    _implementation.main()
else:
    # Preserve the original API, including mutable optimizer configuration.
    sys.modules[__name__] = _implementation
