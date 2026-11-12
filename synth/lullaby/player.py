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
# How often to check for a listener while idle.
IDLE_CHECK_SECONDS = 0.5


class SessionEnded(Exception):
    """Raised mid-render once the session's listeners are gone."""


def in_order(library, history):
    """Placeholder chooser: the file after the last one played, wrapping."""
    if not history:
        return library[0]
    last = str(history[-1]).lower()
    return next((p for p in library if str(p).lower() > last), library[0])


class Player:
    def __init__(self, synth, out, sample_rate, block_frames, gap_seconds, session_active=None):
        self.synth = synth
        self.out = out
        self.sample_rate = sample_rate
        self.block_frames = block_frames
        self.gap_seconds = gap_seconds
        # Callable: is someone listening? Default: always.
        self.session_active = session_active or (lambda: True)
        self._in_session = False

    def render(self, frames: int) -> None:
        while frames > 0:
            if self._in_session and not self.session_active():
                raise SessionEnded
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

    def _play_or_recover(self, path) -> bool:
        """Play one song; on failure log it and stream silence. True if it played."""
        try:
            self.play_song(path)
            return True
        except (OutputFinished, BrokenPipeError, SessionEnded):
            raise
        except Exception:
            log.exception("failed to play %s; streaming silence, moving on in %ds",
                          path, RETRY_SECONDS)
            self.synth.reset()
            self.silence(RETRY_SECONDS)
            return False

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
            if self._play_or_recover(path):
                self.silence(self.gap_seconds)

    def loop_playlist(self, midi_dir, choose_next_song=in_order) -> None:
        """Stream silence until someone listens, then run a session. Never returns."""
        while True:
            if self.session_active():
                self._run_session(midi_dir, choose_next_song)
            else:
                self.silence(IDLE_CHECK_SECONDS)

    def _run_session(self, midi_dir, choose_next_song) -> None:
        started = self.out.pacer.audio_time
        history = []  # every song attempted this session, in order
        log.info("session started")
        self._in_session = True
        try:
            while True:
                library = find_midi_files(midi_dir)
                if not library:
                    log.error("no MIDI files in %s; streaming silence, looking again in %ds",
                              midi_dir, RETRY_SECONDS)
                    self.silence(RETRY_SECONDS)
                    continue
                path = choose_next_song(library, history)
                if path is None:
                    log.info("no next song; streaming silence until the session ends")
                    while True:
                        self.silence(IDLE_CHECK_SECONDS)
                history.append(path)
                if self._play_or_recover(path):
                    self.silence(self.gap_seconds)
        except SessionEnded:
            self.synth.reset()
            minutes = (self.out.pacer.audio_time - started) / 60
            log.info("session ended after %.1f min, %d song(s)", minutes, len(history))
        finally:
            self._in_session = False
