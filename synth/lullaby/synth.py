"""FluidSynth in-process and headless: MIDI messages in, PCM blocks out."""

from __future__ import annotations

import logging

import fluidsynth
import numpy as np

log = logging.getLogger(__name__)

PERCUSSION_CHANNEL = 9  # MIDI channel 10
CC_BANK_SELECT = (0, 32)
CC_ALL_SOUND_OFF = 120
CC_RESET_CONTROLLERS = 121


class Synth:
    def __init__(self, soundfont, sample_rate, gain, force_preset=None, mute_percussion=True):
        """force_preset: (bank, preset) used on every melodic channel, or None
        to honor the file's program changes."""
        self.force_preset = force_preset
        self.mute_percussion = mute_percussion
        # No fs.start(): FluidSynth never opens an audio driver.
        self._fs = fluidsynth.Synth(samplerate=float(sample_rate), gain=gain)
        self._sfid = self._fs.sfload(soundfont)
        if self._sfid == -1:
            raise RuntimeError(f"FluidSynth could not load SoundFont {soundfont}")
        if force_preset:
            bank, preset = force_preset
            name = self._fs.sfpreset_name(self._sfid, bank, preset)
            if not name:
                raise RuntimeError(f"{soundfont} has no preset {bank}:{preset} (FORCE_PRESET)")
            log.info("using preset %d:%d (%s) on all melodic channels", bank, preset, name)
        self.reset()

    def reset(self, cut=True) -> None:
        """Restore starting programs and controllers. With `cut`, also stop
        all sound at once (before songs, after errors); without, notes
        already released ring out naturally."""
        for ch in range(16):
            if cut:
                self._fs.cc(ch, CC_ALL_SOUND_OFF, 0)
            self._fs.cc(ch, CC_RESET_CONTROLLERS, 0)
            if ch == PERCUSSION_CHANNEL:
                self._fs.program_select(ch, self._sfid, 128, 0)
            elif self.force_preset:
                self._fs.program_select(ch, self._sfid, *self.force_preset)
            else:
                self._fs.program_select(ch, self._sfid, 0, 0)

    def handle(self, msg) -> None:
        """Apply one mido channel message."""
        t = msg.type
        if t in ("note_on", "note_off") and self.mute_percussion and msg.channel == PERCUSSION_CHANNEL:
            return
        if t == "note_on":
            self._fs.noteon(msg.channel, msg.note, msg.velocity)
        elif t == "note_off":
            self._fs.noteoff(msg.channel, msg.note)
        elif t == "control_change":
            if self.force_preset and msg.control in CC_BANK_SELECT and msg.channel != PERCUSSION_CHANNEL:
                return
            self._fs.cc(msg.channel, msg.control, msg.value)
        elif t == "program_change":
            if self.force_preset and msg.channel != PERCUSSION_CHANNEL:
                return
            self._fs.program_change(msg.channel, msg.program)
        elif t == "pitchwheel":
            self._fs.pitch_bend(msg.channel, msg.pitch)
        # Aftertouch and anything else: ignored.

    def render(self, frames: int):
        """Render `frames` frames of interleaved stereo int16."""
        return np.asarray(self._fs.get_samples(frames), dtype=np.int16)

    def close(self) -> None:
        self._fs.delete()
