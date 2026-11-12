"""Runs Icecast and `python -m lullaby | ffmpeg` streaming into it, and
restarts whatever dies.

Every line a child writes is relayed with a timestamp and an [icecast],
[synth] or [ffmpeg] tag. Exits, stalls and restarts are logged at ERROR so
they stand out in `docker logs`.
"""

from __future__ import annotations

import logging
import os
import re
import signal
import subprocess
import sys
import threading
import time

from lullaby.config import Config, ConfigError
from lullaby.encoder import ffmpeg_command
from lullaby.icecast import mount_status
from lullaby.server import CONFIG_PATH, render_config

log = logging.getLogger("supervisor")

POLL_SECONDS = 0.5
STOP_GRACE_SECONDS = 5
# A run shorter than this counts toward the crash-loop backoff.
HEALTHY_RUN_SECONDS = 60
BACKOFF_MAX_SECONDS = 30
# Restart the pipeline if the synth's heartbeat goes this long without
# updating (hung Python, or ffmpeg stopped reading).
STALL_SECONDS = 20
STARTUP_GRACE_SECONDS = 15
# How long Icecast gets to start answering HTTP.
ICECAST_READY_SECONDS = 15

_stop = threading.Event()


CHILD_LEVELS = {"DEBUG": logging.DEBUG, "INFO": logging.INFO, "WARNING": logging.WARNING,
                "ERROR": logging.ERROR, "CRITICAL": logging.CRITICAL}
# Icecast: "[2026-11-12  21:04:05] INFO source/source_main ..."
ICECAST_LINE = re.compile(r"\[[^\]]*\] (EROR|WARN|INFO|DBUG) (.*)")
ICECAST_LEVELS = {"EROR": logging.ERROR, "WARN": logging.WARNING,
                  "INFO": logging.INFO, "DBUG": logging.DEBUG}


def child_line(line):
    """Synth lines start with their level name ("ERROR lullaby...")."""
    first, _, rest = line.partition(" ")
    if first in CHILD_LEVELS:
        return CHILD_LEVELS[first], rest
    return None, line


# Icecast 2.4 says this about every MP3 source; it streams them fine.
ICECAST_HARMLESS = ("Unsupported or legacy stream type",)


def icecast_line(line):
    """Icecast's own timestamp is dropped; ours is on every line."""
    m = ICECAST_LINE.fullmatch(line)
    if not m:
        return None, line
    if any(text in m.group(2) for text in ICECAST_HARMLESS):
        return logging.INFO, m.group(2)
    return ICECAST_LEVELS[m.group(1)], m.group(2)


def relay(stream, tag, default_level, parse=child_line) -> None:
    """Relay a child's output. Lines `parse` finds a level in keep it;
    others use the previous line's level, starting at `default_level`."""
    level = default_level
    for raw in iter(stream.readline, b""):
        line = raw.decode("utf-8", "replace").rstrip()
        if not line:
            continue
        found, line = parse(line)
        # Lines without a level (traceback bodies) keep the previous one.
        level = found or level
        log.log(level, "[%s] %s", tag, line)
    stream.close()


def terminate(proc, name) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(STOP_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        log.error("%s ignored SIGTERM for %ds; killing", name, STOP_GRACE_SECONDS)
        proc.kill()
        proc.wait()


def heartbeat_age(path):
    try:
        return time.time() - os.path.getmtime(path)
    except OSError:
        return None


def start_icecast(xml):
    with open(CONFIG_PATH, "w") as f:
        f.write(xml)
    proc = subprocess.Popen(["icecast2", "-c", CONFIG_PATH], stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    threading.Thread(target=relay, args=(proc.stdout, "icecast", logging.INFO, icecast_line),
                     daemon=True).start()
    log.info("icecast started (pid %d)", proc.pid)
    return proc


def wait_for_icecast(cfg, proc):
    """Wait until Icecast answers its status page. Returns None when it
    does, or why it didn't."""
    deadline = time.monotonic() + ICECAST_READY_SECONDS
    while not _stop.is_set():
        if proc.poll() is not None:
            return f"icecast exited with code {proc.returncode}"
        try:
            mount_status(cfg.icecast_host, cfg.icecast_port, cfg.icecast_mount, timeout=1)
            return None
        except (OSError, ValueError, KeyError):
            pass
        if time.monotonic() > deadline:
            return f"icecast did not answer on port {cfg.icecast_port} within {ICECAST_READY_SECONDS}s"
        _stop.wait(0.25)
    return "stop requested"


def run_pipeline(cfg, icecast) -> str:
    """Start the synth and ffmpeg and wait until one of them, or Icecast,
    fails. Returns why it stopped."""
    try:
        os.remove(cfg.heartbeat_path)
    except FileNotFoundError:
        pass

    env = dict(os.environ, LULLABY_SUPERVISED="1")
    synth = subprocess.Popen([sys.executable, "-m", "lullaby"], stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, env=env)
    encoder = subprocess.Popen(ffmpeg_command(cfg), stdin=synth.stdout, stderr=subprocess.PIPE)
    # Only ffmpeg holds the read end now, so the synth gets EPIPE if ffmpeg dies.
    synth.stdout.close()
    procs = {"synth": synth, "ffmpeg": encoder}
    # ffmpeg runs at -loglevel warning, so anything it prints is a warning or worse.
    levels = {"synth": logging.INFO, "ffmpeg": logging.WARNING}
    for name, proc in procs.items():
        threading.Thread(target=relay, args=(proc.stderr, name, levels[name]), daemon=True).start()
    log.info("pipeline started (synth pid %d, ffmpeg pid %d)", synth.pid, encoder.pid)

    started = time.monotonic()
    reason = "stop requested"
    while not _stop.wait(POLL_SECONDS):
        dead = [(n, p.returncode) for n, p in dict(procs, icecast=icecast).items()
                if p.poll() is not None]
        if dead:
            reason = ", ".join(f"{n} exited with code {code}" for n, code in dead)
            break
        if time.monotonic() - started > STARTUP_GRACE_SECONDS:
            age = heartbeat_age(cfg.heartbeat_path)
            if age is None or age > STALL_SECONDS:
                reason = ("synth never wrote a heartbeat" if age is None
                          else f"synth heartbeat stale for {age:.0f}s (stalled)")
                break

    for name, proc in procs.items():
        terminate(proc, name)
    return reason


def main() -> int:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        cfg = Config.from_env()
        xml = render_config()
    except ConfigError as e:
        log.error("%s", e)
        return 2

    def on_signal(signum, _frame):
        log.info("received %s; shutting down", signal.Signals(signum).name)
        _stop.set()

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)

    log.info("streaming to %s", ffmpeg_command(cfg, redact=True)[-1])
    log.debug("ffmpeg: %s", " ".join(ffmpeg_command(cfg, redact=True)))

    backoff = 1
    restarts = 0
    icecast = None
    while not _stop.is_set():
        started = time.monotonic()
        # Icecast keeps running across pipeline restarts. It's restarted
        # only if it died, or stops answering (hung, or still shutting down).
        if icecast is None or icecast.poll() is not None:
            icecast = start_icecast(xml)
        reason = wait_for_icecast(cfg, icecast)
        if reason:
            terminate(icecast, "icecast")
        else:
            reason = run_pipeline(cfg, icecast)
        if _stop.is_set():
            break
        ran = time.monotonic() - started
        restarts += 1
        if ran >= HEALTHY_RUN_SECONDS:
            backoff = 1
        log.error("STREAM DOWN after %.0fs: %s. Restart #%d in %ds "
                  "(stream is silent until it reconnects)", ran, reason, restarts, backoff)
        if backoff >= BACKOFF_MAX_SECONDS:
            log.error("stream is crash-looping; check the [icecast]/[synth]/[ffmpeg] lines above")
        _stop.wait(backoff)
        backoff = min(backoff * 2, BACKOFF_MAX_SECONDS)

    if icecast is not None:
        terminate(icecast, "icecast")
    log.info("stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
