"""Stage-1 test tone: soft alternating notes with rendered silence between.

The gaps are written as real zero samples, the same way the synth will
fill time between songs, so the stream never pauses at the byte level.
"""

from __future__ import annotations

import numpy as np

AMPLITUDE = 0.2           # of full scale; keep it gentle
NOTE_SECONDS = 1.0
GAP_SECONDS = 1.0
FADE_SECONDS = 0.02       # avoids clicks at note edges
FREQUENCIES = (440.0, 659.25)  # A4, E5


def tone_blocks(sample_rate, block_frames):
    """Yield interleaved stereo int16 blocks forever."""
    period = int((NOTE_SECONDS + GAP_SECONDS) * sample_rate)
    note_len = int(NOTE_SECONDS * sample_rate)
    fade = int(FADE_SECONDS * sample_rate)
    frame = 0
    while True:
        n = np.arange(frame, frame + block_frames)
        pos = n % period
        which = (n // period) % len(FREQUENCIES)
        freq = np.asarray(FREQUENCIES)[which]
        envelope = np.clip(np.minimum(pos, note_len - pos) / fade, 0.0, 1.0)
        mono = AMPLITUDE * envelope * np.sin(2 * np.pi * freq * n / sample_rate)
        mono = (mono * 32767).astype(np.int16)
        yield np.repeat(mono, 2)
        frame += block_frames
