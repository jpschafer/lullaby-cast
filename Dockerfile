FROM debian:trixie-slim

RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      icecast2 fluidsynth libfluidsynth3 ffmpeg python3 python3-venv tini ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Debian's system Python refuses pip installs; use a venv.
ENV VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
COPY synth/requirements.txt /tmp/requirements.txt
RUN python3 -m venv /opt/venv \
 && pip install --no-cache-dir -r /tmp/requirements.txt

WORKDIR /app
COPY synth/supervisor.py synth/healthcheck.py synth/icecast.xml.template ./
COPY synth/lullaby ./lullaby

# Icecast refuses to run as root; so does everything else here.
RUN useradd --system --no-create-home --shell /usr/sbin/nologin lullaby
USER lullaby

EXPOSE 8000
# Healthy = Icecast reports a live source on our mount AND the synth's
# heartbeat is fresh. Docker only reports this; the supervisor restarts.
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
  CMD ["python", "/app/healthcheck.py"]

# tini forwards SIGTERM to the supervisor and reaps children. The
# supervisor runs Icecast and the synth | ffmpeg pipeline.
ENTRYPOINT ["tini", "--"]
CMD ["python", "supervisor.py"]
