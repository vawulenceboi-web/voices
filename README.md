# Chatterbox Voice Lab

A simple, self-hosted ElevenLabs-style voice cloning app for personal use, with
a local Next.js UI that proxies requests to a RunPod-hosted Chatterbox GPU API.

- Upload a **WAV**, any other **audio** (MP3/M4A/OGG/FLAC…), or a **video** (MP4/MOV/WEBM/MKV…) as the voice reference
- Pick a saved voice, type text, generate speech with a cloned voice
- The RunPod API key stays server-side in the local Next.js backend

## Architecture

| Layer    | Tech                                        | Role                                      |
| -------- | ------------------------------------------- | ----------------------------------------- |
| Frontend | Next.js (App Router) + Tailwind v4 + lucide | Browser control panel on `:3000`          |
| Local API | Next.js route handlers                     | Server-side proxy and credential boundary |
| Backend  | FastAPI + Uvicorn on RunPod                 | HTTP API on `:8000`, auth via Bearer key  |
| TTS      | Chatterbox (Resemble AI) + PyTorch on GPU   | Zero-shot voice cloning from a reference  |
| Convert  | ffmpeg (optional)                           | Video/audio → 24 kHz mono WAV reference   |

```
Browser (:3000) ──► Next API ──► RunPod FastAPI (:8000, Bearer key) ──► Chatterbox GPU ──► WAV
                                      │
                                      └── voices/ (uploaded references) + generated/ (output)
```

## Setup

### Backend (FastAPI + Chatterbox)

```bash
cd server
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install chatterbox-tts        # install separately; see notes below
cp .env.example .env
sudo apt install ffmpeg           # needed only for video/audio uploads
```

Environment (`.env`):

| Variable                | Default    | Notes                                          |
| ----------------------- | ---------- | ---------------------------------------------- |
| `API_KEY`               | `change-me`| Bearer token the frontend must send            |
| `DEVICE`                | `cuda`     | Use `cpu` or `mps` (Apple Silicon) if no GPU   |
| `HOST` / `PORT`         | `0.0.0.0` / `8000` |                                        |
| `VOICE_DIR`             | `./voices` | Relative to the `server/` directory            |
| `GENERATED_DIR`         | `./generated` | Relative to the `server/` directory         |
| `MAX_REFERENCE_MB`      | `25`       | Upload size cap                                |
| `MAX_REFERENCE_SECONDS` | `30`       | Video/audio converted only up to this length   |
| `MAX_TEXT_LENGTH`       | `3000`     | TTS text cap                                   |
| `DEVELOPER_API_KEYS_DATABASE_URL` | unset | PostgreSQL DSN for the Supabase table that stores developer API-key hashes |
| `DEVELOPER_API_KEY_HASH_SECRET` | unset | Stable server-side HMAC secret for hashing developer keys |

When developer API keys are enabled, the backend creates this minimal Supabase
PostgreSQL table automatically:

```sql
CREATE TABLE IF NOT EXISTS developer_api_keys (
    id uuid PRIMARY KEY,
    developer_name text NOT NULL CHECK (length(btrim(developer_name)) > 0),
    key_hash text NOT NULL UNIQUE,
    key_prefix text NOT NULL,
    key_last4 text NOT NULL CHECK (length(key_last4) = 4),
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    revoked_at timestamptz
);
```

> **PyTorch/CUDA:** `chatterbox-tts` pulls in PyTorch. On a CUDA machine, install
> the torch build matching your CUDA version *before* `chatterbox-tts` so it is
> not replaced by the CPU wheel (see https://pytorch.org/get-started/locally/).

Run:

```bash
cd server
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

First synthesis downloads the model weights from Hugging Face (several GB) and
can take a long time on CPU.

### Frontend (Next.js)

```bash
cd ..
npm install          # or: pnpm install
npm run dev          # http://localhost:3000
```

Configure the server-side bridge in `.env.local`:

```bash
{
  echo 'VOICE_API_BASE_URL=https://8c5buydqo1yexy-8000.proxy.runpod.net'
  awk -F= '$1=="API_KEY"{print "VOICE_API_KEY="$2}' server/.env
  echo 'VOICE_API_TIMEOUT_MS=600000'
} > .env.local
```

Do not use `NEXT_PUBLIC_*` for the voice API key.

> **Troubleshooting:** if `npm install` hangs with no output, your npm registry
> may be pointed at a mirror that is unreachable from this machine. Check
> `npm config get registry`; install with
> `npm install --registry=https://registry.npmjs.org` (or fix `~/.npmrc`).

## API

| Method | Path            | Auth  | Purpose                                    |
| ------ | --------------- | ----- | ------------------------------------------ |
| GET    | `/api/health`   | local | Proxy RunPod liveness check                |
| GET    | `/api/voices`   | local | List saved voices                          |
| POST   | `/api/voices`   | local | Upload WAV / audio / video reference       |
| POST   | `/api/tts`      | local | Generate speech `{voice_id, text}` → WAV   |
| GET    | `/api/developer-keys` | local | List masked developer API keys |
| POST   | `/api/developer-keys` | local | Create a developer API key; full key is returned once |
| POST   | `/api/developer-keys/{id}/revoke` | local | Revoke a developer API key |
| GET    | `/v1/voices` | Bearer `vsk_live_*` | Developer voice list |
| POST   | `/v1/audio/speech` | Bearer `vsk_live_*` | Developer TTS using an existing `voice_id` |
| WS     | `/v1/realtime` | Bearer `vsk_live_*` | Segmented realtime TTS over WebSocket |

```bash
curl http://localhost:3000/api/voices
curl -X POST -F 'file=@ref.wav' http://localhost:3000/api/voices
curl -X POST http://localhost:3000/api/tts \
  -H 'Content-Type: application/json' \
  -d '{"voice_id":"voice_xxx","text":"Hello from my application."}' --output speech.wav
```

Developer apps authenticate directly to the RunPod FastAPI service:

```bash
curl -H 'Authorization: Bearer vsk_live_xxx' https://YOUR-POD-8000.proxy.runpod.net/v1/voices
curl -X POST https://YOUR-POD-8000.proxy.runpod.net/v1/audio/speech \
  -H 'Authorization: Bearer vsk_live_xxx' \
  -H 'Content-Type: application/json' \
  -d '{"voice_id":"voice_xxx","text":"Hello from my bot."}' --output speech.wav
```

## Tests

```bash
cd server && ./.venv/bin/python -m pytest tests -q
```

## What was fixed in this branch

1. **Broken Chatterbox call** (`server/app/engine.py`) — the engine called
   `model.generate(text, audio_prompt=...)`; Chatterbox's argument is
   `audio_prompt_path`. TTS never worked without this fix.
2. **Hard-coded sample rate** — `torchaudio.save(..., 24000)` now uses the
   model's own `sr` attribute.
3. **No video support** — the whole point of the app ("clone a voice from a
   video"). Uploads of MP4/MOV/WEBM/MKV (and MP3/M4A/OGG/FLAC/AAC/OPUS) are now
   converted server-side to a mono 24 kHz WAV (first 30 s, configurable) with
   ffmpeg; a clear error is returned if ffmpeg is missing.
4. **Unhelpful TTS failures** — generation errors other than a missing package
   returned a bare 500. The API now logs the cause and returns a readable
   message (`503` if Chatterbox is not installed).
5. **Fragile frontend error handling** — non-JSON or missing `detail` responses
   crashed the UI instead of showing the message; upload accept-list now covers
   video/audio, not just `.wav`.
6. **Tests** — extended to cover uploads, delete behavior, developer API keys,
   developer TTS, and the segmented realtime WebSocket path.
7. **Corrupt WAV headers on converted uploads** — ffmpeg writes `0xFFFFFFFF`
   size fields when streaming WAV to a pipe (it cannot seek back), so strict
   parsers (Python's `wave`, some clients) misread the frame count. Converted
   files are now post-processed to patch the RIFF/data size fields; the saved
   reference is a fully valid WAV.

## What still needs fixing (open issues)

### High priority

- [ ] **Model weight download on first run** — `ChatterboxTTS.from_pretrained`
      pulls weights from Hugging Face. This needs internet the first time and
      can take minutes; nothing in the UI indicates this. Add a loading
      indicator/health state, and pre-download the model at startup or via a
      dedicated command.
- [ ] **Generated file growth** — every TTS call writes a WAV into
      `server/generated/` and never deletes it. Add retention (e.g. delete
      files older than 24 h, or return `FileResponse` with
      `background=BackgroundTask(os.unlink, path)`).
- [ ] **Verify TTS end-to-end** — no automated test generates audio (needs the
      model). Run `server/smoke_test.py reference.wav` once on the target
      machine to confirm the CUDA/PyTorch build and model download work.

### Medium priority

- [ ] **Reference quality** — for videos the reference is the *first* 30 s of
      audio, which may be silent or not contain the target speaker. Better:
      let the user pick a segment, or skip silence before sampling.
- [ ] **Long texts block the request** — TTS is synchronous; a 3000-character
      prompt ties up the HTTP request. For personal use this is acceptable; a
      background job + `GET /api/tts/{id}` would fix it.
- [ ] **Concurrency** — all TTS calls are serialized by a single model lock
      (intentional; the model is not thread-safe), but the server will accept
      unlimited queued requests. Add a small queue cap.

### Low priority / hardening

- [ ] **CORS wide open** (`allow_origins=["*"]`) — fine on localhost; restrict
      to `http://localhost:3000` before exposing the API.
- [ ] **Expose RunPod HTTP port 8000** — the local bridge expects a RunPod
      proxy URL like `https://8c5buydqo1yexy-8000.proxy.runpod.net`; add port
      8000 to the pod's exposed HTTP ports if that URL returns 404 or 502.
- [ ] **Upload validation** — `valid_wav()` only checks the WAV header; a
      truncated payload passes. Verify frames against the header
      (`getnframes()` × frame width vs actual size) when strictness matters.
      (The header size fields of converted uploads are now patched — the
      `getnframes()` → 2147483647 issue is resolved.)
