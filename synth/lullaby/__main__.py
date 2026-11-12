"""Synth entry point: renders audio and writes s16le PCM to stdout.

    python -m lullaby                      # live, paced, to stdout (what the supervisor runs)
    python -m lullaby | ffplay -f s16le -ar 44100 -ch_layout stereo -
    python -m lullaby --wav out.wav --seconds 20   # offline, as fast as possible
    python -m lullaby --mode tone                  # test tone instead of MIDI
"""

from __future__ import annotations

import argparse
import importlib.util
import logging
import os
import sys
import wave

from .clock import Pacer, UnpacedClock
from .config import Config, ConfigError
from .output import CHANNELS, OutputFinished, PcmOutput
from .tone import tone_blocks

log = logging.getLogger("lullaby")


def setup_logging() -> None:
    # Under the supervisor, it adds timestamps to every relayed line.
    fmt = "%(levelname)s %(name)s: %(message)s"
    if not os.environ.get("LULLABY_SUPERVISED"):
        fmt = "%(asctime)s " + fmt
    logging.basicConfig(level=logging.INFO, format=fmt, stream=sys.stderr)


def parse_args(argv):
    p = argparse.ArgumentParser(prog="lullaby")
    p.add_argument("--mode", help="override SYNTH_MODE")
    p.add_argument("--wav", metavar="PATH", help="render offline to a WAV file instead of stdout")
    p.add_argument("--seconds", type=float, help="stop after this much audio (default: forever; 30 with --wav)")
    return p.parse_args(argv)


def main(argv=None) -> int:
    setup_logging()
    args = parse_args(argv)
    env = dict(os.environ)
    if args.mode:
        env["SYNTH_MODE"] = args.mode
    # Only the encoder needs the password; don't let it block local runs.
    env["ICECAST_SOURCE_PASSWORD"] = "unused-by-synth"
    try:
        cfg = Config.from_env(env)
    except ConfigError as e:
        log.error("%s", e)
        return 2

    seconds = args.seconds if args.seconds is not None else (30.0 if args.wav else None)
    max_frames = None if seconds is None else int(seconds * cfg.sample_rate)

    if args.wav:
        wav = wave.open(args.wav, "wb")
        wav.setnchannels(CHANNELS)
        wav.setsampwidth(2)
        wav.setframerate(cfg.sample_rate)
        out = PcmOutput(UnpacedClock(cfg.sample_rate, cfg.lead_seconds),
                        stream=_WavStream(wav), max_frames=max_frames)
    else:
        out = PcmOutput(Pacer(cfg.sample_rate, cfg.lead_seconds),
                        heartbeat_path=cfg.heartbeat_path, max_frames=max_frames)

    log.info("mode=%s sample_rate=%d block=%d frames, output=%s",
             cfg.mode, cfg.sample_rate, cfg.block_frames, args.wav or "stdout")
    try:
        if cfg.mode == "tone":
            for block in tone_blocks(cfg.sample_rate, cfg.block_frames):
                out.write(block)
        else:
            run_synth(cfg, out)
    except OutputFinished:
        pass
    except BrokenPipeError:
        # Already logged; point stdout at /dev/null so the exit-time flush
        # doesn't print a second, confusing traceback.
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return 1
    except KeyboardInterrupt:
        pass
    finally:
        if args.wav:
            wav.close()
            log.info("wrote %.1fs to %s", out.pacer.audio_time, args.wav)
    return 0


def run_synth(cfg, out) -> None:
    # Imported here so tone mode works without FluidSynth installed.
    from .icecast import ListenerWatch
    from .player import Player
    from .synth import Synth

    log.info("SoundFont %s, gain %.2f", cfg.soundfont, cfg.gain)
    synth = Synth(cfg.soundfont, cfg.sample_rate, cfg.gain,
                  force_preset=cfg.force_preset, mute_percussion=cfg.mute_percussion)
    session_active = None
    if cfg.mode == "playlist" and cfg.session_start == "listener":
        watch = ListenerWatch(cfg.icecast_host, cfg.icecast_port, cfg.icecast_mount,
                              grace_seconds=cfg.session_grace_seconds)
        session_active = lambda: watch.active  # noqa: E731
        log.info("waiting for a listener on %s (streaming silence until then)", cfg.icecast_mount)
    player = Player(synth, out, cfg.sample_rate, cfg.block_frames, cfg.song_gap_seconds,
                    session_active=session_active, mechanism=load_mechanism(cfg.mechanism_file),
                    humanize_window=cfg.humanize_window,
                    session_length=cfg.session_length,
                    interlude=None if cfg.interlude == "off" else cfg.interlude)
    try:
        if cfg.mode == "file":
            player.loop_file(cfg.midi_file, cfg.midi_dir)
        else:
            player.loop_playlist(cfg.midi_dir)
    finally:
        synth.close()


def load_mechanism(path):
    """The module at MECHANISM_FILE, or None for the built-in mechanism.py.
    If it fails to load, the built-in one plays instead, so a typo means
    plain songs rather than a silent stream."""
    if not path:
        return None
    try:
        # Loaded as part of the package, so `from .context import ...` works.
        spec = importlib.util.spec_from_file_location("lullaby.custom_mechanism", path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    except Exception:
        log.exception("MECHANISM_FILE %s failed to load; using the built-in mechanism", path)
        sys.modules.pop("lullaby.custom_mechanism", None)
        return None
    log.info("using the mechanism in %s", path)
    return module


class _WavStream:
    def __init__(self, wav):
        self.wav = wav

    def write(self, data):
        self.wav.writeframesraw(data)

    def flush(self):
        pass


if __name__ == "__main__":
    sys.exit(main())
