"""The mechanism: the musical part, yours to write.

The plumbing calls the three hooks below while it plays. The placeholders
change nothing: songs in order, as written, at the file's own tempo.

If a hook raises, or returns something unusable, the error is logged with a
traceback (once per hook per song; repeats are counted) and the plumbing
uses the unmodified value, so the music keeps going.

Hooks run in the audio loop: keep them fast, and don't block or sleep.
Module-level variables persist for the life of the synth process (it is
restarted only if the pipeline fails), so they can hold state between calls.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .context import NoteEvent, PlaybackContext, SessionContext


def choose_next_song(library: list, history: tuple, ctx: SessionContext) -> Optional[Path]:
    """Pick the next song.

    Receives:
      library  every MIDI file in the folder right now (rescanned before each
               call), sorted by path, never empty
      history  songs started this session, oldest first, including any that
               failed to play
      ctx      elapsed time, SESSION_MINUTES, songs played (see context.py)

    Returns a Path from `library` to play next, or None to stop for the
    night: the stream stays connected and carries silence until the session
    ends.

    Placeholder: the folder in order, wrapping around.
    """
    if not history:
        return library[0]
    last = str(history[-1]).lower()
    return next((p for p in library if str(p).lower() > last), library[0])


def scale_time(delta: float, ctx: PlaybackContext) -> float:
    """Stretch or shrink the time between events (e.g. a spring winding down).

    Receives:
      delta  seconds from the previous event to the next one, as the file has
             it (tempo already applied). Called once per gap, when the gap
             begins, so `ctx` describes the moment you'll hear it. Chords
             (events at the same instant) don't produce a call.
      ctx    session and song position (see context.py)

    Returns the seconds to actually wait, >= 0. Returning 2 * delta plays
    that stretch at half speed. Note lengths stretch with it (note releases
    are events too); pitch is unaffected.

    Placeholder: unchanged.
    """
    return delta


def shape_note(note: NoteEvent, ctx: PlaybackContext) -> Optional[NoteEvent]:
    """Adjust each note as it's struck (e.g. humanization).

    Receives:
      note  channel, note number, velocity (1-127), and offset (always 0.0
            here); see context.py
      ctx   session and song position (see context.py)

    Returns the note with a new velocity and/or offset, e.g.
    dataclasses.replace(note, velocity=70, offset=-0.01), or None to drop
    it. Velocity is clamped to 1-127. The offset is in seconds (negative =
    earlier) and is clamped to +/- HUMANIZE_WINDOW_MS (default 50 ms). The
    note's release moves by the same offset, so its length is unchanged.

    Placeholder: unchanged.
    """
    return note
