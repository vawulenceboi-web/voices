'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import type { ChangeEvent } from 'react'
import {
  AlertCircle,
  Ban,
  CheckCircle2,
  Copy,
  Download,
  KeyRound,
  Loader2,
  Mic2,
  Play,
  Plus,
  RefreshCw,
  Square,
  Trash2,
  Upload,
  Volume2,
} from 'lucide-react'

type Voice = {
  id?: string
  voice_id: string
  name?: string
  display_name?: string
  preview_available?: boolean
}

type Health = {
  service: 'checking' | 'online' | 'warming' | 'offline'
  detail?: string
}

type Message = {
  tone: 'neutral' | 'good' | 'bad'
  text: string
}

type GeneratedAudio = {
  url: string
  filename: string
}

type PreviewAudio = {
  voiceId: string
  url: string
}

type DeveloperApiKey = {
  id: string
  developer_name: string
  masked_key: string
  active: boolean
  created_at?: string
  revoked_at?: string | null
}

type CreatedDeveloperApiKey = DeveloperApiKey & {
  api_key: string
}

const MAX_TEXT_LENGTH = 3000
const MAX_DEVELOPER_NAME_LENGTH = 120
const ACCEPT = 'audio/wav,.wav,audio/mpeg,.mp3,audio/mp4,.m4a,audio/aac,.aac,audio/flac,.flac,audio/ogg,.ogg,audio/opus,.opus,video/mp4,.mp4,video/quicktime,.mov,video/webm,.webm,video/x-matroska,.mkv,video/x-msvideo,.avi,video/x-m4v,.m4v'
const SUPPORTED_EXTENSIONS = ['wav', 'mp3', 'm4a', 'aac', 'flac', 'ogg', 'opus', 'mp4', 'mov', 'webm', 'mkv', 'avi', 'm4v']

function detailFromJson(body: unknown, fallback: string) {
  if (body && typeof body === 'object' && 'detail' in body) {
    const detail = (body as { detail?: unknown }).detail
    if (typeof detail === 'string') return detail
    if (detail) return JSON.stringify(detail)
  }
  return fallback
}

async function errorDetail(response: Response) {
  try {
    return detailFromJson(await response.json(), `Request failed (${response.status}).`)
  } catch {
    return `Request failed (${response.status}).`
  }
}

function xhrErrorDetail(status: number, responseText: string) {
  try {
    return detailFromJson(JSON.parse(responseText), `Upload failed (${status}).`)
  } catch {
    return responseText.trim() || `Upload failed (${status}).`
  }
}

function voiceKey(voice: Voice) {
  return voice.id || voice.voice_id
}

function voiceName(voice?: Voice) {
  if (!voice) return 'None'
  return voice.display_name || voice.name || 'Saved voice'
}

function filenameFromDisposition(value: string | null, fallback: string) {
  if (!value) return fallback
  const utfMatch = value.match(/filename\*=UTF-8''([^;]+)/i)
  if (utfMatch?.[1]) return decodeURIComponent(utfMatch[1].replace(/"/g, ''))
  const match = value.match(/filename="?([^";]+)"?/i)
  return match?.[1] || fallback
}

function hasSupportedExtension(file: File) {
  const suffix = file.name.split('.').pop()?.toLowerCase()
  return Boolean(suffix && SUPPORTED_EXTENSIONS.includes(suffix))
}

function statusLabel(health: Health) {
  if (health.service === 'online') return 'Online'
  if (health.service === 'warming') return 'Warming up'
  if (health.service === 'offline') return 'Offline'
  return 'Checking'
}

export default function Page() {
  const fileInputRef = useRef<HTMLInputElement>(null)
  const previewPlayerRef = useRef<HTMLAudioElement>(null)
  const [voices, setVoices] = useState<Voice[]>([])
  const [selectedVoiceId, setSelectedVoiceId] = useState('')
  const [voiceNameInput, setVoiceNameInput] = useState('')
  const [referenceFile, setReferenceFile] = useState<File | null>(null)
  const [text, setText] = useState('')
  const [health, setHealth] = useState<Health>({ service: 'checking' })
  const [message, setMessage] = useState<Message | null>(null)
  const [hydrated, setHydrated] = useState(false)
  const [loadingVoices, setLoadingVoices] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState<number | null>(null)
  const [previewingVoiceId, setPreviewingVoiceId] = useState('')
  const [playingPreviewVoiceId, setPlayingPreviewVoiceId] = useState('')
  const [deletingVoiceId, setDeletingVoiceId] = useState('')
  const [previewAudio, setPreviewAudio] = useState<PreviewAudio | null>(null)
  const [generating, setGenerating] = useState(false)
  const [generatedAudio, setGeneratedAudio] = useState<GeneratedAudio | null>(null)
  const [developerKeys, setDeveloperKeys] = useState<DeveloperApiKey[]>([])
  const [developerName, setDeveloperName] = useState('')
  const [loadingDeveloperKeys, setLoadingDeveloperKeys] = useState(false)
  const [creatingDeveloperKey, setCreatingDeveloperKey] = useState(false)
  const [revokingDeveloperKeyId, setRevokingDeveloperKeyId] = useState('')
  const [developerKeyError, setDeveloperKeyError] = useState('')
  const [createdDeveloperKey, setCreatedDeveloperKey] = useState<CreatedDeveloperApiKey | null>(null)

  const selectedVoice = useMemo(
    () => voices.find(voice => voice.voice_id === selectedVoiceId),
    [voices, selectedVoiceId],
  )
  const busy = loadingVoices || uploading || generating || Boolean(deletingVoiceId)
  const cleanText = text.trim()
  const cleanVoiceName = voiceNameInput.trim()
  const cleanDeveloperName = developerName.trim()
  const canGenerate = Boolean(selectedVoiceId && cleanText && !busy)
  const canAddVoice = Boolean(cleanVoiceName && referenceFile && !busy)
  const developerKeyBusy = loadingDeveloperKeys || creatingDeveloperKey || Boolean(revokingDeveloperKeyId)
  const canCreateDeveloperKey = Boolean(cleanDeveloperName && !developerKeyBusy)
  const disabledAfterHydration = (disabled: boolean) => hydrated ? disabled : undefined

  async function checkHealth() {
    setHealth({ service: 'checking' })
    try {
      const response = await fetch('/api/health', { cache: 'no-store' })
      if (!response.ok) throw new Error(await errorDetail(response))
      const data = await response.json()
      const reachable = Boolean(data?.runpod?.reachable)
      const modelLoaded = Boolean(data?.runpod?.engine?.model_loaded)
      setHealth({
        service: reachable ? (modelLoaded ? 'online' : 'warming') : 'offline',
        detail: reachable ? undefined : data?.runpod?.detail || 'RunPod voice API is unavailable.',
      })
    } catch (error) {
      setHealth({
        service: 'offline',
        detail: error instanceof Error ? error.message : 'Local voice API is unavailable.',
      })
    }
  }

  async function loadVoices(preferredVoiceId?: string) {
    setLoadingVoices(true)
    try {
      const response = await fetch('/api/voices', { cache: 'no-store' })
      if (!response.ok) throw new Error(await errorDetail(response))
      const data = await response.json()
      const nextVoices = Array.isArray(data.voices) ? data.voices as Voice[] : []
      setVoices(nextVoices)

      const nextVoiceId = preferredVoiceId || selectedVoiceId
      if (nextVoiceId && nextVoices.some(voice => voice.voice_id === nextVoiceId)) {
        setSelectedVoiceId(nextVoiceId)
      } else if (selectedVoiceId) {
        setSelectedVoiceId('')
      }

      if (nextVoices.length === 0) {
        setMessage({ tone: 'neutral', text: 'No saved voices yet.' })
      } else {
        setMessage(null)
      }
    } catch (error) {
      setMessage({ tone: 'bad', text: error instanceof Error ? error.message : 'Could not load voices.' })
    } finally {
      setLoadingVoices(false)
    }
  }

  async function loadDeveloperKeys() {
    setLoadingDeveloperKeys(true)
    setDeveloperKeyError('')

    try {
      const response = await fetch('/api/developer-keys', { cache: 'no-store' })
      if (!response.ok) throw new Error(await errorDetail(response))
      const data = await response.json()
      setDeveloperKeys(Array.isArray(data.keys) ? data.keys as DeveloperApiKey[] : [])
    } catch (error) {
      setDeveloperKeyError(error instanceof Error ? error.message : 'Could not load developer API keys.')
    } finally {
      setLoadingDeveloperKeys(false)
    }
  }

  useEffect(() => {
    setHydrated(true)
  }, [])

  useEffect(() => {
    if (!hydrated) return
    checkHealth()
    loadVoices()
    loadDeveloperKeys()
  }, [hydrated])

  useEffect(() => {
    return () => {
      if (previewAudio?.url) URL.revokeObjectURL(previewAudio.url)
    }
  }, [previewAudio?.url])

  useEffect(() => {
    return () => {
      if (generatedAudio?.url) URL.revokeObjectURL(generatedAudio.url)
    }
  }, [generatedAudio?.url])

  async function previewVoice(voice: Voice) {
    if (voice.preview_available === false) {
      setMessage({ tone: 'bad', text: 'Preview is not available for this voice.' })
      return
    }

    previewPlayerRef.current?.pause()
    if (previewPlayerRef.current) previewPlayerRef.current.currentTime = 0
    setPlayingPreviewVoiceId('')
    setPreviewingVoiceId(voice.voice_id)
    setMessage(null)

    try {
      const response = await fetch(`/api/voices/${encodeURIComponent(voice.voice_id)}/preview`, { cache: 'no-store' })
      if (!response.ok) throw new Error(await errorDetail(response))
      const url = URL.createObjectURL(await response.blob())
      setPreviewAudio({ voiceId: voice.voice_id, url })
      setPlayingPreviewVoiceId(voice.voice_id)
    } catch (error) {
      setMessage({ tone: 'bad', text: error instanceof Error ? error.message : 'Could not load preview.' })
    } finally {
      setPreviewingVoiceId('')
    }
  }

  function stopPreview() {
    previewPlayerRef.current?.pause()
    if (previewPlayerRef.current) previewPlayerRef.current.currentTime = 0
    setPlayingPreviewVoiceId('')
  }

  function onFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0] || null
    setReferenceFile(file)
    if (file && !hasSupportedExtension(file)) {
      setMessage({ tone: 'bad', text: 'Unsupported audio or video format.' })
    } else {
      setMessage(null)
    }
  }

  async function addVoice() {
    const file = referenceFile
    if (!cleanVoiceName) {
      setMessage({ tone: 'bad', text: 'Enter a voice name.' })
      return
    }
    if (!file) {
      setMessage({ tone: 'bad', text: 'Choose a reference audio or video file.' })
      return
    }
    if (file.size === 0) {
      setMessage({ tone: 'bad', text: 'Choose a non-empty reference file.' })
      return
    }
    if (!hasSupportedExtension(file)) {
      setMessage({ tone: 'bad', text: 'Unsupported audio or video format.' })
      return
    }

    setUploading(true)
    setUploadProgress(0)
    setMessage({ tone: 'neutral', text: 'Adding voice.' })

    try {
      const voice = await new Promise<Voice>((resolve, reject) => {
        const form = new FormData()
        form.append('display_name', cleanVoiceName)
        form.append('file', file, file.name || 'reference.wav')

        const request = new XMLHttpRequest()
        request.open('POST', '/api/voices')
        request.timeout = 600_000
        request.upload.onprogress = event => {
          if (event.lengthComputable) {
            setUploadProgress(Math.round((event.loaded / event.total) * 100))
          }
        }
        request.onload = () => {
          if (request.status >= 200 && request.status < 300) {
            try {
              resolve(JSON.parse(request.responseText) as Voice)
            } catch {
              reject(new Error('Voice was added but returned an invalid response.'))
            }
            return
          }
          reject(new Error(xhrErrorDetail(request.status, request.responseText)))
        }
        request.onerror = () => reject(new Error('RunPod voice upload is unavailable.'))
        request.ontimeout = () => reject(new Error('RunPod voice upload timed out.'))
        request.send(form)
      })

      setUploadProgress(100)
      setVoiceNameInput('')
      setReferenceFile(null)
      if (fileInputRef.current) fileInputRef.current.value = ''
      await loadVoices()
      setMessage({ tone: 'good', text: `${voiceName(voice)} was added.` })
    } catch (error) {
      setMessage({ tone: 'bad', text: error instanceof Error ? error.message : 'Add Voice failed.' })
    } finally {
      setUploading(false)
      setUploadProgress(null)
    }
  }

  function useVoice(voice: Voice) {
    setSelectedVoiceId(voice.voice_id)
    setMessage({ tone: 'good', text: `Selected Voice: ${voiceName(voice)}.` })
  }

  async function deleteSavedVoice(voice: Voice) {
    const name = voiceName(voice)
    if (!window.confirm(`Delete ${name}?`)) return

    if (playingPreviewVoiceId === voice.voice_id) {
      stopPreview()
    }

    setDeletingVoiceId(voice.voice_id)
    setMessage({ tone: 'neutral', text: `Deleting ${name}.` })

    try {
      const response = await fetch(`/api/voices/${encodeURIComponent(voice.voice_id)}`, {
        method: 'DELETE',
        cache: 'no-store',
      })
      if (!response.ok) throw new Error(await errorDetail(response))

      if (selectedVoiceId === voice.voice_id) {
        setSelectedVoiceId('')
      }
      if (previewAudio?.voiceId === voice.voice_id) {
        setPreviewAudio(null)
        setPlayingPreviewVoiceId('')
      }
      setVoices(previous => previous.filter(item => item.voice_id !== voice.voice_id))
      await loadVoices()
      setMessage({ tone: 'good', text: `${name} was deleted.` })
    } catch (error) {
      setMessage({ tone: 'bad', text: error instanceof Error ? error.message : 'Could not delete voice.' })
    } finally {
      setDeletingVoiceId('')
    }
  }

  async function generateDeveloperKey() {
    if (!cleanDeveloperName) {
      setDeveloperKeyError('Developer name is required.')
      return
    }
    if (cleanDeveloperName.length > MAX_DEVELOPER_NAME_LENGTH) {
      setDeveloperKeyError(`Developer name exceeds ${MAX_DEVELOPER_NAME_LENGTH} characters.`)
      return
    }

    setCreatingDeveloperKey(true)
    setDeveloperKeyError('')

    try {
      const response = await fetch('/api/developer-keys', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ developer_name: cleanDeveloperName }),
      })
      if (!response.ok) throw new Error(await errorDetail(response))

      const created = await response.json() as CreatedDeveloperApiKey
      const { api_key: _apiKey, ...maskedKey } = created
      setCreatedDeveloperKey(created)
      setDeveloperName('')
      setDeveloperKeys(previous => [maskedKey, ...previous.filter(key => key.id !== created.id)])
      setMessage({ tone: 'good', text: 'Developer API key created.' })
    } catch (error) {
      setDeveloperKeyError(error instanceof Error ? error.message : 'Could not generate developer API key.')
    } finally {
      setCreatingDeveloperKey(false)
    }
  }

  async function copyCreatedDeveloperKey() {
    if (!createdDeveloperKey?.api_key) return
    try {
      await navigator.clipboard.writeText(createdDeveloperKey.api_key)
      setMessage({ tone: 'good', text: 'API key copied.' })
    } catch {
      setMessage({ tone: 'bad', text: 'Could not copy API key.' })
    }
  }

  async function revokeDeveloperKey(key: DeveloperApiKey) {
    if (!window.confirm(`Revoke the API key for ${key.developer_name}?`)) return

    setRevokingDeveloperKeyId(key.id)
    setDeveloperKeyError('')

    try {
      const response = await fetch(`/api/developer-keys/${encodeURIComponent(key.id)}/revoke`, {
        method: 'POST',
        cache: 'no-store',
      })
      if (!response.ok) throw new Error(await errorDetail(response))

      const revoked = await response.json() as DeveloperApiKey
      setDeveloperKeys(previous => previous.map(item => item.id === revoked.id ? revoked : item))
      if (createdDeveloperKey?.id === revoked.id) {
        setCreatedDeveloperKey(null)
      }
      setMessage({ tone: 'good', text: 'Developer API key revoked.' })
    } catch (error) {
      setDeveloperKeyError(error instanceof Error ? error.message : 'Could not revoke developer API key.')
    } finally {
      setRevokingDeveloperKeyId('')
    }
  }

  async function generate() {
    if (!selectedVoiceId) {
      setMessage({ tone: 'bad', text: 'Select a voice first.' })
      return
    }
    if (!cleanText) {
      setMessage({ tone: 'bad', text: 'Enter text before generating speech.' })
      return
    }
    if (cleanText.length > MAX_TEXT_LENGTH) {
      setMessage({ tone: 'bad', text: `Text exceeds ${MAX_TEXT_LENGTH} characters.` })
      return
    }

    setGenerating(true)
    setGeneratedAudio(null)
    setMessage({ tone: 'neutral', text: `Generating speech with ${voiceName(selectedVoice)}.` })

    try {
      const response = await fetch('/api/tts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ voice_id: selectedVoiceId, text: cleanText }),
      })
      if (!response.ok) throw new Error(await errorDetail(response))

      const blob = await response.blob()
      const url = URL.createObjectURL(blob)
      const filename = filenameFromDisposition(
        response.headers.get('content-disposition'),
        `${selectedVoiceId}-${Date.now()}.wav`,
      )

      setGeneratedAudio({ url, filename })
      setMessage({ tone: 'good', text: 'Generated audio is ready.' })
    } catch (error) {
      setMessage({ tone: 'bad', text: error instanceof Error ? error.message : 'Generation failed.' })
    } finally {
      setGenerating(false)
    }
  }

  return (
    <main className="studio-shell">
      <div className="studio-frame">
        <header className="studio-header">
          <div className="brand-lockup">
            <span className="brand-mark"><Mic2 size={20} /></span>
            <h1>Voice Studio</h1>
          </div>
          <div className={`service-status ${health.service}`} aria-label={`Service status: ${statusLabel(health)}`}>
            <span />
            {statusLabel(health)}
          </div>
        </header>

        <div className="studio-grid">
          <section className="studio-section voice-library" aria-label="Available voices">
            <div className="section-heading">
              <h2>Available Voices</h2>
              <button className="icon-button" onClick={() => loadVoices()} disabled={disabledAfterHydration(loadingVoices)} type="button" title="Refresh voices">
                <RefreshCw className={loadingVoices ? 'spin' : ''} size={17} />
              </button>
            </div>

            <div className="voice-list">
              {loadingVoices && voices.length === 0 ? (
                Array.from({ length: 3 }).map((_, index) => <div className="voice-skeleton" key={index} />)
              ) : voices.length === 0 ? (
                <div className="empty-state">No voices added yet.</div>
              ) : (
                voices.map(voice => {
                  const selected = voice.voice_id === selectedVoiceId
                  const playing = playingPreviewVoiceId === voice.voice_id
                  const loadingPreview = previewingVoiceId === voice.voice_id
                  const deleting = deletingVoiceId === voice.voice_id

                  return (
                    <article className={selected ? 'voice-row selected' : 'voice-row'} key={voiceKey(voice)}>
                      <div className="voice-row-top">
                        <h3>{voiceName(voice)}</h3>
                        {selected && <span className="selected-mark"><CheckCircle2 size={14} />Selected</span>}
                      </div>
                      <div className="voice-actions">
                        <button className="secondary-button" onClick={() => previewVoice(voice)} disabled={busy || voice.preview_available === false} type="button">
                          {loadingPreview ? <Loader2 className="spin" size={15} /> : playing ? <Volume2 size={15} /> : <Play size={15} />}
                          {playing ? 'Playing' : 'Preview'}
                        </button>
                        <button className="primary-button" onClick={() => useVoice(voice)} disabled={busy} type="button">
                          Use Voice
                        </button>
                        <button className="danger-button" onClick={() => deleteSavedVoice(voice)} disabled={busy} type="button">
                          {deleting ? <Loader2 className="spin" size={15} /> : <Trash2 size={15} />}
                          Delete
                        </button>
                      </div>
                      {playing && (
                        <div className="preview-player">
                          <audio
                            ref={previewPlayerRef}
                            controls
                            autoPlay
                            src={previewAudio?.voiceId === voice.voice_id ? previewAudio.url : undefined}
                            onEnded={() => setPlayingPreviewVoiceId('')}
                            onPause={() => setPlayingPreviewVoiceId(current => current === voice.voice_id ? '' : current)}
                            onPlay={() => setPlayingPreviewVoiceId(voice.voice_id)}
                          />
                          <button className="icon-button small" onClick={stopPreview} type="button" title="Stop preview">
                            <Square size={14} />
                          </button>
                        </div>
                      )}
                    </article>
                  )
                })
              )}
            </div>
          </section>

          <div className="workspace-stack">
            <section className="studio-section" aria-label="Add voice">
              <div className="section-heading">
                <h2>Add Voice</h2>
              </div>
              <div className="form-grid">
                <label className="field-label" htmlFor="voice-name">Voice Name</label>
                <input
                  id="voice-name"
                  className="text-input"
                  value={voiceNameInput}
                  onChange={event => setVoiceNameInput(event.target.value)}
                  maxLength={80}
                  placeholder="James"
                  autoComplete="off"
                  disabled={disabledAfterHydration(busy)}
                />

                <label className="field-label" htmlFor="voice-reference">Reference Audio / Video</label>
                <div className="file-picker">
                  <input
                    ref={fileInputRef}
                    id="voice-reference"
                    className="sr-only"
                    type="file"
                    accept={ACCEPT}
                    onChange={onFileChange}
                    disabled={disabledAfterHydration(busy)}
                  />
                  <button className="secondary-button" onClick={() => fileInputRef.current?.click()} disabled={disabledAfterHydration(busy)} type="button">
                    <Upload size={16} />
                    Choose File
                  </button>
                  <span>{referenceFile?.name || 'No file chosen'}</span>
                </div>

                {typeof uploadProgress === 'number' && (
                  <div className="progress-track" aria-label="Upload progress">
                    <span style={{ width: `${uploadProgress}%` }} />
                  </div>
                )}

                <button className="primary-button add-button" onClick={addVoice} disabled={disabledAfterHydration(!canAddVoice)} type="button">
                  {uploading ? <Loader2 className="spin" size={16} /> : <Plus size={16} />}
                  Add Voice
                </button>
              </div>
            </section>

            <section className="studio-section synthesis-panel" aria-label="Generate speech">
              <div className="section-heading">
                <h2>Generate Speech</h2>
              </div>

              <div className="selected-voice">
                <span>Selected Voice:</span>
                <strong>{selectedVoice ? voiceName(selectedVoice) : 'Select a voice first.'}</strong>
              </div>

              <label className="field-label" htmlFor="tts-text">Text</label>
              <textarea
                id="tts-text"
                className="text-editor"
                maxLength={MAX_TEXT_LENGTH}
                value={text}
                onChange={event => setText(event.target.value)}
                disabled={disabledAfterHydration(busy)}
              />
              <div className="generate-row">
                <span>{text.length} / {MAX_TEXT_LENGTH}</span>
                <button className="primary-button" onClick={generate} disabled={disabledAfterHydration(!canGenerate)} type="button">
                  {generating ? <Loader2 className="spin" size={16} /> : <Volume2 size={16} />}
                  {generating ? 'Generating' : 'Generate'}
                </button>
              </div>
            </section>

            <section className="studio-section" aria-label="Generated audio">
              <div className="section-heading">
                <h2>Generated Audio</h2>
              </div>

              {generatedAudio ? (
                <div className="output-ready">
                  <audio className="audio-control" controls src={generatedAudio.url} />
                  <div className="output-actions">
                    <a className="secondary-button" href={generatedAudio.url} download={generatedAudio.filename}>
                      <Download size={16} />
                      Download
                    </a>
                    <button className="primary-button" onClick={generate} disabled={disabledAfterHydration(!canGenerate)} type="button">
                      <Volume2 size={16} />
                      Generate Again
                    </button>
                  </div>
                </div>
              ) : (
                <div className="empty-state">No generated audio yet.</div>
              )}
            </section>

            <section className="studio-section developer-keys" aria-label="Developer API keys">
              <div className="section-heading">
                <h2>Developer API Keys</h2>
                <button className="icon-button" onClick={loadDeveloperKeys} disabled={disabledAfterHydration(loadingDeveloperKeys)} type="button" title="Refresh developer API keys">
                  <RefreshCw className={loadingDeveloperKeys ? 'spin' : ''} size={17} />
                </button>
              </div>

              <div className="form-grid">
                <label className="field-label" htmlFor="developer-name">Developer Name</label>
                <input
                  id="developer-name"
                  className="text-input"
                  value={developerName}
                  onChange={event => setDeveloperName(event.target.value)}
                  maxLength={MAX_DEVELOPER_NAME_LENGTH}
                  placeholder="Acme Sales Bot"
                  autoComplete="off"
                  disabled={disabledAfterHydration(developerKeyBusy)}
                />

                <button className="primary-button add-button" onClick={generateDeveloperKey} disabled={disabledAfterHydration(!canCreateDeveloperKey)} type="button">
                  {creatingDeveloperKey ? <Loader2 className="spin" size={16} /> : <KeyRound size={16} />}
                  Generate API Key
                </button>
              </div>

              {createdDeveloperKey && (
                <div className="created-key-panel">
                  <div>
                    <h3>API Key Created</h3>
                    <p>Copy this key now. It will not be shown again.</p>
                  </div>
                  <dl>
                    <div>
                      <dt>Developer</dt>
                      <dd>{createdDeveloperKey.developer_name}</dd>
                    </div>
                    <div>
                      <dt>API Key</dt>
                      <dd className="one-time-key">
                        <code>{createdDeveloperKey.api_key}</code>
                        <button className="icon-button small" onClick={copyCreatedDeveloperKey} type="button" title="Copy API key">
                          <Copy size={14} />
                        </button>
                      </dd>
                    </div>
                  </dl>
                </div>
              )}

              <div className="developer-key-list">
                {developerKeyError ? (
                  <div className="message bad" role="status">
                    <AlertCircle size={17} />
                    <span>{developerKeyError}</span>
                  </div>
                ) : loadingDeveloperKeys && developerKeys.length === 0 ? (
                  <div className="empty-state">Loading developer API keys.</div>
                ) : developerKeys.length === 0 ? (
                  <div className="empty-state">No developer API keys yet.</div>
                ) : (
                  developerKeys.map(key => {
                    const revoking = revokingDeveloperKeyId === key.id

                    return (
                      <article className="developer-key-row" key={key.id}>
                        <div className="developer-key-main">
                          <h3>{key.developer_name}</h3>
                          <code>{key.masked_key}</code>
                        </div>
                        <div className="developer-key-actions">
                          <span className={key.active ? 'status-pill active' : 'status-pill revoked'}>
                            {key.active ? 'Active' : 'Revoked'}
                          </span>
                          <button className="danger-button" onClick={() => revokeDeveloperKey(key)} disabled={disabledAfterHydration(developerKeyBusy || !key.active)} type="button">
                            {revoking ? <Loader2 className="spin" size={15} /> : <Ban size={15} />}
                            Revoke
                          </button>
                        </div>
                      </article>
                    )
                  })
                )}
              </div>
            </section>

            {message && (
              <div className={`message ${message.tone}`} role="status" aria-live="polite">
                <MessageIcon tone={message.tone} />
                <span>{message.text}</span>
              </div>
            )}

            {health.detail && <p className="service-detail">{health.detail}</p>}
          </div>
        </div>
      </div>
    </main>
  )
}

function MessageIcon({ tone }: { tone: Message['tone'] }) {
  if (tone === 'bad') return <AlertCircle size={17} />
  if (tone === 'good') return <CheckCircle2 size={17} />
  return <Loader2 className="spin" size={17} />
}
