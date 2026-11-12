"""Turns songs into one continuous PCM stream.

Events are applied at their exact sample position. Between songs, and
whenever something goes wrong, the synth keeps rendering with no notes,
which is silence (after any reverb tail) and keeps bytes flowing.
"""

from __future__ import annotations

import logging
from pathlib import Path

from .midi import find_midi_files, load_events
from .output import OutputFinished

log = logging.getLogger(__name__)

# How long to stream silence before looking again after a failure.
RETRY_SECONDS = 30


class Player:
    def __init__(self, synth, out, sample_rate, block_frames, gap_seconds):
        self.synth = synth
        self.out = out
        self.sample_rate = sample_rate
        self.block_frames = block_frames
        self.gap_seconds = gap_seconds

    def render(self, frames: int) -> None:
        while frames > 0:
            n = min(frames, self.block_frames)
            self.out.write(self.synth.render(n))
            frames -= n

    def silence(self, seconds: float) -> None:
        self.render(int(seconds * self.sample_rate))

    def play_song(self, path) -> None:
        # Parse first, so a bad file fails before anything is cut off.
        events = load_events(path)
        length = events[-1].time if events else 0.0
        log.info("playing %s (%.1fs, %d events)", Path(path).name, length, len(events))
        self.synth.reset()
        pos = 0  # frames since song start
        for event in events:
            target = round(event.time * self.sample_rate)
            if target > pos:
                self.render(target - pos)
                pos = target
            self.synth.handle(event.message)

    def loop_file(self, midi_file, midi_dir) -> None:
        """Play one file over and over with a gap between. Never returns.

        `midi_file` may be None: then the first MIDI file in `midi_dir` is
        used, looked up again each time so files can be added live.
        """
        while True:
            path = Path(midi_file) if midi_file else next(iter(find_midi_files(midi_dir)), None)
            if path is None:
                log.error("no MIDI files in %s; streaming silence, looking again in %ds",
                          midi_dir, RETRY_SECONDS)
                self.silence(RETRY_SECONDS)
                continue
            try:
                self.play_song(path)
            except (OutputFinished, BrokenPipeError):
                raise
            except Exception:
                log.exception("failed to play %s; streaming silence, retrying in %ds",
                              path, RETRY_SECONDS)
                self.synth.reset()
                self.silence(RETRY_SECONDS)
                continue
            self.silence(self.gap_seconds)
