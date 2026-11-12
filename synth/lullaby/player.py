"""Turns songs into one continuous PCM stream.

Events are applied at their exact sample position. Between songs, and
whenever something goes wrong, the synth keeps rendering with no notes,
which is silence (after any reverb tail) and keeps bytes flowing.

Timing runs through the mechanism hooks (see mechanism.py): scale_time
decides each gap, shape_note may move a note by up to the humanize window,
so events go through a small queue that renders that far behind the
newest event.
"""

from __future__ import annotations

import heapq
import itertools
import logging
import math
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, replace
from pathlib import Path

from . import mechanism as default_mechanism
from .context import NoteEvent, PlaybackContext, SessionContext
from .interlude import STYLES, detect_key, interlude_events
from .midi import find_midi_files, load_events
from .output import OutputFinished

log = logging.getLogger(__name__)

# How long to stream silence before looking again after a failure.
RETRY_SECONDS = 30
# How often to check for a listener while idle.
IDLE_CHECK_SECONDS = 0.5


class SessionEnded(Exception):
    """Raised mid-render once the session's listeners are gone."""


class HookError(Exception):
    """A hook returned something the plumbing can't use."""


def in_order(library, history):
    """Fallback chooser: the file after the last one played, wrapping."""
    if not history:
        return library[0]
    last = str(history[-1]).lower()
    return next((p for p in library if str(p).lower() > last), library[0])


@dataclass
class _Session:
    start_frame: int
    history: list


class Player:
    def __init__(self, synth, out, sample_rate, block_frames, gap_seconds,
                 session_active=None, mechanism=None, humanize_window=0.05, session_length=None,
                 interlude=None):
        self.synth = synth
        self.out = out
        self.sample_rate = sample_rate
        self.block_frames = block_frames
        self.gap_seconds = gap_seconds
        # Callable: is someone listening? Default: always.
        self.session_active = session_active or (lambda: True)
        self.mechanism = mechanism or default_mechanism
        self.humanize_window = humanize_window
        self.session_length = session_length
        # None, or an interlude style to play before each song (interlude.py).
        self.interlude = interlude
        self._in_session = False
        self._hook_errors = Counter()

    # --- rendering -----------------------------------------------------

    @property
    def now(self) -> int:
        """Frames written so far."""
        return self.out.pacer.frames

    def render(self, frames: int) -> None:
        while frames > 0:
            if self._in_session and not self.session_active():
                raise SessionEnded
            n = min(frames, self.block_frames)
            self.out.write(self.synth.render(n))
            frames -= n

    def silence(self, seconds: float) -> None:
        self.render(int(seconds * self.sample_rate))

    def _flush(self, queue, upto) -> None:
        """Render up to and apply every queued event due at or before `upto`."""
        while queue and queue[0][0] <= upto:
            frame, _, msg = heapq.heappop(queue)
            if frame > self.now:
                self.render(frame - self.now)
            self.synth.handle(msg)

    # --- hooks ---------------------------------------------------------

    def _hook(self, name, fallback, *args, check=None):
        """Call mechanism.<name>; on any error log it (first time per song)
        and return `fallback`."""
        try:
            result = getattr(self.mechanism, name)(*args)
            return check(result) if check else result
        except (OutputFinished, BrokenPipeError, SessionEnded):
            raise
        except Exception:
            self._hook_errors[name] += 1
            if self._hook_errors[name] == 1:
                log.exception("mechanism.%s failed; using the unmodified value "
                              "(further failures this song are only counted)", name)
            return fallback

    def _report_hook_errors(self, path) -> None:
        for name, count in self._hook_errors.items():
            if count > 1:
                log.error("mechanism.%s failed %d times during %s", name, count, Path(path).name)
        self._hook_errors.clear()

    @staticmethod
    def _check_delta(value):
        value = float(value)
        if not math.isfinite(value) or value < 0:
            raise HookError(f"scale_time must return a finite number >= 0, got {value!r}")
        return value

    def _check_note(self, value):
        if value is None:
            return None
        if not isinstance(value, NoteEvent):
            raise HookError(f"shape_note must return a NoteEvent or None, got {value!r}")
        w = self.humanize_window
        return replace(value, velocity=max(1, min(127, int(value.velocity))),
                       offset=max(-w, min(w, float(value.offset))))

    # --- songs ---------------------------------------------------------

    def play_song(self, path, session) -> None:
        # Parse first, so a bad file fails before anything is cut off.
        events = load_events(path)
        length = events[-1].time if events else 0.0
        self.synth.reset()
        if self.interlude:
            key = detect_key(events)
            if key is not None:
                style = self.interlude
                if style == "alternate":
                    style = STYLES[(len(session.history) - 1) % len(STYLES)]
                log.info("interlude (%s) in %s", style, key)
                self._play_events(interlude_events(key, style), path, session, interlude=True)
                # Keep the interlude's last note ringing into the song.
                self.synth.reset(cut=False)
        log.info("playing %s (%.1fs, %d events)", Path(path).name, length, len(events))
        self._play_events(events, path, session)

    def _play_events(self, events, path, session, interlude=False) -> None:
        length = events[-1].time if events else 0.0
        sr = self.sample_rate
        window = round(self.humanize_window * sr)
        song_start = self.now
        song_index = len(session.history) - 1
        queue, seq = [], itertools.count()  # (frame, tiebreak, message)
        # Offsets (in frames) of sounding notes, so releases move with them.
        # None marks a dropped note whose release must be dropped too.
        sounding = defaultdict(deque)
        position = 0.0  # seconds of this song played (after scale_time)
        prev_time = 0.0

        def ctx(song_time):
            return PlaybackContext(
                elapsed=(self.now - session.start_frame) / sr, session_length=self.session_length,
                song=Path(path), song_index=song_index, song_length=length,
                song_time=song_time, song_position=position, interlude=interlude)

        try:
            for event in events:
                delta = event.time - prev_time
                if delta > 0:
                    position += self._hook("scale_time", delta, delta, ctx(prev_time),
                                           check=self._check_delta)
                prev_time = event.time
                frame = song_start + round(position * sr)
                msg = event.message
                offset = 0

                if msg.type == "note_on" and msg.velocity > 0:
                    note = NoteEvent(msg.channel, msg.note, msg.velocity)
                    shaped = self._hook("shape_note", note, note, ctx(event.time),
                                        check=self._check_note)
                    key = (msg.channel, msg.note)
                    if shaped is None:
                        sounding[key].append(None)
                        continue
                    offset = round(shaped.offset * sr)
                    sounding[key].append(offset)
                    msg = msg.copy(velocity=shaped.velocity)
                elif msg.type in ("note_on", "note_off"):
                    pending = sounding[(msg.channel, msg.note)]
                    offset = pending.popleft() if pending else 0
                    if offset is None:
                        continue

                # Nothing still to come can land before frame - window.
                self._flush(queue, frame - window)
                heapq.heappush(queue, (frame + offset, next(seq), msg))
            self._flush(queue, math.inf)
        finally:
            self._report_hook_errors(f"the interlude before {Path(path).name}" if interlude else path)

    def _play_or_recover(self, path, session) -> bool:
        """Play one song; on failure log it and stream silence. True if it played."""
        try:
            self.play_song(path, session)
            return True
        except (OutputFinished, BrokenPipeError, SessionEnded):
            raise
        except Exception:
            log.exception("failed to play %s; streaming silence, moving on in %ds",
                          path, RETRY_SECONDS)
            self.synth.reset()
            self.silence(RETRY_SECONDS)
            return False

    # --- loops ---------------------------------------------------------

    def loop_file(self, midi_file, midi_dir) -> None:
        """Play one file over and over with a gap between. Never returns.

        `midi_file` may be None: then the first MIDI file in `midi_dir` is
        used, looked up again each time so files can be added live.
        """
        session = _Session(self.now, [])
        while True:
            path = Path(midi_file) if midi_file else next(iter(find_midi_files(midi_dir)), None)
            if path is None:
                log.error("no MIDI files in %s; streaming silence, looking again in %ds",
                          midi_dir, RETRY_SECONDS)
                self.silence(RETRY_SECONDS)
                continue
            session.history.append(path)
            if self._play_or_recover(path, session):
                self.silence(self.gap_seconds)

    def loop_playlist(self, midi_dir) -> None:
        """Stream silence until someone listens, then run a session. Never returns."""
        while True:
            if self.session_active():
                self._run_session(midi_dir)
            else:
                self.silence(IDLE_CHECK_SECONDS)

    def _run_session(self, midi_dir) -> None:
        session = _Session(self.now, [])
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
                path = self._choose(library, session)
                if path is None:
                    log.info("no next song; streaming silence until the session ends")
                    while True:
                        self.silence(IDLE_CHECK_SECONDS)
                session.history.append(path)
                if self._play_or_recover(path, session):
                    self.silence(self.gap_seconds)
        except SessionEnded:
            self.synth.reset()
            minutes = (self.now - session.start_frame) / self.sample_rate / 60
            log.info("session ended after %.1f min, %d song(s)", minutes, len(session.history))
        finally:
            self._in_session = False

    def _choose(self, library, session):
        ctx = SessionContext(elapsed=(self.now - session.start_frame) / self.sample_rate,
                             session_length=self.session_length,
                             songs_played=len(session.history))
        fallback = in_order(library, session.history)

        def check(value):
            if value is None:
                return None
            value = Path(value)
            if value not in library:
                raise HookError(f"choose_next_song returned {value}, which is not in the library")
            return value

        path = self._hook("choose_next_song", fallback, list(library), tuple(session.history), ctx,
                          check=check)
        self._report_hook_errors("song selection")
        return path
