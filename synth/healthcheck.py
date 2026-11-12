"""Docker healthcheck: exit 0 only if Icecast has a live source on our mount
and the synth's heartbeat is fresh. Prints the reason either way."""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from urllib.parse import urlparse

from lullaby.config import Config, ConfigError

HEARTBEAT_MAX_AGE = 15


def check(cfg) -> str:
    url = f"http://{cfg.icecast_host}:{cfg.icecast_port}/status-json.xsl"
    with urllib.request.urlopen(url, timeout=5) as resp:
        stats = json.load(resp)["icestats"]
    sources = stats.get("source", [])
    if isinstance(sources, dict):  # Icecast returns a bare object for one source
        sources = [sources]
    mounts = [urlparse(s.get("listenurl", "")).path for s in sources]
    if cfg.icecast_mount not in mounts:
        raise RuntimeError(f"no live source on {cfg.icecast_mount} (live mounts: {mounts or 'none'})")

    try:
        age = time.time() - os.path.getmtime(cfg.heartbeat_path)
    except OSError:
        raise RuntimeError("synth heartbeat file missing")
    if age > HEARTBEAT_MAX_AGE:
        raise RuntimeError(f"synth heartbeat is {age:.0f}s old")

    listeners = sum(int(s.get("listeners", 0)) for s in sources
                    if urlparse(s.get("listenurl", "")).path == cfg.icecast_mount)
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
