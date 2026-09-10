"""CUDA / NVIDIA library discovery and environment construction."""

import os

from .python import find_site_packages


def discover_lib_paths(python: str) -> list[str]:
    """
    Discover NVIDIA/CUDA library directories that must be on LD_LIBRARY_PATH.

    Uses the Python interpreter to find its site-packages, then looks for
    nvidia/{cublas,cudnn}/lib inside it — the layout produced by the CUDA
    Python wheel packages (nvidia-cublas-cu12, nvidia-cudnn-cu12, etc.).
    """
    paths: list[str] = []

    site_dir = find_site_packages(python)
    if not site_dir:
        return paths

    nvidia_dir = os.path.join(site_dir, "nvidia")
    if not os.path.isdir(nvidia_dir):
        return paths

    for sub in ("cublas", "cudnn", "cuda", "cudart", "cusolver", "cusparse", "nccl", "nvtx"):
        lib_dir = os.path.join(nvidia_dir, sub, "lib")
        if os.path.isdir(lib_dir):
            paths.append(lib_dir)
        else:
            lib64_dir = os.path.join(nvidia_dir, sub, "lib64")
            if os.path.isdir(lib64_dir):
                paths.append(lib64_dir)

    return paths


def build_env(python: str, extra_lib_paths: list[str]) -> dict[str, str]:
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

    # Ensure the venv's bin directory is on PATH (Unix)
    venv_dir = os.path.dirname(os.path.abspath(python))
    old_path = env.get("PATH", "")
    path_entries = [p for p in old_path.split(os.pathsep) if p != venv_dir]
    env["PATH"] = os.pathsep.join([venv_dir] + path_entries)

    return env
