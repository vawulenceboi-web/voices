# Chatterbox Voice Lab - Setup Guide

This app is a local Next.js control panel that talks to a separate RunPod
FastAPI Chatterbox service through server-side Next.js route handlers.

```
Browser -> local Next API -> RunPod FastAPI -> Chatterbox GPU -> WAV
```

The browser must not call RunPod directly and must not receive the RunPod API
key. Configure the RunPod URL and key only as server-side environment variables.

## Local Environment

Create `/run/media/ksmo/D41AF0A31AF083B0/voices/.env.local`:

```bash
cd /run/media/ksmo/D41AF0A31AF083B0/voices
{
  echo 'VOICE_API_BASE_URL=https://8c5buydqo1yexy-8000.proxy.runpod.net'
  awk -F= '$1=="API_KEY"{print "VOICE_API_KEY="$2}' server/.env
  echo 'VOICE_API_TIMEOUT_MS=600000'
} > .env.local
```

Environment variables:

| Variable | Required | Notes |
| --- | --- | --- |
| `VOICE_API_BASE_URL` | Yes | RunPod FastAPI base URL. Expected public URL is `https://8c5buydqo1yexy-8000.proxy.runpod.net` when HTTP port 8000 is exposed. |
| `VOICE_API_KEY` | Yes | Bearer token forwarded only by the local Next.js backend. Do not create `NEXT_PUBLIC_*` voice key variables. |
| `VOICE_API_TIMEOUT_MS` | No | Defaults to 600000 ms. Long enough for first Chatterbox model load and generation. |

Developer API keys are created by the private dashboard through the same
server-side bridge. Configure these only in the RunPod FastAPI environment when
you want developer keys to persist:

| Variable | Required | Notes |
| --- | --- | --- |
| `DEVELOPER_API_KEYS_DATABASE_URL` | For developer keys | Supabase PostgreSQL DSN, preferably a pooler URL. |
| `DEVELOPER_API_KEY_HASH_SECRET` | Recommended | Stable server-side HMAC secret. Keep it unchanged or existing developer keys cannot be verified. |

## RunPod Service

Remote project path:

```bash
/workspace/voices/server
```

Expected remote endpoints:

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/` | Authenticated service metadata |
| `GET` | `/health` | Liveness |
| `GET` | `/api/voices` | List reference voices |
| `POST` | `/api/voices` | Upload WAV/audio/video reference |
| `POST` | `/api/tts` | Generate speech and return a complete WAV |
| `GET` | `/api/developer-keys` | Admin list of masked developer API keys |
| `POST` | `/api/developer-keys` | Admin create developer API key |
| `POST` | `/api/developer-keys/{id}/revoke` | Admin revoke developer API key |
| `GET` | `/v1/voices` | Developer list of available voices |
| `POST` | `/v1/audio/speech` | Developer TTS with an existing `voice_id` |
| `WS` | `/v1/realtime` | Developer segmented realtime voice endpoint |

Port 8000 must be exposed as an HTTP port in the RunPod dashboard. If the
public proxy returns 404 or 502, open the pod settings and add `8000` to
Expose HTTP Ports. RunPod documents the proxy format as:

```text
https://POD_ID-INTERNAL_PORT.proxy.runpod.net
```

For this pod and service port, use:

```text
https://8c5buydqo1yexy-8000.proxy.runpod.net
```

If you need to start the remote API manually:

```bash
ssh 8c5buydqo1yexy-64411fba@ssh.runpod.io -i ~/.ssh/id_ed25519
cd /workspace/voices/server
source .venv/bin/activate
DEVICE=cuda PYTHONPATH=/workspace/voices/server \
  HF_HOME=/workspace/voices/server/.cache/huggingface \
  XDG_CACHE_HOME=/workspace/voices/server/.cache \
  uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Local Development

```bash
cd /run/media/ksmo/D41AF0A31AF083B0/voices
npx pnpm install --frozen-lockfile
npx pnpm dev
```

Open:

```text
http://localhost:3000
```

The UI calls only these local routes:

| Method | Local route | Upstream RunPod route |
| --- | --- | --- |
| `GET` | `/api/health` | `/health` |
| `GET` | `/api/voices` | `/api/voices` |
| `POST` | `/api/voices` | `/api/voices` |
| `POST` | `/api/tts` | `/api/tts` |
| `GET` | `/api/developer-keys` | `/api/developer-keys` |
| `POST` | `/api/developer-keys` | `/api/developer-keys` |
| `POST` | `/api/developer-keys/{id}/revoke` | `/api/developer-keys/{id}/revoke` |
| `DELETE` | `/api/voices/{voice_id}` | `/api/voices/{voice_id}` |

## Verification Commands

Check local backend health through Next.js:

```bash
curl -i http://localhost:3000/api/health
```

List voices through the local backend:

```bash
curl -i http://localhost:3000/api/voices
```

Upload a voice sample through the local backend:

```bash
curl -X POST -F 'file=@server/voices/voice_cb368780d7.wav;type=audio/wav' \
  http://localhost:3000/api/voices
```

Generate TTS through the local backend:

```bash
curl -X POST http://localhost:3000/api/tts \
  -H 'Content-Type: application/json' \
  -d '{"voice_id":"voice_abc1234567","text":"Hello from my application."}' \
  --output speech.wav
```

Verify the RunPod GPU during generation:

```bash
ssh 8c5buydqo1yexy-64411fba@ssh.runpod.io -i ~/.ssh/id_ed25519
nvidia-smi
```

## Production Build

```bash
cd /run/media/ksmo/D41AF0A31AF083B0/voices
npx tsc --noEmit
npx pnpm build
```

For deployment, configure the same server-side variables in the hosting
provider:

```text
VOICE_API_BASE_URL=https://8c5buydqo1yexy-8000.proxy.runpod.net
VOICE_API_KEY=<set as a secret using the same value as RunPod API_KEY>
VOICE_API_TIMEOUT_MS=600000
```

Do not configure `VOICE_API_KEY` as a public client variable.
