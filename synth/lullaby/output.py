"""Writes paced s16le PCM to stdout and keeps a heartbeat file fresh."""

from __future__ import annotations

import logging
import os
import sys
import time

log = logging.getLogger(__name__)

CHANNELS = 2


class PcmOutput:
    def __init__(self, pacer, heartbeat_path=None, stream=None):
        self.pacer = pacer
        self.heartbeat_path = heartbeat_path
        self.stream = stream if stream is not None else sys.stdout.buffer
        self._last_beat = None

    def write(self, block) -> None:
        """Write one block of interleaved stereo int16 samples (numpy array)."""
        frames = len(block) // CHANNELS
        self.pacer.before_write(frames)
        try:
            self.stream.write(block.tobytes())
            self.stream.flush()
        except BrokenPipeError:
            log.error("encoder closed the pipe (ffmpeg exited?); stopping")
            raise
        self._beat()

    def _beat(self) -> None:
        if not self.heartbeat_path:
            return
        now = time.monotonic()
        if self._last_beat is not None and now - self._last_beat < 1.0:
            return
        self._last_beat = now
        try:
            with open(self.heartbeat_path, "a"):
                os.utime(self.heartbeat_path)
        except OSError as e:
            log.error("cannot update heartbeat %s: %s", self.heartbeat_path, e)
