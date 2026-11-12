"""Between-song interludes in the next song's key, so the gap between tunes
isn't dead silence. Two styles:

  phrase  a short tune: "da da da da, duh dah dah" (PHRASE)
  chords  broken chords over I-IV-I-V, ending on V so the song resolves it

The key is estimated with the Krumhansl-Schmuckler method: how long each
pitch class sounds in the song, correlated against the Krumhansl-Kessler
major and minor key profiles in all 12 transpositions.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

import mido
import numpy as np

from .midi import MidiEvent

PERCUSSION_CHANNEL = 9
NAMES = ("C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B")
MAJOR_PROFILE = (6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88)
MINOR_PROFILE = (6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17)

STYLES = ("chords", "phrase")  # also the order "alternate" takes turns in

# The phrase, as (scale degree, beats): "da da da da, duh dah dah".
# Degree 1 is the tonic; 8 is the tonic an octave up. Edit freely.
PHRASE = ((1, 0.5), (2, 0.5), (3, 0.5), (4, 0.5), (5, 1), (3, 1), (1, 2))
# Broken chords: scale degrees of each bar's chord root. Each bar plays
# root, 3rd, 5th, octave, 5th, 3rd in eighth notes; the last bar stops at
# the octave and lets the chord ring.
PROGRESSION = (1, 4, 1, 5)
TEMPO_BPM = 72
LOWEST_TONIC = 72      # C5: tonic placed in 72-83, music-box register
VELOCITY_ACCENT = 54   # first note and the long notes
VELOCITY = 44
CHANNEL = 0
MAJOR_SCALE = (0, 2, 4, 5, 7, 9, 11)
MINOR_SCALE = (0, 2, 3, 5, 7, 8, 10)


@dataclass(frozen=True)
class Key:
    tonic: int    # pitch class, 0 = C
    minor: bool

    def __str__(self) -> str:
        return f"{NAMES[self.tonic]} {'minor' if self.minor else 'major'}"


def detect_key(events):
    """Estimate the key of a song's events, or None if it has no notes."""
    weights = np.zeros(12)
    started = defaultdict(list)  # (channel, note) -> start times
    for event in events:
        msg = event.message
        if msg.type not in ("note_on", "note_off") or msg.channel == PERCUSSION_CHANNEL:
            continue
        key = (msg.channel, msg.note)
        if msg.type == "note_on" and msg.velocity > 0:
            started[key].append(event.time)
        elif started[key]:
            weights[msg.note % 12] += event.time - started[key].pop(0)
    if not weights.any():
        return None
    best, best_score = None, -2.0
    for minor, profile in ((False, MAJOR_PROFILE), (True, MINOR_PROFILE)):
        for tonic in range(12):
            score = np.corrcoef(weights, np.roll(profile, tonic))[0, 1]
            if score > best_score:
                best, best_score = Key(tonic, minor), score
    return best


def _pitch(key, degree):
    """MIDI note for a scale degree (1 = tonic, 8 = tonic an octave up)."""
    scale = MINOR_SCALE if key.minor else MAJOR_SCALE
    octave, step = divmod(degree - 1, 7)
    return LOWEST_TONIC + key.tonic + 12 * octave + scale[step]


def _phrase(key, beat):
    notes, t = [], 0.0
    for i, (degree, beats) in enumerate(PHRASE):
        velocity = VELOCITY_ACCENT if i == 0 or beats >= 1 else VELOCITY
        notes.append((t, beats * beat, _pitch(key, degree), velocity))
        t += beats * beat
    return notes


def _chords(key, beat):
    eighth = beat / 2
    notes, t = [], 0.0
    for bar, degree in enumerate(PROGRESSION):
        root = _pitch(key, degree)
        if root - _pitch(key, 1) > 6:
            root -= 12  # keep chords near the tonic (V sits below it)
        third = root + _pitch(key, degree + 2) - _pitch(key, degree)
        if degree == 5:
            third = root + 4  # major V in minor keys too, so it leads home
        fifth = root + 7
        figure = (root, third, fifth, root + 12, fifth, third)
        last_bar = bar == len(PROGRESSION) - 1
        if last_bar:
            figure = figure[:4]
        for i, note in enumerate(figure):
            # In the last bar every note holds to the end, so the chord rings.
            length = eighth * (len(figure) - i) if last_bar else eighth * 1.5
            notes.append((t, length, note, VELOCITY_ACCENT if i == 0 else VELOCITY))
            t += eighth
    return notes


def interlude_events(key, style="phrase"):
    """The interlude in `key` as MidiEvents starting at 0 s; the song starts
    after the last release."""
    beat = 60.0 / TEMPO_BPM
    notes = _chords(key, beat) if style == "chords" else _phrase(key, beat)
    events = []
    for start, length, note, velocity in notes:
        events.append((start, mido.Message("note_on", channel=CHANNEL, note=note, velocity=velocity)))
        events.append((start + length, mido.Message("note_off", channel=CHANNEL, note=note)))
    events.sort(key=lambda e: (e[0], e[1].type == "note_on"))  # releases first
    return [MidiEvent(time, msg) for time, msg in events]
