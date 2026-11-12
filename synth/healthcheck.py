"""Docker healthcheck: exit 0 only if Icecast has a live source on our mount
and the synth's heartbeat is fresh. Prints the reason either way."""

from __future__ import annotations

import os
import sys
import time

from lullaby.config import Config, ConfigError
from lullaby.icecast import mount_status

HEARTBEAT_MAX_AGE = 15


def check(cfg) -> str:
    listeners = mount_status(cfg.icecast_host, cfg.icecast_port, cfg.icecast_mount)
    if listeners is None:
        raise RuntimeError(f"no live source on {cfg.icecast_mount}")
    try:
        age = time.time() - os.path.getmtime(cfg.heartbeat_path)
    except OSError:
        raise RuntimeError("synth heartbeat file missing")
    if age > HEARTBEAT_MAX_AGE:
        raise RuntimeError(f"synth heartbeat is {age:.0f}s old")
    return f"ok: {cfg.icecast_mount} live, {listeners} listener(s), heartbeat {age:.0f}s"


def main() -> int:
    try:
        print(check(Config.from_env()))
        return 0
    except (ConfigError, OSError, ValueError, KeyError, RuntimeError) as e:
        print(f"unhealthy: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
