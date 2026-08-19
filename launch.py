#!/usr/bin/env python3
"""
launch.py — Environment bootstrap launcher for aisubs.py.

This script is responsible for:
  1. Locating the bundled venv Python (or falling back to a valid Python).
  2. Discovering CUDA/NVIDIA library paths from the Python interpreter.
  3. Constructing the appropriate environment (LD_LIBRARY_PATH, etc.).
  4. Launching the main aisubs.py transcription script with a clean,
     deterministic environment.

Usage:
    python3 launch.py <media_path> <model> <language> <task> <tmp_file>

The Lua plugin calls this script instead of constructing complex shell
commands with LD_LIBRARY_PATH. This keeps all environment logic inside
Python where it can introspect the interpreter's site-packages layout.
"""

import sys
import os
import json
import subprocess
import traceback

sep = os.pathsep


def find_venv_python(script_dir):
    """Locate the bundled venv Python relative to this script."""
    candidates = []
    if os.name == "nt":
        candidates.append(
            os.path.join(script_dir, "venv", "Scripts", "python.exe")
        )
    else:
        candidates.append(
            os.path.join(script_dir, "venv", "bin", "python3")
        )
        candidates.append(
            os.path.join(script_dir, "venv", "bin", "python")
        )

    for p in candidates:
        if os.path.isfile(p):
            return p
    return None


def find_site_packages(python):
    """Ask the Python interpreter where its site-packages is."""
    try:
        result = subprocess.run(
            [python, "-c",
             "import site; print(site.getsitepackages()[0])"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception as e:
        sys.stderr.write(f"Warning: could not determine site-packages: {e}\n")
    return None


def discover_lib_paths(python):
    """
    Discover NVIDIA/CUDA library directories that must be on LD_LIBRARY_PATH.

    Uses the Python interpreter to find its site-packages, then looks for
    nvidia/{cublas,cudnn}/lib inside it — the layout produced by the CUDA
    Python wheel packages (nvidia-cublas-cu12, nvidia-cudnn-cu12, etc.).
    """
    paths = []

    site_dir = find_site_packages(python)
    if not site_dir:
        return paths

    nvidia_dir = os.path.join(site_dir, "nvidia")
    if not os.path.isdir(nvidia_dir):
        return paths

    # Check for nvidia package subdirectories with a lib folder
    for sub in ("cublas", "cudnn", "cuda", "cudart", "cusolver",
                "cusparse", "nccl", "nvtx"):
        lib_dir = os.path.join(nvidia_dir, sub, "lib")
        if os.path.isdir(lib_dir):
            paths.append(lib_dir)
        else:
            lib64_dir = os.path.join(nvidia_dir, sub, "lib64")
            if os.path.isdir(lib64_dir):
                paths.append(lib64_dir)

    return paths


def build_env(python, extra_lib_paths):
    """
    Build a complete environment dict for the child process.

    Merges discovered library paths with the user's existing LD_LIBRARY_PATH
    on Unix. On Windows, we pass the environment through mostly unchanged.
    """
    env = os.environ.copy()

    if os.name != "nt" and extra_lib_paths:
        existing_ld = env.get("LD_LIBRARY_PATH", "")
        all_paths = list(extra_lib_paths) + ([existing_ld] if existing_ld else [])
        env["LD_LIBRARY_PATH"] = os.pathsep.join(all_paths)

    # Ensure the venv's bin directory is on PATH (Unix) so subprocesses
    # find Python's native extensions correctly.
    venv_dir = os.path.dirname(os.path.abspath(python))
    old_path = env.get("PATH", "")
    # Remove any existing venv from PATH to avoid stale entries
    path_entries = [p for p in old_path.split(os.pathsep) if p != venv_dir]
    env["PATH"] = os.pathsep.join([venv_dir] + path_entries)

    return env


def emit(data):
    """Emit a JSON line to stderr (diagnostics) — not stdout."""
    sys.stderr.write(json.dumps(data, ensure_ascii=False) + "\n")
    sys.stderr.flush()


def main():
    emit({
        "type": "msg",
        "msg": "entered launch.py"
    })
    if len(sys.argv) < 6:
        emit({
            "type": "error",
            "msg": "Usage: launch.py <media> <model> <lang> <task> <tmp_file>"
        })
        sys.exit(1)

    media_path = sys.argv[1]
    model_name = sys.argv[2]
    language = sys.argv[3]
    task = sys.argv[4]
    tmp_file = sys.argv[5]

    # Determine the script directory (where launch.py lives)
    script_dir = os.path.dirname(os.path.abspath(__file__))

    # 1. Find the Python interpreter
    python = find_venv_python(script_dir)
    if not python:
        explicit = os.environ.get("AI_SUBS_PYTHON")
        if explicit and os.path.isfile(explicit):
            python = explicit
        else:
            emit({
                "type": "error",
                "msg": ("Python backend not found. A bundled venv is not "
                        "installed and AI_SUBS_PYTHON is not set or invalid. "
                        "Run setup.sh first.")
            })
            sys.exit(1)

    emit({
        "type": "status",
        "msg": f"Using Python: {python}"
    })

    # 2. Discover NVIDIA/CUDA library paths
    lib_paths = discover_lib_paths(python)
    if lib_paths:
        emit({
            "type": "status",
            "msg": f"Discovered CUDA libs: {lib_paths}"
        })

    # 3. Build environment
    env = build_env(python, lib_paths)

    # 4. Determine aisubs.py path
    aisubs_script = os.path.join(script_dir, "aisubs.py")
    if not os.path.isfile(aisubs_script):
        emit({
            "type": "error",
            "msg": f"aisubs.py not found at: {aisubs_script}"
        })
        sys.exit(1)

    # 5. Launch aisubs.py with the constructed environment
    cmd = [
        python, "-u", aisubs_script,
        media_path,
        model_name,
        language,
        task,
        tmp_file,
    ]

    emit({
        "type": "status",
        "msg": f"Launching transcription: {' '.join(cmd)}"
    })

    try:
        proc = subprocess.run(
            cmd,
            env=env,
            stdout=sys.stdout,
            stderr=sys.stderr,
            check=False,
        )
        sys.exit(proc.returncode)
    except Exception as e:
        emit({
            "type": "error",
            "msg": f"Failed to launch transcription: {e}\n{traceback.format_exc()}"
        })
        sys.exit(1)


if __name__ == "__main__":
    main()
