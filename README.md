# vlc-ai-subs

VLC media player plugin that generates subtitles using OpenAI Whisper — works with any video, any language.

## Features

- **Any language** — Auto-detection or specify a language code
- **Translation** — Translate any language to English subtitles
- **5 model sizes** — From `tiny` (fastest) to `large` (most accurate)
- **VLC 3.x & 4.x** — Compatible with both versions
- **Cross-platform** — Windows, macOS, and Linux (native, snap, flatpak)

## Quick Start

### Linux / macOS

```bash
git clone https://github.com/voidrlm/vlc-ai-subs.git
cd vlc-ai-subs
./setup.sh
```

### Windows

```
git clone https://github.com/voidrlm/vlc-ai-subs.git
cd vlc-ai-subs
setup.bat
```

Then:

1. **Restart VLC**
2. Open a video
3. **View → AI Subs Generator**
4. Click **Generate**

## Requirements

- Python 3.8+
- VLC 3.x or 4.x
- ~150 MB disk space for the `base` model (downloaded on first use)

Dedicated gpu is recommended for models above `base`. Setup script should auto detect cuda and install the necessary libraries. If cuda is not available -> fallback to cpu. Models are downloaded automatically on first use.

## Models

| Model | Speed | Accuracy | RAM | Download |
|-------|-------|----------|-----|----------|
| `tiny` | Fastest | Basic | ~1 GB | ~75 MB |
| `base` | Fast | Good | ~1 GB | ~140 MB |
| `small` | Moderate | Better | ~2 GB | ~460 MB |
| `medium` | Slow | Great | ~5 GB | ~1.5 GB |
| `large` | Slowest | Best | ~10 GB | ~3 GB |

## Options

- **Language** — `auto` for detection, or a code like `en`, `es`, `fr`, `hi`, `ja`, `zh`, etc.
- **Task** — `Transcribe` (same language) or `Translate to English`
- **Audio Track** — `auto` (first track) or numeric index `0,1,2…` (maps to `ffmpeg -map 0:a:N`)
- **Audio Channel** — `auto` (mix to mono), `mono`, `left`, `right`, `center`, or numeric channel index

## Architecture

The codebase is split by responsibility so each file has a single purpose:

### Python backend (`src/aisubs/`)

| Module | Responsibility |
|--------|---------------|
| `constants.py` | Tunable segmentation constants (durations, char limits) |
| `models.py` | `Word` and `SubtitleSegment` dataclasses |
| `scoring.py` | Punctuation / silence scoring and duration/length penalties |
| `segmentation.py` | Boundary search, segment grouping, timing refinement |
| `formatting.py` | SRT timestamp formatting and line wrapping |
| `audio.py` | `ffmpeg` extraction for track/channel selection |
| `transcription.py` | `faster-whisper` model loading and streaming |
| `protocol.py` | JSON-line emit to stdout + temp file |
| `srt_writer.py` | SRT assembly helpers |
| `cli.py` | Argument parsing and orchestration (`main()`) |

### Launcher (`src/launcher/`)

| Module | Responsibility |
|--------|---------------|
| `python.py` | Locate bundled `venv` Python and `site-packages` |
| `cuda.py` | Discover NVIDIA libs and build `LD_LIBRARY_PATH` / `PATH` |
| `cli.py` | CLI entry that wires Python + env + `aisubs.py` spawn |

### VLC extension (`lua/`)

| Module | Responsibility |
|--------|---------------|
| `helpers.lua` | `shell_quote`, `is_windows`, `get_temp_file`, `parse_json`, `set_status` |
| `compat.lua` | VLC 3.x/4.x compatibility (`get_input_item`, `add_subtitle_track`, `get_media_path`) |
| `audio.lua` | `ffprobe` track probing and `get_audio_track`/`get_audio_channel` |
| `dialog.lua` | Dialog creation and widget wiring |
| `polling.lua` | Background spawn, `poll_progress` timer, and result processing |

Root shims (`aisubs.py`, `launch.py`, `aisubs.lua`, `boundaries.py`) are thin wrappers that preserve the public paths VLC and existing imports expect.

## Project Structure

```
vlc-ai-subs/
├── aisubs.lua              # VLC extension entry (loads lua/*.lua)
├── aisubs.py               # Python backend entry (imports src/aisubs/cli.py)
├── launch.py               # Launcher entry (imports src/launcher/cli.py)
├── boundaries.py           # Backwards-compat shim re-exporting src/aisubs/*
├── lua/
│   ├── helpers.lua
│   ├── compat.lua
│   ├── audio.lua
│   ├── dialog.lua
│   └── polling.lua
├── src/
│   ├── aisubs/
│   │   ├── __init__.py
│   │   ├── constants.py
│   │   ├── models.py
│   │   ├── scoring.py
│   │   ├── segmentation.py
│   │   ├── formatting.py
│   │   ├── audio.py
│   │   ├── transcription.py
│   │   ├── protocol.py
│   │   ├── srt_writer.py
│   │   └── cli.py
│   └── launcher/
│       ├── __init__.py
│       ├── python.py
│       ├── cuda.py
│       └── cli.py
├── setup.sh                # Setup & install (Linux / macOS)
├── setup.bat               # Setup & install (Windows)
├── LICENSE
└── README.md
```

## Manual Installation

If the setup script doesn't work for your system:

1. Install faster-whisper:
   ```bash
   python3 -m venv venv
   venv/bin/pip install faster-whisper        # Linux/macOS
   venv\Scripts\pip.exe install faster-whisper # Windows
   ```

2. Copy extension and Python backend:
   - **Lua** — `aisubs.lua` + `lua/` folder to your VLC extensions folder:
     - **Linux**: `~/.local/share/vlc/lua/extensions/`
     - **macOS**: `~/Library/Application Support/org.videolan.vlc/lua/extensions/`
     - **Windows**: `%APPDATA%\vlc\lua\extensions\`
   - **Python** — `aisubs.py`, `launch.py`, `boundaries.py`, `src/` (and `venv/` if present) to the data folder:
     - **Linux**: `~/.local/share/vlc-ai-subs/`
     - **macOS**: `~/Library/Application Support/vlc-ai-subs/`
     - **Windows**: `%APPDATA%\vlc-ai-subs\`
     - Flatpak: `~/.var/app/org.videolan.VLC/data/vlc-ai-subs/`

3. Restart VLC.

To update just the VLC extension + Python backend without reinstalling Python deps:
```bash
./setup.sh --install        # Linux/macOS
setup.bat --install         # Windows
```

## Development

```bash
# Python syntax check (no Whisper model needed)
python -m py_compile src/aisubs/*.py src/launcher/*.py aisubs.py launch.py boundaries.py

# Lua syntax check
luac -p aisubs.lua && luac -p lua/*.lua

# Run transcription directly
python aisubs.py /path/to/video.mp4 base auto transcribe
```

## Credits

Original idea and initial code by [voidrlm](https://github.com/voidrlm/vlc-ai-subs.git)

## License

MIT
