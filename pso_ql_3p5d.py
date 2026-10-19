"""Compatibility entry point; use pso_with_only_ql.py for threaded PSO+QL."""

import sys
import pso_with_only_ql as _implementation

if __name__ == "__main__":
    _implementation.main()
else:
    sys.modules[__name__] = _implementation
