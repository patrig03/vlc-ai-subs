"""CUDA / NVIDIA library discovery and environment construction."""

import os

from .python import find_site_packages


def discover_lib_paths(python: str) -> list[str]:
    """
    Discover NVIDIA/CUDA library directories that must be on LD_LIBRARY_PATH.

    Searches:
    1. venv site-packages/nvidia/*/lib (or lib64 / bin on Windows) — layout of
       nvidia-cublas-cu12, nvidia-cuda-runtime-cu12, nvidia-cudnn-cu12, etc.
       Handles both underscore and hyphen variants (cuda_nvrtc vs cuda-nvrtc).
    2. System CUDA paths (/usr/local/cuda/lib64, /opt/cuda/lib64) as fallback.
    """
    paths: list[str] = []
    seen: set[str] = set()

    def _add(p: str) -> None:
        ap = os.path.abspath(p)
        if ap not in seen and os.path.isdir(ap):
            # Only add if it actually contains libs (avoid empty dirs)
            try:
                entries = os.listdir(ap)
            except Exception:
                entries = []
            # Keep if has .so/.dll or at least not empty, otherwise still useful for fallback
            has_lib = any(
                e.endswith((".so", ".so.12", ".so.13", ".dll", ".dylib")) or "cublas" in e.lower() or "cudnn" in e.lower()
                for e in entries
            )
            # If directory is non-empty, add it; empty dirs are still okay to add but de-duplicate
            if has_lib or entries:
                seen.add(ap)
                paths.append(ap)
            elif not entries:
                # Empty dir — still add but de-duplicate
                if ap not in seen:
                    seen.add(ap)
                    paths.append(ap)

    # 1. venv site-packages
    site_dir = find_site_packages(python)
    if site_dir:
        nvidia_dir = os.path.join(site_dir, "nvidia")
        if os.path.isdir(nvidia_dir):
            try:
                for entry in os.listdir(nvidia_dir):
                    entry_path = os.path.join(nvidia_dir, entry)
                    if not os.path.isdir(entry_path):
                        continue
                    # Common layouts: nvidia/<pkg>/lib, lib64, bin (Windows)
                    for sub in ("lib", "lib64", "bin"):
                        cand = os.path.join(entry_path, sub)
                        if os.path.isdir(cand):
                            _add(cand)
                    # Also handle nested like nvidia/cublas/lib vs nvidia/cuda_runtime/lib
                    # Already covered by scanning all entries, but keep legacy explicit check
            except Exception:
                pass
            # Legacy explicit check for older venvs / known names (kept for completeness)
            for sub in ("cublas", "cudnn", "cuda", "cudart", "cusolver", "cusparse", "nccl", "nvtx",
                        "cuda_runtime", "cuda-runtime", "cuda_nvrtc", "cuda-nvrtc", "cublas_cu12"):
                for libsub in ("lib", "lib64", "bin"):
                    cand = os.path.join(nvidia_dir, sub, libsub)
                    if os.path.isdir(cand):
                        _add(cand)

    # 2. System CUDA fallbacks (Linux)
    if os.name != "nt":
        sys_candidates = [
            "/usr/local/cuda/lib64",
            "/usr/local/cuda/lib",
            "/opt/cuda/lib64",
            "/opt/cuda/lib",
            "/usr/local/cuda-12/lib64",
            "/usr/local/cuda-13/lib64",
            "/usr/lib/x86_64-linux-gnu",
            "/usr/lib64",
        ]
        for cand in sys_candidates:
            if os.path.isdir(cand):
                # Only add system path if it actually contains cublas/cudnn to avoid polluting LD_LIBRARY_PATH
                try:
                    files = os.listdir(cand)
                except Exception:
                    files = []
                if any("cublas" in f or "cudnn" in f or "cudart" in f for f in files):
                    _add(cand)
        # Also respect CUDA_HOME / CUDA_PATH if set
        for env_key in ("CUDA_HOME", "CUDA_PATH", "CUDA_ROOT"):
            cuda_home = os.environ.get(env_key)
            if cuda_home:
                for sub in ("lib64", "lib", "targets/x86_64-linux/lib"):
                    cand = os.path.join(cuda_home, sub)
                    if os.path.isdir(cand):
                        _add(cand)

    # Deduplicate preserving order (already via seen) and return
    return paths


def build_env(python: str, extra_lib_paths: list[str]) -> dict[str, str]:
    """
    Build a complete environment dict for the child process.

    Merges discovered library paths with the user's existing LD_LIBRARY_PATH
    on Unix, and PATH on Windows (where CUDA DLLs live in bin).
    """
    env = os.environ.copy()

    if extra_lib_paths:
        if os.name == "nt":
            # On Windows, CUDA DLLs are in bin; add to PATH
            existing_path = env.get("PATH", "")
            # Filter duplicates
            existing_parts = existing_path.split(os.pathsep) if existing_path else []
            # Prepend discovered paths that are not already present
            new_parts = [p for p in extra_lib_paths if p not in existing_parts]
            env["PATH"] = os.pathsep.join(new_parts + existing_parts)
        else:
            existing_ld = env.get("LD_LIBRARY_PATH", "")
            # De-duplicate while preserving order
            all_paths: list[str] = []
            seen: set[str] = set()
            for p in list(extra_lib_paths) + ([existing_ld] if existing_ld else []):
                for part in p.split(os.pathsep):
                    if part and part not in seen:
                        seen.add(part)
                        all_paths.append(part)
            env["LD_LIBRARY_PATH"] = os.pathsep.join(all_paths)

    # Ensure the venv's bin directory is on PATH (Unix & Windows)
    venv_dir = os.path.dirname(os.path.abspath(python))
    old_path = env.get("PATH", "")
    path_entries = [p for p in old_path.split(os.pathsep) if p != venv_dir]
    env["PATH"] = os.pathsep.join([venv_dir] + path_entries)

    return env
