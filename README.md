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
- Bedtime sessions: silence until the Nest Hub (or any player) connects, then
  the playlist from the top; back to silence once nobody has been listening
  for `SESSION_GRACE_SECONDS`.
- One container: a supervisor runs Icecast and the synth→ffmpeg pipe, restarts
  whatever dies or stalls, and logs it at `ERROR`.
- Published on Docker Hub as `jpschafer/lullaby-cast` (amd64 and arm64), with
  an Unraid template.

This repo is only the audio pipeline; Home Assistant does the casting.

> **Status:** the plumbing is complete. The musical mechanism
> (`synth/lullaby/mechanism.py`) has placeholder hooks, ready to be written.

## Layout

```
Dockerfile                the one image: Debian icecast2 + FluidSynth + ffmpeg + Python
docker-compose.yml        runs it, configured from .env
unraid/lullaby-cast.xml   Unraid container template
.github/workflows/        tests, then builds and pushes the image to Docker Hub
synth/
  supervisor.py           runs Icecast and `python -m lullaby | ffmpeg`, restarts on failure
  healthcheck.py          healthy = live source on the mount + fresh heartbeat
  icecast.xml.template    Icecast config, rendered from the environment at start
  lullaby/                the synth package (writes PCM to stdout)
    mechanism.py          ← the musical mechanism: three hooks (yours)
    context.py            what the hooks receive
    interlude.py          key detection + the short figure played before each song
    midi.py               MIDI file → timed events
    synth.py              FluidSynth wrapper (forced preset, percussion mute)
    player.py             sample-accurate playback, sessions, playlist, error recovery
    icecast.py            Icecast status: live mount, listener count
    server.py             renders and validates icecast.xml
    encoder.py            the ffmpeg command (the only place it's defined)
  tests/                  unit tests (python -m unittest discover -s tests)
scripts/
  listen.sh               play the Icecast mount on this machine
  local-play.sh           run the synth with no Docker/Icecast
soundfonts/, midi/        default local mount points (contents git-ignored)
```

## Quick start

Put a SoundFont in `soundfonts/` and at least one MIDI file in `midi/`
(see [SoundFont](#soundfont)), then:

```sh
cp .env.example .env
# edit .env: set both passwords; ICECAST_HOSTNAME = this machine's LAN IP
docker compose up -d --build   # builds this checkout; without --build it pulls the published image
docker compose logs -f          # watch for "pipeline started"
scripts/listen.sh               # hear it
```

The passwords may only contain letters, digits, `.`, `_` and `-`. Icecast
refuses to start while they still say `change-me…`.

## Testing on a Mac before casting

There are three ways to test, from most to least of the real pipeline.

**1. The whole stack, listened to from the Mac.** Run `docker compose up` on
the Mac or on Unraid. For Docker on a Mac without Docker Desktop, use
[Colima](https://github.com/abiosoft/colima) (headless; forwards ports to
localhost):

```sh
brew install colima docker docker-compose
mkdir -p ~/.docker && echo '{"cliPluginsExtraDirs": ["/opt/homebrew/lib/docker/cli-plugins"]}' > ~/.docker/config.json
colima start
docker compose up -d --build
```

A local build on an Apple Silicon Mac is arm64; Unraid pulls the published
amd64 image (see [Releases](#releases)). Then open
<http://localhost:8000/lullaby.mp3> in a browser, or run:

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

### What you should hear

Every file in `midi/` on the music box, in alphabetical order, wrapping around
at the end. Before each song there's a short interlude in that song's key:
broken chords (I–IV–I–V) before one song, a little "da da da da, duh dah dah"
phrase before the next. The first song gets one too, which also covers the
second or two a Cast device may lose while it buffers.

Through Icecast, the playlist starts only when you connect. Watch
`docker compose logs -f` while you run `scripts/listen.sh`:

```
listeners on /lullaby.mp3: 0 -> 1
session started
interlude (chords) in F major
playing brahms-lullaby-wiegenlied-piano.mid (72.0s, 409 events)
...
listeners on /lullaby.mp3: 1 -> 0
session ended after 3.2 min, 3 song(s)
```

Each new connection after a session ends starts again from the first song.
`local-play.sh` has no Icecast, so it always plays (`SESSION_START=always`).
To loop a single file instead, use `SYNTH_MODE=file`.

For the stage-1 test tone instead, use `SYNTH_MODE=tone` in `.env` or
`scripts/local-play.sh --mode tone`.

## SoundFont

A MIDI file is only notes; the SoundFont supplies the sound. The default is
[GeneralUser GS](https://www.schristiancollins.com/generaluser) by S.
Christian Collins, a free General MIDI bank whose license allows use without
restriction. Its preset 0:10 is a pleasant Music Box.

```sh
curl -L -o soundfonts/GeneralUser-GS.sf2 \
  https://raw.githubusercontent.com/mrbumpy409/GeneralUser-GS/main/GeneralUser-GS.sf2
```

Any `.sf2` works. Set `SOUNDFONT` to its path inside the container, and set
`FORCE_PRESET` to its music-box preset. For a SoundFont with a single preset,
that's usually `0:0`. Many "free" SoundFonts online contain samples of unclear
origin, so check the license on the source page.

Most lullaby MIDI files ask for piano. `FORCE_PRESET` makes every melodic
channel play the music box regardless, and `MUTE_PERCUSSION` drops drum parts.
`FORCE_PRESET=off` plays the instruments the file asks for.

## The mechanism

`synth/lullaby/mechanism.py` is where the music gets its character. The
plumbing calls three hooks; the placeholders change nothing.

| Hook | Called | Returns |
|---|---|---|
| `choose_next_song(library, history, ctx)` | before each song | a path from `library`, or `None` to stop for the night (silence until the session ends) |
| `scale_time(delta, ctx)` | at the start of every gap between events | seconds to actually wait (`2 * delta` = half speed); e.g. a spring winding down |
| `shape_note(note, ctx)` | for every struck note | the note with new `velocity`/`offset` (±`HUMANIZE_WINDOW_MS`), or `None` to drop it; e.g. humanization |

Interlude notes go through `scale_time` and `shape_note` too, so a wind-down
slows them as well; `ctx.interlude` is `True` while one plays (and `ctx.song`
is the song it introduces).

The contexts (`context.py`) carry `elapsed` (seconds since the session
started), `session_length` (from `SESSION_MINUTES`), and for the playback
hooks, the song, its length, and where in it you are, both in the file's own
timeline and as played.

Rendering is paced to the wall clock, so a hook decides what happens *now*:
each `scale_time` call is made as its gap begins. If a hook raises or returns
something unusable, the error is logged with a traceback (once per song, then
counted), the value is used unmodified, and the music continues.

To hear a mechanism quickly, render offline. `elapsed` is audio time, so a
30-minute session renders in seconds:

```sh
SESSION_MINUTES=30 scripts/local-play.sh --wav /tmp/night.wav --seconds 1800
afplay /tmp/night.wav     # or open it in an audio editor and jump to the end
```

### Your own mechanism.py without rebuilding

The built-in `mechanism.py` is baked into the image. To change it on a
running server without publishing a new image, put your copy in a folder,
mount it, and set `MECHANISM_FILE`:

- **Unraid template:** copy `synth/lullaby/mechanism.py` to
  `/mnt/user/appdata/lullaby-cast/mechanism/`, then set *MECHANISM_FILE*
  (under *Show more settings*) to `/mechanism/mechanism.py`.
- **Compose:** copy it to `./mechanism/` (git-ignored), uncomment the
  `/mechanism` volume in `docker-compose.yml`, and set
  `MECHANISM_FILE=/mechanism/mechanism.py` in `.env`.

Restart the container after each edit. It's imported as part of the
package, so `from .context import NoteEvent` works as in the original. If it
fails to load, the log shows the traceback and the built-in placeholders
play instead.

Run the unit tests after changing the plumbing (not needed for the mechanism):

```sh
cd synth && ../.venv/bin/python -m unittest discover -s tests
```

## Interludes

`interlude.py` finds each song's key (Krumhansl–Schmuckler: how long each
pitch class sounds, matched against major and minor key profiles) and plays
one of two figures in it on channel 1, at 72 bpm:

- **chords**: root, 3rd, 5th, octave, 5th, 3rd over I, IV, I, then V held, so
  the song's start resolves it. V is major in minor keys too.
- **phrase**: scale degrees 1 2 3 4 (eighths), 5, 3 (quarters), 1 (half).

Both are plain data at the top of the file (`PHRASE`, `PROGRESSION`,
`TEMPO_BPM`), so they're easy to change. The detected key is in the log line
`interlude (chords) in G minor`.

## Configuration (.env)

| Variable | Default | Meaning |
|---|---|---|
| `ICECAST_HOSTNAME` | (required) | LAN IP/name of the Docker host, used in Icecast's URLs |
| `ICECAST_PORT` | `8000` | Icecast port, published on the host |
| `ICECAST_MOUNT` | `/lullaby.mp3` | Mount point |
| `ICECAST_SOURCE_PASSWORD` | (required) | Password the synth uses to push the stream |
| `ICECAST_ADMIN_PASSWORD` | (required) | Icecast admin web UI password (user `admin`) |
| `ICECAST_BURST_SIZE` | `16384` | Bytes sent instantly to new listeners (≈1 s at 128k) |
| `SYNTH_MODE` | `playlist` | `playlist`, `file` (loop one MIDI file) or `tone` (test tone) |
| `SESSION_START` | `listener` | `listener`: play while Icecast has listeners; `always`: never stop |
| `SESSION_GRACE_SECONDS` | `20` | How long after the last listener leaves before the session ends |
| `SESSION_MINUTES` | (empty) | Passed to the hooks as `ctx.session_length`; the plumbing doesn't enforce it |
| `HUMANIZE_WINDOW_MS` | `50` | Furthest `shape_note` may move a note |
| `MECHANISM_FILE` | (empty) | Your own `mechanism.py`, as a path inside the container; empty = built-in |
| `MECHANISM_HOST_DIR` | `./mechanism` | Host folder for the commented-out `/mechanism` volume |
| `SOUNDFONTS_HOST_DIR` | `./soundfonts` | Host folder mounted at `/soundfonts` |
| `MIDI_HOST_DIR` | `./midi` | Host folder mounted at `/midi` |
| `SOUNDFONT` | `/soundfonts/GeneralUser-GS.sf2` | SoundFont path inside the container |
| `FORCE_PRESET` | `0:10` | `bank:preset` for all melodic channels, or `off` |
| `MUTE_PERCUSSION` | `true` | Drop drum notes (MIDI channel 10) |
| `GAIN` | `0.8` | FluidSynth output level (FluidSynth's own default, 0.2, is very quiet) |
| `MIDI_FILE` | (empty) | `file` mode: file to loop, e.g. `/midi/song.mid`; empty = first in the folder |
| `SONG_GAP_SECONDS` | `2` | Pause after each song for the last notes to ring out |
| `INTERLUDE` | `alternate` | Before each song: `chords`, `phrase`, `alternate` (taking turns), or `off` (silence) |
| `SAMPLE_RATE` | `44100` | Synth and MP3 sample rate |
| `MP3_BITRATE` | `128k` | MP3 bitrate |
| `TZ` | `UTC` | Timezone for log timestamps |
| `LULLABY_TAG` | `latest` | Image tag compose runs: `latest`, a release like `0.1.0`, or `edge` |

Advanced settings, not in `.env.example`: `LEAD_SECONDS` (0.25) and
`BLOCK_FRAMES` (512).

## Running on Unraid

**1. Copy your media to the server.** The image holds no SoundFont or MIDI
files. From the repo on your Mac (`tower` = your Unraid host):

```sh
ssh root@tower mkdir -p /mnt/user/appdata/lullaby-cast/{soundfonts,midi}
scp soundfonts/*.sf2 root@tower:/mnt/user/appdata/lullaby-cast/soundfonts/
scp midi/*.mid root@tower:/mnt/user/appdata/lullaby-cast/midi/
```

Or copy them over the `appdata` SMB share.

**2. Add the container**, with either option:

- **Template (recommended).** On the Unraid terminal:
  ```sh
  wget -O /boot/config/plugins/dockerMan/templates-user/my-lullaby-cast.xml \
    https://raw.githubusercontent.com/jpschafer/lullaby-cast/main/unraid/lullaby-cast.xml
  ```
  Then *Docker → Add Container → Template: lullaby-cast*. Fill in the server
  IP and both passwords (letters, digits, `.`, `_`, `-`), check the folders,
  and *Apply*.
- **Compose Manager plugin.** Make a stack from this repo's
  `docker-compose.yml` and a `.env` with
  `SOUNDFONTS_HOST_DIR=/mnt/user/appdata/lullaby-cast/soundfonts`,
  `MIDI_HOST_DIR=/mnt/user/appdata/lullaby-cast/midi` and
  `ICECAST_HOSTNAME=<Unraid's LAN IP>`. Compose Up pulls the image.

**3. Check it.** The container shows **healthy** once Icecast has a live
source; open `http://<unraid-ip>:8000/lullaby.mp3`. Docker only *reports*
health; the supervisor inside does the restarting.

**Updating:** *Docker → Check for Updates*, then *Apply Update* (template),
or *Update Stack* in Compose Manager. To pin a version, change the
repository to `jpschafer/lullaby-cast:0.1.0` (or set `LULLABY_TAG`).

To swap MIDI files, drop them into the MIDI folder; no restart needed. Files
are looked up again before each play. Extensions `.mid`/`.midi` are matched in
any case, and subfolders are included. A changed SoundFont needs a container
restart.

## Releases

`.github/workflows/docker.yml` runs the unit tests, then builds the image for
`linux/amd64` and `linux/arm64`:

| Event | Pushed to Docker Hub |
|---|---|
| pull request | nothing (build only) |
| push to `main` | `jpschafer/lullaby-cast:edge` |
| tag `v0.1.0` | `:0.1.0`, `:0.1`, `:latest` |

It needs two repository secrets (*Settings → Secrets and variables →
Actions*): `DOCKERHUB_USERNAME`, and `DOCKERHUB_TOKEN`, a Docker Hub access
token with *Read & Write*. To release:

```sh
git tag v0.1.0 && git push origin v0.1.0
```

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
and child output is tagged `[icecast]`, `[synth]` or `[ffmpeg]`. When
something fails you'll see:

```
ERROR supervisor: STREAM DOWN after 1s: ffmpeg exited with code 1. Restart #1 in 1s ...
```

Restarts back off from 1 s to 30 s while it keeps failing. Icecast keeps
running across synth/ffmpeg restarts; it's restarted itself only if it exits
or stops answering. The pipeline is also restarted if the synth stops
producing audio for 20 s (the heartbeat).
Bad configuration (including a missing SoundFont or a preset it doesn't have)
fails at startup with every problem listed. A missing or unreadable MIDI file
doesn't stop the stream: it logs the error with a traceback, streams silence,
and tries again 30 s later.

Check health directly:

```sh
docker inspect --format '{{json .State.Health}}' lullaby-cast
docker exec lullaby-cast python /app/healthcheck.py
```

## Troubleshooting

- **The Nest Hub won't play, but VLC on the Mac can.** The URL probably says
  `localhost`, a Docker-internal name, or a hostname. Cast devices often
  ignore your local DNS, so use the Unraid LAN IP.
- **Different VLANs.** HA must discover the Hub (mDNS, which needs a reflector
  across VLANs), and the Hub must be able to reach `UNRAID_IP:8000` (check
  firewall rules from the IoT VLAN to the server).
- **`ffmpeg exited` restarting forever.** ffmpeg can't reach Icecast or the
  source password doesn't match. Check the `[icecast]` lines in the log.
- **`no live source on /lullaby.mp3`** in the healthcheck: the pipeline is down
  or still starting. Look for `STREAM DOWN` lines.
- **The stream connects but it's silent.** In `playlist` mode, check the synth
  log for `session started`. If it's missing, the synth can't read Icecast's
  status: look for `cannot read Icecast status`.
- **Some songs are much louder than others.** With `FORCE_PRESET`, every part
  of an orchestral MIDI file becomes a music box, so busy arrangements come
  out louder than solo piano ones. Lower `GAIN` if the loudest one is too much.
- **`Unsupported or legacy stream type: "audio/mpeg"`** in the log is
  harmless (logged at INFO): Icecast 2.4 streams MP3 through its generic
  handler.
- **Upgrading from the two-container version.** Run
  `docker compose up -d --remove-orphans` once, so the old `icecast` and
  `synth` containers stop holding port 8000.
- **Delay between rendering and hearing.** Icecast's burst plus the Cast buffer
  add a few seconds. Lower `ICECAST_BURST_SIZE` if needed.
