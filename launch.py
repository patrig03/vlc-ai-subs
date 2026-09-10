#!/usr/bin/env python3
"""
launch.py — Environment bootstrap launcher for aisubs.py (entry point).

Thin wrapper that delegates to src/launcher/cli.py.
"""

import os
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(_ROOT, "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from launcher.cli import main  # noqa: E402

if __name__ == "__main__":
    main()
