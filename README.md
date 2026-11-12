# lullaby-cast

Streams live-synthesized music-box lullabies to a Google Nest Hub at bedtime.

```
MIDI files → Python "mechanism" → FluidSynth (in-process, pyfluidsynth)
  → s16le PCM on stdout → ffmpeg (MP3 128k) → Icecast mount
  → Home Assistant media_player.play_media → Nest Hub (Google Cast)
```

- Fully headless: no ALSA, audio devices, or MIDI ports.
- The synth paces itself to the wall clock (it renders at most `LEAD_SECONDS`,
  default 0.25 s, ahead), so timing effects land when they're heard.
- The stream never goes silent at the byte level: gaps and errors are filled
  with rendered silence.
- A supervisor restarts the synth→ffmpeg pipe if either side dies or stalls,
  and logs it at `ERROR`.

This repo is only the audio pipeline; Home Assistant does the casting.

> **Status:** stage 1 of 4. Icecast plus a test tone. FluidSynth, the playlist
> loop, and the mechanism hooks are coming.

## Layout

```
docker-compose.yml        icecast + synth services, configured from .env
icecast/                  Debian icecast2, config rendered from .env at start
synth/
  supervisor.py           runs `python -m lullaby | ffmpeg`, restarts on failure
  healthcheck.py          healthy = live source on the mount + fresh heartbeat
  lullaby/                the synth package (writes PCM to stdout)
    encoder.py            the ffmpeg command (the only place it's defined)
scripts/
  listen.sh               play the Icecast mount on this machine
  local-play.sh           run the synth with no Docker/Icecast
soundfonts/, midi/        default local mount points (contents git-ignored)
```

## Quick start

```sh
cp .env.example .env
# edit .env: set both passwords; ICECAST_HOSTNAME = this machine's LAN IP
docker compose up -d --build
docker compose logs -f          # watch for "pipeline started"
scripts/listen.sh               # hear it
```

The passwords may only contain letters, digits, `.`, `_` and `-`. Icecast
refuses to start while they still say `change-me…`.

## Testing on a Mac before casting

There are three ways to test, from most to least of the real pipeline.

**1. The whole stack, listened to from the Mac.** Run `docker compose up` on
the Mac (needs Docker Desktop or OrbStack), or on Unraid. Then run:

```sh
scripts/listen.sh                    # http://localhost:8000/lullaby.mp3
scripts/listen.sh 192.168.1.10       # the stream on your Unraid box
```

`listen.sh` uses ffplay, mpv, or VLC if one is installed, and otherwise opens
the URL in your default browser. Safari plays MP3 streams with nothing
installed. You can also paste the URL into VLC → *File → Open Network*.
Seeing it in `http://<host>:8000/` (the Icecast status page) confirms the
mount is live.

**2. The synth alone, live, no Docker.** Needs [uv](https://docs.astral.sh/uv/)
(or Python 3.11+) and ffplay:

```sh
brew install uv ffmpeg              # fluidsynth too, from stage 2 on
scripts/local-play.sh               # first run creates .venv with Python 3.13
```

**3. Offline to a WAV file**, rendered faster than real time:

```sh
scripts/local-play.sh --wav /tmp/test.wav --seconds 20 && afplay /tmp/test.wav
```

### What you should hear (stage 1)

A soft tone: one second of A, one second of silence, one second of E, one
second of silence, repeating. The silences are real rendered zeros, just like
the gaps between songs will be, so the stream itself never pauses.

## Configuration (.env)

| Variable | Default | Meaning |
|---|---|---|
| `ICECAST_HOSTNAME` | (required) | LAN IP/name of the Docker host, used in Icecast's URLs |
| `ICECAST_PORT` | `8000` | Icecast port, published on the host |
| `ICECAST_MOUNT` | `/lullaby.mp3` | Mount point |
| `ICECAST_SOURCE_PASSWORD` | (required) | Password the synth uses to push the stream |
| `ICECAST_ADMIN_PASSWORD` | (required) | Icecast admin web UI password (user `admin`) |
| `ICECAST_BURST_SIZE` | `16384` | Bytes sent instantly to new listeners (≈1 s at 128k) |
| `SYNTH_MODE` | `tone` | What the synth plays |
| `SOUNDFONTS_HOST_DIR` | `./soundfonts` | Host folder mounted at `/soundfonts` |
| `MIDI_HOST_DIR` | `./midi` | Host folder mounted at `/midi` |
| `SOUNDFONT` | `/soundfonts/musicbox.sf2` | SoundFont path inside the container |
| `SAMPLE_RATE` | `44100` | Synth and MP3 sample rate |
| `MP3_BITRATE` | `128k` | MP3 bitrate |
| `TZ` | `UTC` | Timezone for log timestamps |

Advanced settings, not in `.env.example`: `LEAD_SECONDS` (0.25) and
`BLOCK_FRAMES` (512).

## Running on Unraid

1. Install the **Docker Compose Manager** plugin from Community Applications.
2. Put the repo somewhere persistent, for example:
   ```sh
   cd /mnt/user/appdata && git clone https://github.com/jpschafer/lullaby-cast.git
   ```
3. Create the media folders and point `.env` at them:
   ```
   SOUNDFONTS_HOST_DIR=/mnt/user/appdata/lullaby-cast/soundfonts
   MIDI_HOST_DIR=/mnt/user/appdata/lullaby-cast/midi
   ICECAST_HOSTNAME=<Unraid's LAN IP>
   ```
   The `soundfonts/` and `midi/` folders inside the clone work as-is too.
4. Add a stack in Compose Manager pointing at that folder (or
   `docker compose up -d --build` from a terminal in it).
5. The synth container shows **healthy** once Icecast has a live source.
   Docker only *reports* health; restarts are handled by the supervisor
   inside the container, plus `restart: unless-stopped`.

To swap MIDI files, drop them into the MIDI folder; no rebuild needed.

## Home Assistant

The Nest Hub fetches the URL itself, so it must be the Unraid **LAN IP**:

```yaml
action: media_player.play_media
target:
  entity_id: media_player.nursery_hub
data:
  media_content_id: http://192.168.1.10:8000/lullaby.mp3
  media_content_type: music
```

## Logs and failures

Everything goes to `docker compose logs`. Supervisor lines are timestamped,
and child output is tagged `[synth]` or `[ffmpeg]`. When something fails
you'll see:

```
ERROR supervisor: PIPELINE DOWN after 1s: ffmpeg exited with code 1. Restart #1 in 1s ...
```

Restarts back off from 1 s to 30 s while it keeps failing. The pipeline is
also restarted if the synth stops producing audio for 20 s (the heartbeat).
Bad configuration fails at startup with every problem listed.

Check health directly:

```sh
docker inspect --format '{{json .State.Health}}' lullaby-cast-synth-1
docker compose exec synth python /app/healthcheck.py
```

## Troubleshooting

- **The Nest Hub won't play, but VLC on the Mac can.** The URL probably says
  `localhost`, a Docker-internal name, or a hostname. Cast devices often
  ignore your local DNS, so use the Unraid LAN IP.
- **Different VLANs.** HA must discover the Hub (mDNS, which needs a reflector
  across VLANs), and the Hub must be able to reach `UNRAID_IP:8000` (check
  firewall rules from the IoT VLAN to the server).
- **`ffmpeg exited` restarting forever.** ffmpeg can't reach Icecast or the
  source password doesn't match. Check `docker compose logs icecast`.
- **`no live source on /lullaby.mp3`** in the healthcheck: the pipeline is down
  or still starting. Look for `PIPELINE DOWN` lines.
- **Delay between rendering and hearing.** Icecast's burst plus the Cast buffer
  add a few seconds. Lower `ICECAST_BURST_SIZE` if needed.
