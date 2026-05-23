from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CONFIG = """\
# myflow config

anthropic_api_key = ""
openai_api_key = ""

# "openai" (Whisper API) or "local" (faster-whisper)
stt_engine = "openai"
local_whisper_model = "small"
# Language hint, e.g. "en", "es", "fr". Empty string = auto-detect.
language = "en"

# Push-to-talk: hold to record. Released = stop.
# Values use pynput key names: alt_r, alt_l, ctrl_r, ctrl_l, cmd, etc.
hotkey_push_to_talk = "alt_r"

# Hands-free toggle (chord). Press together to toggle continuous mode.
hotkey_handsfree = ["alt_r", "space"]

min_recording_seconds = 0.3
play_start_sound = true

# Cleanup model
cleanup_model = "claude-haiku-4-5"

# Mic device. Leave "" for the Windows default input.
# Can be a name substring (e.g. "DM40", "Jabra") or an integer index from
# sounddevice.query_devices().
input_device = ""
"""


def config_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "myflow"
    return Path.home() / ".config" / "myflow"


def config_path() -> Path:
    return config_dir() / "config.toml"


def history_path() -> Path:
    return config_dir() / "history.jsonl"


def log_path() -> Path:
    return config_dir() / "myflow.log"


@dataclass
class Config:
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    stt_engine: str = "openai"
    local_whisper_model: str = "base"
    language: str = "en"  # ISO code, or "" to auto-detect
    # sounddevice input device: int index, substring of device name, or "" for OS default
    input_device: str | int = ""
    hotkey_push_to_talk: str = "alt_r"
    hotkey_handsfree: list[str] = field(default_factory=lambda: ["alt_r", "space"])
    min_recording_seconds: float = 0.3
    play_start_sound: bool = True
    cleanup_model: str = "claude-haiku-4-5"


def ensure_config() -> Path:
    d = config_dir()
    d.mkdir(parents=True, exist_ok=True)
    p = config_path()
    if not p.exists():
        p.write_text(DEFAULT_CONFIG, encoding="utf-8")
    h = history_path()
    if not h.exists():
        h.touch()
    return p


def load() -> Config:
    p = ensure_config()
    with p.open("rb") as f:
        data = tomllib.load(f)
    cfg = Config()
    for k, v in data.items():
        if hasattr(cfg, k):
            setattr(cfg, k, v)
    # Env overrides for keys
    cfg.anthropic_api_key = cfg.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    cfg.openai_api_key = cfg.openai_api_key or os.environ.get("OPENAI_API_KEY", "")
    return cfg
