FROM debian:trixie-slim

RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      fluidsynth libfluidsynth3 ffmpeg python3 python3-venv tini ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Debian's system Python refuses pip installs; use a venv.
ENV VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
COPY requirements.txt /tmp/requirements.txt
RUN python3 -m venv /opt/venv \
 && pip install --no-cache-dir -r /tmp/requirements.txt

WORKDIR /app
COPY supervisor.py healthcheck.py ./
COPY lullaby ./lullaby

RUN useradd --system --no-create-home --shell /usr/sbin/nologin lullaby
USER lullaby

# tini forwards SIGTERM to the supervisor and reaps children.
ENTRYPOINT ["tini", "--"]
CMD ["python", "supervisor.py"]
