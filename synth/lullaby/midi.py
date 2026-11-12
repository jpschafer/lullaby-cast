"""MIDI files → timed events."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import mido

MIDI_EXTENSIONS = (".mid", ".midi")


@dataclass(frozen=True)
class MidiEvent:
    time: float  # seconds from the start of the song, as written in the file
    message: mido.Message


def is_midi_file(path: Path) -> bool:
    return (path.is_file() and not path.name.startswith(".")
            and path.suffix.lower() in MIDI_EXTENSIONS)


def find_midi_files(folder) -> list:
    """All MIDI files under `folder` (any depth, any extension case), sorted."""
    folder = Path(folder)
    if not folder.is_dir():
        return []
    files = [p for p in folder.rglob("*") if is_midi_file(p)]
    return sorted(files, key=lambda p: str(p.relative_to(folder)).lower())


def load_events(path) -> list:
    """Parse a MIDI file into channel events with absolute times.

    Tracks are merged and tempo changes applied (mido does both when
    iterating a MidiFile). Meta and sysex messages are dropped. Raises on
    unreadable files.
    """
    events = []
    t = 0.0
    for msg in mido.MidiFile(path, clip=True):
        t += msg.time
        if not msg.is_meta and msg.type != "sysex":
            events.append(MidiEvent(t, msg))
    return events
