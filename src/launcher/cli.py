"""Launcher CLI — spawns aisubs transcription with correct env.

Usage:
    python -m launcher.cli <media_path> <model> <language> <task> <tmp_file> [audio_track] [audio_channel]
"""

import json
import os
import subprocess
import sys
import traceback


_log_file = None  # type: ignore
_log_path: str | None = None


def _open_log(tmp_file: str | None) -> None:
    global _log_file, _log_path
    if not tmp_file:
        return
    _log_path = tmp_file + ".log"
    try:
        _log_file = open(_log_path, "a", encoding="utf-8", buffering=1)
    except Exception:
        _log_file = None
        _log_path = None


def emit(data: dict) -> None:
    """Emit a JSON line to log file (if available) and stderr."""
    line = json.dumps(data, ensure_ascii=False) + "\n"
    # When log file is open, write only there to avoid duplication via shell >> log 2>&1
    if _log_file:
        try:
            _log_file.write(line)
            _log_file.flush()
        except Exception:
            pass
        return
    # No log yet (early startup) — write to stderr only; shell >> log 2>&1 will capture it once
    try:
        sys.stderr.write(line)
        sys.stderr.flush()
    except Exception:
        pass


def main(argv: list[str] | None = None) -> None:
    from .cuda import build_env, discover_lib_paths
    from .python import find_venv_python

    emit({"type": "msg", "msg": "entered launch.py"})

    if argv is None:
        argv = sys.argv

    if len(argv) < 6:
        emit({"type": "error", "msg": "Usage: launch.py <media> <model> <lang> <task> <tmp_file> [audio_track] [audio_channel]"})
        sys.exit(1)

    media_path = argv[1]
    model_name = argv[2]
    language = argv[3]
    task = argv[4]
    tmp_file = argv[5]
    _open_log(tmp_file)
    audio_track = argv[6] if len(argv) > 6 else "auto"
    audio_channel = argv[7] if len(argv) > 7 else "auto"

    # Legacy: Lua previously passed tmp_file twice (dup). Detect and ignore.
    if audio_track and ("/aisubs_" in audio_track or "\\aisubs_" in audio_track or audio_track.endswith(".txt")):
        if len(argv) > 7:
            audio_track = argv[7] or "auto"
            audio_channel = argv[8] if len(argv) > 8 else "auto"
        else:
            audio_track = "auto"
            audio_channel = "auto"

    script_dir = os.path.dirname(os.path.abspath(__file__))
    # When running as src.launcher.cli, __file__ is src/launcher/cli.py -> project root is 3 levels up
    # Try to find project root (where aisubs.py lives)
    project_root = os.path.abspath(os.path.join(script_dir, "..", ".."))
    if not os.path.isfile(os.path.join(project_root, "aisubs.py")):
        # Fallback: use script_dir's parent logic for wrapper case
        project_root = os.path.dirname(os.path.abspath(sys.argv[0])) if sys.argv[0] else script_dir
        # Also try argv[0]'s dir via __file__ fallback
        alt_root = os.path.dirname(os.path.abspath(__file__))
        # If running via root launch.py wrapper, script_dir is project root already
        if os.path.isfile(os.path.join(alt_root, "aisubs.py")):
            project_root = alt_root
        elif os.path.isfile(os.path.join(os.path.dirname(alt_root), "aisubs.py")):
            project_root = os.path.dirname(alt_root)

    # 1. Find the Python interpreter
    python = find_venv_python(project_root)
    if not python:
        # Also try discovery relative to script_dir (for nested package)
        python = find_venv_python(script_dir)
    if not python:
        explicit = os.environ.get("AI_SUBS_PYTHON")
        if explicit and os.path.isfile(explicit):
            python = explicit
        else:
            emit(
                {
                    "type": "error",
                    "msg": (
                        "Python backend not found. A bundled venv is not "
                        "installed and AI_SUBS_PYTHON is not set or invalid. "
                        "Run setup.sh first."
                    ),
                }
            )
            sys.exit(1)

    emit({"type": "status", "msg": f"Using Python: {python}"})
    if _log_path:
        emit({"type": "status", "msg": f"Log file: {_log_path}"})

    # 2. Discover NVIDIA/CUDA library paths
    lib_paths = discover_lib_paths(python)
    if lib_paths:
        emit({"type": "status", "msg": f"Discovered CUDA libs: {lib_paths}"})

    # 3. Build environment
    env = build_env(python, lib_paths)

    # 4. Determine aisubs.py path
    # Prefer project_root/aisubs.py, fallback to script_dir detection
    aisubs_script = os.path.join(project_root, "aisubs.py")
    if not os.path.isfile(aisubs_script):
        # Try alternative locations
        for cand in [
            os.path.join(script_dir, "aisubs.py"),
            os.path.join(os.path.dirname(script_dir), "aisubs.py"),
            os.path.join(os.getcwd(), "aisubs.py"),
        ]:
            if os.path.isfile(cand):
                aisubs_script = cand
                break
    if not os.path.isfile(aisubs_script):
        emit({"type": "error", "msg": f"aisubs.py not found at: {aisubs_script}"})
        sys.exit(1)

    # 5. Launch aisubs.py with the constructed environment
    cmd = [
        python,
        "-u",
        aisubs_script,
        media_path,
        model_name,
        language,
        task,
        tmp_file,
        audio_track,
        audio_channel,
    ]

    emit({"type": "status", "msg": f"Launching transcription: {' '.join(cmd)}"})

    # Prefer explicit log file for child output; fall back to inherited stdout/stderr
    # so shell-level >> log redirection still captures output.
    try:
        if _log_file and _log_path:
            # Ensure log file is flushed before child writes
            _log_file.flush()
            # Open a fresh handle for the child to avoid buffering conflicts
            # Use unbuffered append so Lua's >> log and child's writes interleave safely
            with open(_log_path, "a", encoding="utf-8", buffering=1) as child_log:
                proc = subprocess.run(
                    cmd,
                    env=env,
                    stdout=child_log,
                    stderr=subprocess.STDOUT,
                    check=False,
                )
            # Also try to append child's stdout that was printed via protocol to log
            sys.exit(proc.returncode)
        else:
            proc = subprocess.run(
                cmd,
                env=env,
                stdout=sys.stdout,
                stderr=sys.stderr,
                check=False,
            )
            sys.exit(proc.returncode)
    except SystemExit:
        raise
    except Exception as e:
        emit({"type": "error", "msg": f"Failed to launch transcription: {e}\n{traceback.format_exc()}"})
        # Also write raw traceback to log file for post-mortem
        if _log_file:
            try:
                _log_file.write(traceback.format_exc() + "\n")
                _log_file.flush()
            except Exception:
                pass
        sys.exit(1)
    finally:
        if _log_file:
            try:
                _log_file.flush()
            except Exception:
                pass


if __name__ == "__main__":
    main()
