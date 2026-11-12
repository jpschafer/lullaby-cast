"""The ffmpeg command that turns PCM on stdin into the Icecast stream.

This is the only place the encoder is defined. A future HLS/visualizer
output becomes another output branch here; the synth side never changes.
"""

from __future__ import annotations

from urllib.parse import quote


def icecast_url(cfg, redact=False) -> str:
    password = "****" if redact else quote(cfg.source_password, safe="")
    return f"icecast://source:{password}@{cfg.icecast_host}:{cfg.icecast_port}{cfg.icecast_mount}"


def ffmpeg_command(cfg, redact=False) -> list:
    return [
        "ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "warning",
        # Input: raw PCM from the synth.
        "-f", "s16le", "-ar", str(cfg.sample_rate), "-ch_layout", "stereo", "-i", "pipe:0",
        # Output: MP3 to Icecast.
        "-c:a", "libmp3lame", "-b:a", cfg.mp3_bitrate,
        "-content_type", "audio/mpeg", "-ice_name", "lullaby-cast",
        "-f", "mp3", icecast_url(cfg, redact=redact),
    ]
