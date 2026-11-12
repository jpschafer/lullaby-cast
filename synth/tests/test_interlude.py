"""Run from synth/:  python -m unittest discover -s tests"""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import mido

from lullaby import mechanism
from lullaby.interlude import Key, detect_key, interlude_events
from lullaby.midi import MidiEvent
from lullaby.output import OutputFinished
from test_player import make_player
from test_playlist import write_song


def melody(notes, step=0.5):
    """Events for `notes` played one after another, `step` seconds each."""
    events = []
    for i, n in enumerate(notes):
        events.append(MidiEvent(i * step, mido.Message("note_on", note=n, velocity=80)))
        events.append(MidiEvent((i + 1) * step, mido.Message("note_off", note=n)))
    return events


def pitch_classes(events):
    return {e.message.note % 12 for e in events if e.message.type == "note_on"}


class KeyTests(unittest.TestCase):
    def test_major(self):
        # Twinkle Twinkle in C: C C G G A A G, F F E E D D C
        self.assertEqual(detect_key(melody([60, 60, 67, 67, 69, 69, 67, 67,
                                            65, 65, 64, 64, 62, 62, 60, 60])), Key(0, False))

    def test_minor(self):
        # A minor: tonic triad with the raised 7th
        self.assertEqual(detect_key(melody([57, 60, 64, 69, 68, 69, 64, 60, 57, 57])), Key(9, True))

    def test_percussion_and_empty_songs(self):
        drums = [MidiEvent(0, mido.Message("note_on", channel=9, note=36, velocity=90)),
                 MidiEvent(1, mido.Message("note_off", channel=9, note=36))]
        self.assertIsNone(detect_key(drums))
        self.assertIsNone(detect_key([]))


class InterludeTests(unittest.TestCase):
    def test_both_styles_stay_in_key(self):
        g_major = {7, 9, 11, 0, 2, 4, 6}
        for style in ("phrase", "chords"):
            self.assertLessEqual(pitch_classes(interlude_events(Key(7, False), style)), g_major, style)

    def test_minor_chords_use_major_dominant(self):
        notes = pitch_classes(interlude_events(Key(9, True), "chords"))
        self.assertIn(8, notes)        # G#, the raised 7th in V
        self.assertNotIn(1, notes)     # no C#: tonic chord stays minor

    def test_player_plays_interlude_then_song_with_flagged_context(self):
        with tempfile.TemporaryDirectory() as d:
            write_song(Path(d, "a.mid"), 60)          # C
            seen = []
            m = SimpleNamespace(**vars(mechanism))
            m.shape_note = lambda note, ctx: seen.append((note.note, ctx.interlude)) or note
            player, synth, _ = make_player(max_seconds=30, mechanism=m, interlude="alternate")
            with self.assertRaises(OutputFinished):
                player.loop_playlist(d)
        chords = [n for n, _, _ in [(e.message.note, 0, 0) for e in interlude_events(Key(0, False), "chords")
                                    if e.message.type == "note_on"]]
        phrase = [e.message.note for e in interlude_events(Key(0, False), "phrase")
                  if e.message.type == "note_on"]
        # First song: chords, then the song's note; second: phrase, then the song.
        expected = ([(n, True) for n in chords] + [(60, False)]
                    + [(n, True) for n in phrase] + [(60, False)])
        self.assertEqual(seen[:len(expected)], expected)


if __name__ == "__main__":
    unittest.main()
