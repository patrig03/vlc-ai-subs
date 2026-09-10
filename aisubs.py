#!/usr/bin/env python3
"""
vlc-ai-subs — Whisper transcription backend (entry point).

Thin wrapper that delegates to src/aisubs/cli.py. Keeps the root
script stable for VLC while the implementation lives in a proper
package for readability and testability.
"""

import os
import sys

# Ensure src/ is on sys.path so `import aisubs` works when run from any cwd
_ROOT = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(_ROOT, "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from aisubs.cli import main  # noqa: E402

if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        import traceback

        from aisubs.protocol import emit
        from aisubs.protocol import _out_file as _of

        emit({"type": "error", "msg": str(e) + "\n" + traceback.format_exc()})
        if _of:
            try:
                _of.close()
            except Exception:
                pass
        sys.exit(1)
