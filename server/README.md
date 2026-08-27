# Standalone Chatterbox Voice Server

A single-process FastAPI service. The calling application only needs `VOICE_API_URL`, `VOICE_API_KEY`, and `VOICE_ID`; it never imports Chatterbox.

## Setup

```bash
cd server
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# Install the current Chatterbox package for your CUDA/PyTorch setup:
pip install chatterbox-tts
cp .env.example .env
```

Set `DEVICE=cpu` when testing without CUDA. Before using the API, generate and listen to one local reference sample:

```bash
python smoke_test.py ./reference.wav
```

## Run and open

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```
Open `http://localhost:3000` for the browser control panel, and set `NEXT_PUBLIC_VOICE_API_URL` plus `NEXT_PUBLIC_VOICE_API_KEY` in the Next app environment.

The interface uploads a WAV reference, lists voices, generates speech, and provides playback/download. No database, queue, Redis, Twilio, or LiveKit is required.

## API

```bash
curl -H 'Authorization: Bearer change-me' http://localhost:8000/api/voices
curl -X POST -H 'Authorization: Bearer change-me' -F 'file=@reference.wav' http://localhost:8000/api/voices
curl -X POST http://localhost:8000/api/tts -H 'Authorization: Bearer change-me' -H 'Content-Type: application/json' -d '{"voice_id":"voice_001","text":"Hello from my application."}' --output speech.wav
```

```python
import requests
response = requests.post("http://localhost:8000/api/tts", headers={"Authorization": "Bearer MY_API_KEY"}, json={"voice_id": "voice_001", "text": "Hello from my application."})
response.raise_for_status()
with open("speech.wav", "wb") as f: f.write(response.content)
```
