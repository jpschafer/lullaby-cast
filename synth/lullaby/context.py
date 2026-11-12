"""What the mechanism hooks receive. Times are seconds of audio, which the
pacer keeps within a fraction of a second of wall-clock time."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class SessionContext:
    elapsed: float                   # seconds since this session started
    session_length: Optional[float]  # SESSION_MINUTES in seconds, or None if unset
    songs_played: int                # songs started so far this session


@dataclass(frozen=True)
class PlaybackContext:
    elapsed: float                   # seconds since this session started
    session_length: Optional[float]  # SESSION_MINUTES in seconds, or None if unset
    song: Path                       # file being played
    song_index: int                  # 0 for the session's first song, 1 for the next...
    song_length: float               # the file's own length in seconds (before scale_time)
    song_time: float                 # where we are in the file's timeline (before scale_time)
    song_position: float             # seconds of this song played so far (after scale_time)
    interlude: bool = False          # True during the short phrase played before `song`


@dataclass(frozen=True)
class NoteEvent:
    channel: int     # 0-15
    note: int        # MIDI note number, 60 = middle C
    velocity: int    # 1-127
    offset: float = 0.0  # seconds to move the note by; negative = earlier
