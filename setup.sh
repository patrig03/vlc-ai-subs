#!/usr/bin/env bash
#
# vlc-ai-subs — setup & install (Linux / macOS)
#
# Usage:
#   ./setup.sh              Full setup (Python deps + VLC extension)
#   ./setup.sh --install    Only install/update the VLC extension
#
# On Windows, use setup.bat instead.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$SCRIPT_DIR/venv"
SRC="$SCRIPT_DIR/aisubs.lua"
LUA_DIR="$SCRIPT_DIR/lua"
SRC_DIR="$SCRIPT_DIR/src"
INSTALLED=0

# ── Helpers ──────────────────────────────────────────────────

info()  { echo "  → $*"; }
ok()    { echo "  ✓ $*"; }
warn()  { echo "  ⚠ $*"; }
fail()  { echo "  ✗ $*" >&2; exit 1; }

install_to() {
    local dir="$1"
    local needs_sudo="${2:-false}"

    if [ "$needs_sudo" = "true" ]; then
        if [ -d "$dir" ]; then
            sudo cp "$SRC" "$dir/aisubs.lua" 2>/dev/null && ok "$dir (aisubs.lua)" && INSTALLED=1
            # Also try to install lua/ submodules if present
            if [ -d "$LUA_DIR" ]; then
                sudo mkdir -p "$dir/lua" 2>/dev/null || true
                sudo cp "$LUA_DIR"/*.lua "$dir/lua/" 2>/dev/null && ok "$dir/lua/" || true
            fi
        fi
    else
        mkdir -p "$dir" 2>/dev/null || return
        cp "$SRC" "$dir/aisubs.lua" && ok "$dir (aisubs.lua)" && INSTALLED=1
        if [ -d "$LUA_DIR" ]; then
            mkdir -p "$dir/lua" 2>/dev/null || true
            cp "$LUA_DIR"/*.lua "$dir/lua/" 2>/dev/null && ok "$dir/lua/" || true
        fi
    fi
}

install_python_backend() {
    local target="$DATA_DIR"
    echo ""
    echo "Installing Python backend to $target ..."
    mkdir -p "$target" 2>/dev/null || warn "Could not create $target"
    # Core entry points
    for f in aisubs.py launch.py boundaries.py; do
        if [ -f "$SCRIPT_DIR/$f" ]; then
            cp "$SCRIPT_DIR/$f" "$target/$f" 2>/dev/null && ok "$target/$f" || warn "Failed to copy $f"
        fi
    done
    # Package directory
    if [ -d "$SRC_DIR" ]; then
        mkdir -p "$target/src" 2>/dev/null || true
        cp -r "$SRC_DIR"/* "$target/src/" 2>/dev/null && ok "$target/src/" || warn "Failed to copy src/"
        # Ensure src is a package (already has __init__.py)
    fi
    # venv: if project venv exists and target venv missing, copy it
    if [ -d "$VENV_DIR" ] && [ ! -d "$target/venv" ]; then
        info "Copying venv to $target/venv (this may take a moment)..."
        cp -r "$VENV_DIR" "$target/venv" 2>/dev/null && ok "venv copied" || warn "Could not copy venv — will be created on next run"
    fi
    # If no venv at target and this is full setup, let the venv creation step handle it
    # (VENV_DIR already handled earlier; target venv will be created if needed by launcher fallback)
}

# ── Detect OS ────────────────────────────────────────────────

detect_os() {
    case "${OSTYPE:-$(uname -s)}" in
        linux*|Linux)   echo "linux" ;;
        darwin*|Darwin) echo "macos" ;;
        msys*|MINGW*|CYGWIN*|Windows*) echo "windows" ;;
        *)              echo "linux" ;;  # best guess
    esac
}

OS=$(detect_os)

# Data dir where Python backend lives (used by Lua's find_script)
if [ "$OS" = "macos" ]; then
    DATA_DIR="$HOME/Library/Application Support/vlc-ai-subs"
else
    DATA_DIR="$HOME/.local/share/vlc-ai-subs"
fi
# Flatpak override
[ -d "$HOME/.var/app/org.videolan.VLC" ] && DATA_DIR="$HOME/.var/app/org.videolan.VLC/data/vlc-ai-subs"

# ── Check prerequisites ─────────────────────────────────────

check_python() {
    if command -v python3 &>/dev/null; then
        PYTHON=python3
    elif command -v python &>/dev/null; then
        PYTHON=python
    else
        echo ""
        echo "Python 3 is not installed."
        echo ""
        if [ "$OS" = "macos" ]; then
            echo "Install it with:  brew install python3"
            echo "  or download from https://www.python.org/downloads/"
        elif [ "$OS" = "linux" ]; then
            echo "Install it with:  sudo apt install python3   (Debian/Ubuntu)"
            echo "                  sudo dnf install python3   (Fedora)"
            echo "                  sudo pacman -S python      (Arch)"
        fi
        exit 1
    fi

    # Verify it's Python 3
    PY_VER=$("$PYTHON" -c 'import sys; print(sys.version_info.major)')
    if [ "$PY_VER" != "3" ]; then
        fail "Python 3 required, but found Python $PY_VER"
    fi
}

# ── Install VLC extension ───────────────────────────────────

install_vlc_extension() {
    [ ! -f "$SRC" ] && fail "aisubs.lua not found at $SRC"

    echo ""
    echo "Installing VLC extension..."
    echo ""

    if [ "$OS" = "linux" ]; then
        # VLC 4.x (system)
        install_to "/usr/lib/x86_64-linux-gnu/vlc/libexec/vlc/lua/extensions" true
        # VLC 3.x (system — various distros)
        install_to "/usr/lib/vlc/lua/extensions" true
        install_to "/usr/lib64/vlc/lua/extensions" true
        install_to "/usr/share/vlc/lua/extensions" true
        # Snap
        [ -d "$HOME/snap/vlc" ] && \
            install_to "$HOME/snap/vlc/current/.local/share/vlc/lua/extensions"
        # Flatpak
        [ -d "$HOME/.var/app/org.videolan.VLC" ] && \
            install_to "$HOME/.var/app/org.videolan.VLC/data/vlc/lua/extensions"
        # User-level fallback
        install_to "$HOME/.local/share/vlc/lua/extensions"

    elif [ "$OS" = "macos" ]; then
        install_to "$HOME/Library/Application Support/org.videolan.vlc/lua/extensions"

    elif [ "$OS" = "windows" ]; then
        # Git Bash / MSYS2 on Windows
        local appdata="${APPDATA:-$HOME/AppData/Roaming}"
        install_to "$appdata/vlc/lua/extensions"
    fi

    echo ""
    if [ "$INSTALLED" -eq 0 ]; then
        warn "No VLC extension directory found."
        echo "  Copy aisubs.lua manually to your VLC lua/extensions folder."
        exit 1
    fi
}

# ── Install-only mode ────────────────────────────────────────

if [ "${1:-}" = "--install" ]; then
    install_vlc_extension
    install_python_backend
    echo "Done! Restart VLC and check View > AI Subs Generator"
    exit 0
fi

# ── Full setup ───────────────────────────────────────────────

echo ""
echo "  vlc-ai-subs setup"
echo "  ─────────────────"
echo ""

# 1. Check Python
info "Checking Python..."
check_python
ok "Found $($PYTHON --version)"

# 2. Ensure venv module is available
if ! "$PYTHON" -m venv --help &>/dev/null; then
    if [ "$OS" = "linux" ]; then
        info "Installing python3-venv..."
        PY_MINOR=$("$PYTHON" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
        sudo apt-get install -y "python${PY_MINOR}-venv" 2>/dev/null || \
        sudo apt-get install -y python3-venv 2>/dev/null || \
        sudo dnf install -y python3-pip 2>/dev/null || \
        sudo pacman -S --noconfirm python 2>/dev/null || \
        fail "Could not install python3-venv. Install it manually and re-run."
    elif [ "$OS" = "macos" ]; then
        fail "Python venv module not found. Reinstall Python: brew install python3"
    fi
fi

# 3. Create virtual environment
if [ ! -d "$VENV_DIR" ]; then
    info "Creating virtual environment..."
    "$PYTHON" -m venv "$VENV_DIR"
    ok "Virtual environment created"
else
    ok "Virtual environment already exists"
fi

# Resolve pip/python inside venv (cross-platform)
if [ -f "$VENV_DIR/bin/pip" ]; then
    VENV_PIP="$VENV_DIR/bin/pip"
    VENV_PYTHON="$VENV_DIR/bin/python3"
elif [ -f "$VENV_DIR/Scripts/pip.exe" ]; then
    VENV_PIP="$VENV_DIR/Scripts/pip.exe"
    VENV_PYTHON="$VENV_DIR/Scripts/python.exe"
else
    fail "Could not find pip in virtual environment"
fi

# 4. Install faster-whisper
info "Installing faster-whisper (this may take a few minutes)..."
"$VENV_PIP" install --quiet --upgrade pip
"$VENV_PIP" install --quiet faster-whisper
"$VENV_PYTHON" -c "from faster_whisper import WhisperModel; print('  ✓ faster-whisper installed')"

# 5. Install VLC extension + Python backend
install_vlc_extension
install_python_backend

echo ""
echo "  Setup complete!"
echo ""
echo "  1. Restart VLC"
echo "  2. Go to View > AI Subs Generator"
echo "  3. Play a video and click Generate"
echo ""
