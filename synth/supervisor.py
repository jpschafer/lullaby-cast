"""Runs `python -m lullaby | ffmpeg` and restarts the pair if either side dies.

Every line either child writes to stderr is relayed with a timestamp and a
[synth] or [ffmpeg] tag. Exits, stalls and restarts are logged at ERROR so
they stand out in `docker logs`.
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import threading
import time

from lullaby.config import Config, ConfigError
from lullaby.encoder import ffmpeg_command

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

_stop = threading.Event()


def relay(stream, tag) -> None:
    for raw in iter(stream.readline, b""):
        line = raw.decode("utf-8", "replace").rstrip()
        if line:
            log.info("[%s] %s", tag, line)
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


def run_pipeline(cfg) -> str:
    """Start both processes and wait until one fails. Returns why it stopped."""
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
    for name, proc in procs.items():
        threading.Thread(target=relay, args=(proc.stderr, name), daemon=True).start()
    log.info("pipeline started (synth pid %d, ffmpeg pid %d)", synth.pid, encoder.pid)

    started = time.monotonic()
    reason = "stop requested"
    while not _stop.wait(POLL_SECONDS):
        dead = [(n, p.returncode) for n, p in procs.items() if p.poll() is not None]
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
    while not _stop.is_set():
        started = time.monotonic()
        reason = run_pipeline(cfg)
        if _stop.is_set():
            break
        ran = time.monotonic() - started
        restarts += 1
        if ran >= HEALTHY_RUN_SECONDS:
            backoff = 1
        log.error("PIPELINE DOWN after %.0fs: %s. Restart #%d in %ds "
                  "(stream is silent until it reconnects)", ran, reason, restarts, backoff)
        if backoff >= BACKOFF_MAX_SECONDS:
            log.error("pipeline is crash-looping; check the [synth]/[ffmpeg] lines above")
        _stop.wait(backoff)
        backoff = min(backoff * 2, BACKOFF_MAX_SECONDS)

    log.info("stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
