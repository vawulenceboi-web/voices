'use client'

import { useEffect, useState } from 'react'
import { ArrowUpRight, Download, Headphones, Mic2, RefreshCw, Upload, Volume2 } from 'lucide-react'

const API_URL = process.env.NEXT_PUBLIC_VOICE_API_URL || 'http://localhost:8000'
const API_KEY = process.env.NEXT_PUBLIC_VOICE_API_KEY || 'change-me'
type Voice = { voice_id: string; filename: string; size_bytes: number }

export default function Page() {
  const [voices, setVoices] = useState<Voice[]>([])
  const [voiceId, setVoiceId] = useState('')
  const [text, setText] = useState('')
  const [audioUrl, setAudioUrl] = useState('')
  const [status, setStatus] = useState('')
  const [busy, setBusy] = useState(false)
  const headers = { Authorization: `Bearer ${API_KEY}` }

  async function loadVoices() {
    setStatus('Loading voices…')
    try {
      const response = await fetch(`${API_URL}/api/voices`, { headers })
      if (!response.ok) throw new Error('Could not reach the voice server.')
      const data = await response.json()
      setVoices(data.voices)
      if (!voiceId && data.voices[0]) setVoiceId(data.voices[0].voice_id)
      setStatus(data.voices.length ? '' : 'Upload a WAV reference to get started.')
    } catch (error) { setStatus(error instanceof Error ? error.message : 'Could not load voices.') }
  }
  useEffect(() => { loadVoices() }, [])

  async function upload(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    if (!file) return
    setBusy(true); setStatus('Saving reference…')
    try {
      const response = await fetch(`${API_URL}/api/voices`, { method: 'POST', headers, body: (() => { const form = new FormData(); form.append('file', file); return form })() })
      if (!response.ok) throw new Error((await response.json()).detail || 'Upload failed.')
      const voice = await response.json(); setVoiceId(voice.voice_id); await loadVoices(); setStatus('Reference saved.')
    } catch (error) { setStatus(error instanceof Error ? error.message : 'Upload failed.') }
    finally { setBusy(false); event.target.value = '' }
  }
  async function generate() {
    if (!voiceId || !text.trim()) return setStatus('Choose a voice and enter text first.')
    setBusy(true); setStatus('Generating WAV…'); setAudioUrl('')
    try {
      const response = await fetch(`${API_URL}/api/tts`, { method: 'POST', headers: { ...headers, 'Content-Type': 'application/json' }, body: JSON.stringify({ voice_id: voiceId, text }) })
      if (!response.ok) throw new Error((await response.json()).detail || 'Generation failed.')
      setAudioUrl(URL.createObjectURL(await response.blob())); setStatus('Ready to listen.')
    } catch (error) { setStatus(error instanceof Error ? error.message : 'Generation failed.') }
    finally { setBusy(false) }
  }

  return <main className="min-h-screen bg-background text-foreground"><div className="mx-auto flex min-h-screen max-w-5xl flex-col px-5 py-6 sm:px-8 sm:py-10">
    <header className="flex items-center justify-between border-b border-border pb-6"><div className="flex items-center gap-3"><span className="grid size-10 place-items-center rounded-xl bg-primary text-primary-foreground"><Mic2 size={19} /></span><div><p className="font-mono text-xs uppercase tracking-[0.22em] text-muted-foreground">Local voice lab</p><h1 className="font-serif text-xl font-semibold">Chatterbox server</h1></div></div><a className="hidden min-h-11 items-center gap-2 text-sm text-muted-foreground hover:text-foreground sm:flex" href={`${API_URL}/health`} target="_blank" rel="noreferrer">API health <ArrowUpRight size={15} /></a></header>
    <section className="grid flex-1 gap-8 py-10 lg:grid-cols-[0.78fr_1.22fr] lg:items-start lg:gap-16"><div><p className="mb-4 font-mono text-xs uppercase tracking-[0.22em] text-accent">Independent TTS infrastructure</p><h2 className="max-w-xl font-serif text-5xl leading-[0.98] tracking-tight sm:text-6xl">Give your app a voice it can call.</h2><p className="mt-6 max-w-md text-base leading-7 text-muted-foreground">Store reference audio locally, generate speech through one clean HTTP endpoint, and keep Chatterbox out of your main application.</p><div className="mt-8 flex flex-wrap gap-3 text-xs text-muted-foreground"><span className="rounded-full border border-border px-3 py-2">Bearer protected</span><span className="rounded-full border border-border px-3 py-2">Raw WAV output</span></div></div>
      <div className="space-y-4"><div className="panel"><div className="flex items-center justify-between"><div><p className="eyebrow">01 / Reference voices</p><h3 className="panel-title">Choose a voice</h3></div><button className="icon-button" onClick={loadVoices} aria-label="Refresh voices"><RefreshCw size={17} /></button></div><div className="mt-5 flex flex-col gap-3 sm:flex-row"><select className="control min-h-12 flex-1" value={voiceId} onChange={e => setVoiceId(e.target.value)} aria-label="Voice"><option value="">Select a saved voice</option>{voices.map(voice => <option key={voice.voice_id} value={voice.voice_id}>{voice.voice_id} · {Math.round(voice.size_bytes / 1024)} KB</option>)}</select><label className="button-secondary"><Upload size={16} /> Upload WAV<input className="sr-only" type="file" accept="audio/wav,.wav" onChange={upload} disabled={busy} /></label></div></div>
        <div className="panel"><p className="eyebrow">02 / Synthesis</p><h3 className="panel-title">Write a line</h3><textarea className="control mt-5 min-h-36 w-full resize-y" maxLength={3000} placeholder="Hello from my application." value={text} onChange={e => setText(e.target.value)} /><div className="mt-3 flex items-center justify-between gap-4"><span className="text-xs text-muted-foreground">{text.length} / 3000 characters</span><button className="button-primary" onClick={generate} disabled={busy || !voiceId || !text.trim()}><Volume2 size={16} /> {busy ? 'Working…' : 'Generate speech'}</button></div></div>
        {status && <p className="rounded-lg border border-border bg-muted px-4 py-3 text-sm text-muted-foreground" role="status">{status}</p>}
        {audioUrl && <div className="panel border-accent/40"><div className="flex items-center gap-3"><span className="grid size-10 place-items-center rounded-full bg-accent text-accent-foreground"><Headphones size={18} /></span><div><p className="eyebrow">03 / Output</p><h3 className="panel-title">Your WAV is ready</h3></div></div><audio className="mt-5 w-full" controls src={audioUrl} /><a className="button-secondary mt-4 w-full justify-center" href={audioUrl} download="chatterbox-speech.wav"><Download size={16} /> Download WAV</a></div>}
      </div></section><footer className="border-t border-border pt-5 text-xs text-muted-foreground">FastAPI at <span className="font-mono">{API_URL}</span> · No queues, databases, or provider lock-in.</footer>
  </div></main>
}
