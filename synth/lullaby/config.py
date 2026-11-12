"""Settings from the environment, checked up front so bad config fails loudly."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

MODES = ("tone", "file", "playlist")
SYNTH_MODES = ("file", "playlist")  # modes that need FluidSynth and a SoundFont
SESSION_STARTS = ("listener", "always")
INTERLUDES = ("phrase", "chords", "alternate", "off")
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
    # One file to loop in "file" mode; None = first file in midi_dir.
    midi_file: str
    gain: float
    # (bank, preset) forced on every melodic channel, or None.
    force_preset: tuple
    mute_percussion: bool
    song_gap_seconds: float
    # "listener": a session runs while Icecast reports listeners.
    # "always": one endless session (local testing without Icecast).
    session_start: str
    session_grace_seconds: float
    # Passed to the mechanism hooks as ctx.session_length (seconds); None if unset.
    session_length: float
    # How far shape_note may move a note, in seconds.
    humanize_window: float
    # Interlude style before each song (see interlude.py), or None for silence.
    interlude: str
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

        def get_bool(name, default):
            raw = env.get(name, "").strip().lower()
            if raw == "":
                return default
            if raw in ("1", "true", "yes", "on"):
                return True
            if raw in ("0", "false", "no", "off"):
                return False
            errors.append(f"{name} must be true or false (got {raw!r})")
            return default

        def get_preset(name, default):
            raw = env.get(name, default).strip().lower()
            if raw in ("", "off", "none"):
                return None
            m = re.fullmatch(r"(\d+):(\d+)", raw)
            if not m or int(m.group(1)) > 128 or int(m.group(2)) > 127:
                errors.append(f"{name} must be bank:preset like 0:10, or off (got {raw!r})")
                return None
            return int(m.group(1)), int(m.group(2))

        cfg = cls(
            icecast_host=get("ICECAST_HOST", "icecast"),
            icecast_port=get_int("ICECAST_PORT", 8000),
            icecast_mount=get("ICECAST_MOUNT", "/lullaby.mp3"),
            source_password=get("ICECAST_SOURCE_PASSWORD"),
            mode=get("SYNTH_MODE", "playlist"),
            soundfont=get("SOUNDFONT", "/soundfonts/GeneralUser-GS.sf2"),
            midi_dir=get("MIDI_DIR", "/midi"),
            midi_file=env.get("MIDI_FILE") or None,
            gain=get_float("GAIN", 0.8),
            force_preset=get_preset("FORCE_PRESET", "0:10"),
            mute_percussion=get_bool("MUTE_PERCUSSION", True),
            song_gap_seconds=get_float("SONG_GAP_SECONDS", 2.0),
            session_start=get("SESSION_START", "listener"),
            session_grace_seconds=get_float("SESSION_GRACE_SECONDS", 20.0),
            session_length=(get_float("SESSION_MINUTES", 0) * 60) if env.get("SESSION_MINUTES") else None,
            humanize_window=get_float("HUMANIZE_WINDOW_MS", 50) / 1000,
            interlude=get("INTERLUDE", "alternate").strip().lower(),
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
        if not 0 < cfg.gain <= 10:
            errors.append(f"GAIN must be above 0 and at most 10 (got {cfg.gain})")
        if not 0 <= cfg.song_gap_seconds <= 600:
            errors.append(f"SONG_GAP_SECONDS must be between 0 and 600 (got {cfg.song_gap_seconds})")
        if cfg.session_start and cfg.session_start not in SESSION_STARTS:
            errors.append(f"SESSION_START must be one of {SESSION_STARTS} (got {cfg.session_start!r})")
        if not 0 <= cfg.session_grace_seconds <= 600:
            errors.append(f"SESSION_GRACE_SECONDS must be between 0 and 600 (got {cfg.session_grace_seconds})")
        if cfg.session_length is not None and cfg.session_length <= 0:
            errors.append("SESSION_MINUTES must be above 0, or empty")
        if not 0 <= cfg.humanize_window <= 0.5:
            errors.append(f"HUMANIZE_WINDOW_MS must be between 0 and 500 (got {cfg.humanize_window * 1000:g})")
        if cfg.interlude not in INTERLUDES:
            errors.append(f"INTERLUDE must be one of {INTERLUDES} (got {cfg.interlude!r})")
        if cfg.mode in SYNTH_MODES and cfg.soundfont and not os.path.isfile(cfg.soundfont):
            errors.append(f"SoundFont not found: {cfg.soundfont} (put it in the soundfonts "
                          f"folder and set SOUNDFONT to its path inside the container)")
        if cfg.source_password and cfg.source_password.startswith("change-me"):
            errors.append("ICECAST_SOURCE_PASSWORD still has the example value")

        if errors:
            raise ConfigError("invalid configuration:\n  - " + "\n  - ".join(errors))
        return cfg
