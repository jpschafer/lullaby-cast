"""Run from synth/:  python -m unittest discover -s tests"""

import tempfile
import unittest
from pathlib import Path

import mido
import numpy as np

from lullaby.clock import UnpacedClock
from lullaby.midi import find_midi_files, load_events
from lullaby.output import OutputFinished, PcmOutput
from lullaby.player import Player

SR = 1000  # tiny sample rate keeps frame math readable


def write_midi(path):
    """Notes at 0 s and 0.5 s at 120 bpm, then tempo halves at 1.0 s, so a
    note 480 ticks later lands at 2.0 s and
    its note-off 480 ticks after that at 3.0 s. Notes are split across two tracks."""
    mid = mido.MidiFile(ticks_per_beat=480)
    conductor = mido.MidiTrack([
        mido.MetaMessage("set_tempo", tempo=500000, time=0),
        mido.MetaMessage("set_tempo", tempo=1000000, time=960),
    ])
    notes = mido.MidiTrack([
        mido.Message("note_on", note=60, velocity=80, time=0),
        mido.Message("note_on", note=62, velocity=80, time=480),
        mido.Message("note_on", note=64, velocity=80, time=960),
        mido.Message("note_off", note=64, time=480),
    ])
    mid.tracks += [conductor, notes]
    mid.save(path)


class FakeSynth:
    def __init__(self):
        self.frame = 0
        self.handled = []  # (frame, message type, note)
        self.resets = 0

    def reset(self, cut=True):
        self.resets += 1

    def handle(self, msg):
        self.handled.append((self.frame, msg.type, getattr(msg, "note", None)))

    def render(self, frames):
        self.frame += frames
        return np.zeros(frames * 2, dtype=np.int16)


class CollectStream:
    def __init__(self):
        self.bytes = 0

    def write(self, data):
        self.bytes += len(data)

    def flush(self):
        pass


def make_player(max_seconds, block=64, **kwargs):
    synth = FakeSynth()
    stream = CollectStream()
    out = PcmOutput(UnpacedClock(SR, 0.1), stream=stream, max_frames=int(max_seconds * SR))
    return Player(synth, out, SR, block_frames=block, gap_seconds=1.0, **kwargs), synth, stream


class MidiTests(unittest.TestCase):
    def test_tempo_changes_and_track_merge(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d, "song.MID")
            write_midi(path)
            times = [(round(e.time, 6), e.message.note) for e in load_events(path)]
        self.assertEqual(times, [(0.0, 60), (0.5, 62), (2.0, 64), (3.0, 64)])

    def test_find_midi_files_ignores_case_hidden_and_other_files(self):
        with tempfile.TemporaryDirectory() as d:
            for name in ("b.Mid", "a.midi", "sub/c.MID", ".hidden.mid", "notes.txt"):
                Path(d, name).parent.mkdir(exist_ok=True)
                Path(d, name).write_bytes(b"")
            names = [p.name for p in find_midi_files(d)]
        self.assertEqual(names, ["a.midi", "b.Mid", "c.MID"])


class PlayerTests(unittest.TestCase):
    def test_events_land_on_exact_frames_and_gap_follows(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d, "song.mid")
            write_midi(path)
            player, synth, _ = make_player(max_seconds=7)
            with self.assertRaises(OutputFinished):
                player.loop_file(path, d)
        first_play = synth.handled[:4]
        self.assertEqual([f for f, _, _ in first_play], [0, 500, 2000, 3000])
        # Second play starts after the 1 s gap: 3000 + 1000.
        self.assertEqual(synth.handled[4][0], 4000)
        self.assertGreaterEqual(synth.resets, 2)

    def test_missing_folder_streams_silence_instead_of_stopping(self):
        player, synth, stream = make_player(max_seconds=5)
        with self.assertLogs("lullaby.player", "ERROR"), self.assertRaises(OutputFinished):
            player.loop_file(None, "/nonexistent")
        # Stops at the first whole block past 5 s.
        self.assertGreaterEqual(stream.bytes, 5 * SR * 4)
        self.assertLess(stream.bytes, (5 * SR + 64) * 4)
        self.assertEqual(synth.handled, [])

    def test_corrupt_file_logs_and_streams_silence(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d, "bad.mid")
            path.write_bytes(b"not a midi file")
            player, _, stream = make_player(max_seconds=3)
            with self.assertLogs("lullaby.player", "ERROR"), self.assertRaises(OutputFinished):
                player.loop_file(path, d)
        self.assertGreater(stream.bytes, 0)


if __name__ == "__main__":
    unittest.main()
