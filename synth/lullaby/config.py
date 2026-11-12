"""Settings from the environment, checked up front so bad config fails loudly."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

MODES = ("tone",)
MP3_SAMPLE_RATES = (22050, 24000, 32000, 44100, 48000)
HEARTBEAT_PATH = "/tmp/lullaby-heartbeat"


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Config:
    icecast_host: str
    icecast_port: int
    icecast_mount: str
    source_password: str
    mode: str
    soundfont: str
    midi_dir: str
    sample_rate: int
    mp3_bitrate: str
    # How far audio may be rendered ahead of the wall clock.
    lead_seconds: float
    # Frames per rendered block; smaller = finer event timing.
    block_frames: int
    heartbeat_path: str

    @classmethod
    def from_env(cls, env=None) -> Config:
        env = os.environ if env is None else env
        errors = []

        def get(name, default=None):
            value = env.get(name, default)
            if value is None or value == "":
                errors.append(f"{name} is not set")
            return value

        def get_int(name, default):
            raw = get(name, str(default))
            try:
                return int(raw)
            except (TypeError, ValueError):
                errors.append(f"{name} must be an integer (got {raw!r})")
                return default

        def get_float(name, default):
            raw = get(name, str(default))
            try:
                return float(raw)
            except (TypeError, ValueError):
                errors.append(f"{name} must be a number (got {raw!r})")
                return default

        cfg = cls(
            icecast_host=get("ICECAST_HOST", "icecast"),
            icecast_port=get_int("ICECAST_PORT", 8000),
            icecast_mount=get("ICECAST_MOUNT", "/lullaby.mp3"),
            source_password=get("ICECAST_SOURCE_PASSWORD"),
            mode=get("SYNTH_MODE", "tone"),
            soundfont=get("SOUNDFONT", "/soundfonts/musicbox.sf2"),
            midi_dir=get("MIDI_DIR", "/midi"),
            sample_rate=get_int("SAMPLE_RATE", 44100),
            mp3_bitrate=get("MP3_BITRATE", "128k"),
            lead_seconds=get_float("LEAD_SECONDS", 0.25),
            block_frames=get_int("BLOCK_FRAMES", 512),
            heartbeat_path=env.get("HEARTBEAT_PATH", HEARTBEAT_PATH),
        )

        if cfg.mode and cfg.mode not in MODES:
            errors.append(f"SYNTH_MODE must be one of {MODES} (got {cfg.mode!r})")
        if cfg.icecast_mount and not cfg.icecast_mount.startswith("/"):
            errors.append(f"ICECAST_MOUNT must start with '/' (got {cfg.icecast_mount!r})")
        if cfg.sample_rate not in MP3_SAMPLE_RATES:
            errors.append(f"SAMPLE_RATE must be one of {MP3_SAMPLE_RATES} (got {cfg.sample_rate})")
        if cfg.mp3_bitrate and not re.fullmatch(r"\d+k", cfg.mp3_bitrate):
            errors.append(f"MP3_BITRATE must look like '128k' (got {cfg.mp3_bitrate!r})")
        if not 0.05 <= cfg.lead_seconds <= 5:
            errors.append(f"LEAD_SECONDS must be between 0.05 and 5 (got {cfg.lead_seconds})")
        if not 64 <= cfg.block_frames <= 8192:
            errors.append(f"BLOCK_FRAMES must be between 64 and 8192 (got {cfg.block_frames})")
        if cfg.source_password and cfg.source_password.startswith("change-me"):
            errors.append("ICECAST_SOURCE_PASSWORD still has the example value")

        if errors:
            raise ConfigError("invalid configuration:\n  - " + "\n  - ".join(errors))
        return cfg
