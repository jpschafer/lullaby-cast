"""Run from synth/:  python -m unittest discover -s tests"""

import tempfile
import unittest
from pathlib import Path

import mido

from lullaby.output import OutputFinished
from lullaby.player import in_order
from test_player import SR, make_player


def write_song(path, note, seconds=1.0):
    """One note held for `seconds` at 120 bpm (480 ticks = 0.5 s)."""
    mid = mido.MidiFile(ticks_per_beat=480)
    mid.tracks.append(mido.MidiTrack([
        mido.Message("note_on", note=note, velocity=80, time=0),
        mido.Message("note_off", note=note, time=int(seconds * 960)),
    ]))
    mid.save(path)


def first_notes(synth):
    return [note for _, kind, note in synth.handled if kind == "note_on"]


class InOrderTests(unittest.TestCase):
    def test_walks_library_and_wraps(self):
        lib = [Path("/m/a.mid"), Path("/m/b.mid"), Path("/m/c.mid")]
        self.assertEqual(in_order(lib, []), lib[0])
        self.assertEqual(in_order(lib, [lib[0]]), lib[1])
        self.assertEqual(in_order(lib, [lib[0], lib[1], lib[2]]), lib[0])

    def test_survives_last_song_being_deleted(self):
        lib = [Path("/m/a.mid"), Path("/m/c.mid")]
        self.assertEqual(in_order(lib, [Path("/m/b.mid")]), lib[1])


class PlaylistTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        for name, note in (("a.mid", 60), ("b.mid", 62), ("c.mid", 64)):
            write_song(Path(self.dir.name, name), note)

    def tearDown(self):
        self.dir.cleanup()

    def test_plays_every_song_in_order_then_wraps(self):
        # Each song is 1 s plus a 1 s gap.
        player, synth, _ = make_player(max_seconds=7.5)
        with self.assertRaises(OutputFinished):
            player.loop_playlist(self.dir.name)
        self.assertEqual(first_notes(synth), [60, 62, 64, 60])

    def test_idles_until_listener_then_starts_from_first_song(self):
        player, synth, _ = make_player(max_seconds=4)
        player.session_active = lambda: player.out.pacer.frames >= 2 * SR
        with self.assertRaises(OutputFinished):
            player.loop_playlist(self.dir.name)
        frame, _, note = synth.handled[0]
        self.assertEqual(note, 60)
        self.assertGreaterEqual(frame, 2 * SR)
        self.assertLess(frame, 2 * SR + SR // 2)

    def test_session_end_stops_mid_song_and_next_session_restarts(self):
        write_song(Path(self.dir.name, "a.mid"), 60, seconds=10)
        player, synth, _ = make_player(max_seconds=8)
        # Listening for 0-2 s, gone 2-4 s, back from 4 s.
        player.session_active = lambda: not (2 * SR <= player.out.pacer.frames < 4 * SR)
        with self.assertLogs("lullaby.player", "INFO") as logs, self.assertRaises(OutputFinished):
            player.loop_playlist(self.dir.name)
        self.assertEqual(first_notes(synth), [60, 60])
        self.assertTrue(any("session ended" in line for line in logs.output))

    def test_bad_file_is_skipped(self):
        Path(self.dir.name, "b.mid").write_bytes(b"garbage")
        player, synth, _ = make_player(max_seconds=40)
        with self.assertLogs("lullaby.player", "ERROR"), self.assertRaises(OutputFinished):
            player.loop_playlist(self.dir.name)
        self.assertEqual(first_notes(synth)[:2], [60, 64])

    def test_chooser_returning_none_streams_silence(self):
        player, synth, stream = make_player(max_seconds=3)
        with self.assertRaises(OutputFinished):
            player.loop_playlist(self.dir.name, choose_next_song=lambda lib, hist: None)
        self.assertEqual(synth.handled, [])
        self.assertGreater(stream.bytes, 0)


if __name__ == "__main__":
    unittest.main()
