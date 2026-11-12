"""Run from synth/:  python -m unittest discover -s tests"""

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from lullaby import mechanism
from lullaby.output import OutputFinished
from test_player import SR, make_player, write_midi
from test_playlist import write_song


def mech(**hooks):
    """The placeholder mechanism with some hooks swapped out."""
    m = SimpleNamespace(**vars(mechanism))
    for name, fn in hooks.items():
        setattr(m, name, fn)
    return m


def note_frames(synth, kind="note_on"):
    return [(frame, note) for frame, k, note in synth.handled if k == kind]


class HookTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.song = Path(self.dir.name, "song.mid")
        write_midi(self.song)  # note_ons at 0, 0.5, 2.0 s; last note_off at 3.0 s

    def tearDown(self):
        self.dir.cleanup()

    def play_once(self, m, max_seconds=4.5, **kwargs):
        player, synth, _ = make_player(max_seconds=max_seconds, mechanism=m, **kwargs)
        try:
            player.loop_file(self.song, self.dir.name)
        except OutputFinished:
            pass
        return synth

    def test_placeholders_change_nothing(self):
        synth = self.play_once(mechanism)
        self.assertEqual(note_frames(synth)[:3], [(0, 60), (500, 62), (2000, 64)])

    def test_scale_time_stretches_gaps(self):
        synth = self.play_once(mech(scale_time=lambda d, ctx: d * 2), max_seconds=7)
        self.assertEqual(note_frames(synth)[:3], [(0, 60), (1000, 62), (4000, 64)])
        self.assertEqual(note_frames(synth, "note_off")[0], (6000, 64))

    def test_scale_time_sees_song_and_session_position(self):
        seen = []

        def scale(delta, ctx):
            seen.append((round(ctx.song_time, 3), round(ctx.song_position, 3), ctx.song.name))
            return delta * 2
        self.play_once(mech(scale_time=scale), max_seconds=7)
        self.assertEqual(seen[:3], [(0.0, 0.0, "song.mid"), (0.5, 1.0, "song.mid"),
                                    (2.0, 4.0, "song.mid")])

    def test_shape_note_moves_note_and_its_release_together(self):
        def shape(note, ctx):
            return replace(note, velocity=200, offset=0.03 if note.note == 64 else -0.02)
        synth = self.play_once(mech(shape_note=shape))
        # First note can't go earlier than the song start; others move.
        self.assertEqual(note_frames(synth)[:3], [(0, 60), (480, 62), (2030, 64)])
        self.assertEqual(note_frames(synth, "note_off")[0], (3030, 64))

    def test_shape_note_offset_is_clamped_to_window(self):
        synth = self.play_once(mech(shape_note=lambda n, ctx: replace(n, offset=5.0)),
                               humanize_window=0.05)
        self.assertEqual(note_frames(synth)[1], (550, 62))

    def test_shape_note_none_drops_note_and_release(self):
        synth = self.play_once(mech(shape_note=lambda n, ctx: None if n.note == 64 else n))
        self.assertNotIn(64, [n for _, n in note_frames(synth)[:3]])
        self.assertNotIn(64, [n for _, n in note_frames(synth, "note_off")[:1]])

    def test_failing_hook_logs_once_and_music_continues(self):
        def broken(delta, ctx):
            raise ZeroDivisionError("oops")
        with self.assertLogs("lullaby.player", "ERROR") as logs:
            # Stop during the gap, before the song starts again.
            synth = self.play_once(mech(scale_time=broken), max_seconds=3.5)
        self.assertEqual(note_frames(synth)[:3], [(0, 60), (500, 62), (2000, 64)])
        tracebacks = [line for line in logs.output if "ZeroDivisionError" in line]
        self.assertEqual(len(tracebacks), 1)
        self.assertTrue(any("failed 3 times" in line for line in logs.output))

    def test_bad_return_values_fall_back(self):
        m = mech(scale_time=lambda d, ctx: -1, shape_note=lambda n, ctx: "loud")
        with self.assertLogs("lullaby.player", "ERROR"):
            synth = self.play_once(m)
        self.assertEqual(note_frames(synth)[:3], [(0, 60), (500, 62), (2000, 64)])


class ChooserTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        for name, note in (("a.mid", 60), ("b.mid", 62), ("c.mid", 64)):
            write_song(Path(self.dir.name, name), note)

    def tearDown(self):
        self.dir.cleanup()

    def run_playlist(self, m, seconds):
        player, synth, _ = make_player(max_seconds=seconds, mechanism=m, session_length=600.0)
        try:
            player.loop_playlist(self.dir.name)
        except OutputFinished:
            pass
        return [n for _, k, n in synth.handled if k == "note_on"]

    def test_chooser_gets_history_and_context(self):
        calls = []

        def choose(library, history, ctx):
            calls.append((len(library), len(history), ctx.songs_played, ctx.session_length))
            return library[-1]
        self.assertEqual(self.run_playlist(mech(choose_next_song=choose), 4.5), [64, 64, 64])
        self.assertEqual(calls[:2], [(3, 0, 0, 600.0), (3, 1, 1, 600.0)])

    def test_failing_or_invalid_chooser_falls_back_to_in_order(self):
        with self.assertLogs("lullaby.player", "ERROR"):
            notes = self.run_playlist(mech(choose_next_song=lambda lib, h, c: "/elsewhere.mid"), 4.5)
        self.assertEqual(notes, [60, 62, 64])


if __name__ == "__main__":
    unittest.main()
