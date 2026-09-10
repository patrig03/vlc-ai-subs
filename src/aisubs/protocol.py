"""JSON-line protocol for communicating with the VLC Lua frontend."""

import json
from typing import Optional, TextIO

_out_file: Optional[TextIO] = None


def set_output_file(f: Optional[TextIO]) -> None:
    global _out_file
    _out_file = f


def emit(data: dict) -> None:
    """Write a JSON line to stdout and to the output file if set."""
    line = json.dumps(data, ensure_ascii=False)
    print(line, flush=True)
    if _out_file:
        try:
            _out_file.write(line + "\n")
            _out_file.flush()
        except Exception:
            pass
