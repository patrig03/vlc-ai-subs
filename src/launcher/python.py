"""Python interpreter discovery."""

import os
import subprocess
import sys


def find_venv_python(script_dir: str) -> str | None:
    """Locate the bundled venv Python relative to this script."""
    candidates: list[str] = []
    if os.name == "nt":
        candidates.append(os.path.join(script_dir, "venv", "Scripts", "python.exe"))
    else:
        candidates.append(os.path.join(script_dir, "venv", "bin", "python3"))
        candidates.append(os.path.join(script_dir, "venv", "bin", "python"))

    for p in candidates:
        if os.path.isfile(p):
            return p
    return None


def find_site_packages(python: str) -> str | None:
    """Ask the Python interpreter where its site-packages is."""
    try:
        result = subprocess.run(
            [python, "-c", "import site; print(site.getsitepackages()[0])"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception as e:
        sys.stderr.write(f"Warning: could not determine site-packages: {e}\n")
    return None
