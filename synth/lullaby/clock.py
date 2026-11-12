"""Keeps rendering within a small lead of the wall clock.

Audio time (frames written / sample rate) is the timeline everything is
scheduled on. The pacer only makes sure audio time never runs more than
`lead_seconds` ahead of real time, so an effect rendered now is heard
about now (plus Icecast/Cast buffering).
"""

from __future__ import annotations

import logging
import time

log = logging.getLogger(__name__)


class Pacer:
    def __init__(self, sample_rate, lead_seconds, max_behind_seconds=2.0,
                 clock=time.monotonic, sleep=time.sleep):
        self.sample_rate = sample_rate
        self.lead = lead_seconds
        self.max_behind = max_behind_seconds
        self._clock = clock
        self._sleep = sleep
        self._anchor = None  # wall time at which audio time was 0
        self.frames = 0

    @property
    def audio_time(self) -> float:
        """Seconds of audio produced so far."""
        return self.frames / self.sample_rate

    def before_write(self, frames: int) -> None:
        """Block until `frames` more frames may be written."""
        now = self._clock()
        if self._anchor is None:
            self._anchor = now
        due = self._anchor + self.audio_time - self.lead
        if due > now:
            self._sleep(due - now)
        elif now - due - self.lead > self.max_behind:
            # Fell behind (pipe stalled, machine paused). Re-anchor instead
            # of rendering a burst to catch up.
            behind = now - due - self.lead
            log.warning("rendering fell %.1fs behind real time; re-anchoring clock", behind)
            self._anchor = now - self.audio_time
        self.frames += frames


class UnpacedClock(Pacer):
    """Renders as fast as possible (offline rendering, tests)."""

    def before_write(self, frames: int) -> None:
        self.frames += frames
