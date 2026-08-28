export type Voice = {
  id?: string
  voice_id: string
  name?: string
  display_name?: string
  filename?: string
  size_bytes?: number
  created_at?: string
  updated_at?: string
  preview_available?: boolean
}

export type VoiceListResponse = {
  voices: Voice[]
}

export type UploadedVoice = Voice & {
  voice_id: string
}

export type VoiceHealthResponse = {
  status: string
  engine?: {
    device?: string
    model_loaded?: boolean
    audio_io_loaded?: boolean
    conditioning_cache?: {
      size?: number
      max_size?: number
    }
  }
}

export type DeveloperApiKey = {
  id: string
  developer_name: string
  key_prefix: string
  key_last4: string
  masked_key: string
  active: boolean
  created_at?: string
  revoked_at?: string | null
}

export type DeveloperApiKeyListResponse = {
  keys: DeveloperApiKey[]
}

export type CreatedDeveloperApiKey = DeveloperApiKey & {
  api_key: string
}

type RequestOptions = {
  method?: string
  body?: BodyInit
  headers?: HeadersInit
  timeoutMs?: number
  requireAuth?: boolean
}

export class VoiceApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'VoiceApiError'
    this.status = status
  }
}

const DEFAULT_TIMEOUT_MS = 600_000

function getConfig() {
  const baseUrl = process.env.VOICE_API_BASE_URL?.trim()
  const apiKey = process.env.VOICE_API_KEY
  const timeoutMs = Number(process.env.VOICE_API_TIMEOUT_MS || DEFAULT_TIMEOUT_MS)

  if (!baseUrl) {
    throw new VoiceApiError(500, 'VOICE_API_BASE_URL is not configured.')
  }
  if (!apiKey) {
    throw new VoiceApiError(500, 'VOICE_API_KEY is not configured.')
  }

  let normalizedBaseUrl: string
  try {
    normalizedBaseUrl = new URL(baseUrl).toString().replace(/\/$/, '')
  } catch {
    throw new VoiceApiError(500, 'VOICE_API_BASE_URL must be a valid URL.')
  }

  return {
    baseUrl: normalizedBaseUrl,
    apiKey,
    timeoutMs: Number.isFinite(timeoutMs) && timeoutMs > 0 ? timeoutMs : DEFAULT_TIMEOUT_MS,
  }
}

async function responseDetail(response: Response) {
  const contentType = response.headers.get('content-type') || ''

  if (contentType.includes('application/json')) {
    try {
      const body = await response.json()
      if (typeof body?.detail === 'string') return body.detail
      if (body?.detail) return JSON.stringify(body.detail)
    } catch {
      return `RunPod request failed (${response.status}).`
    }
  }

  try {
    const text = await response.text()
    if (text.trim()) return text.slice(0, 500)
  } catch {
    // Fall through to the generic status message.
  }

  return `RunPod request failed (${response.status}).`
}

async function runPodFetch(path: string, options: RequestOptions = {}) {
  const config = getConfig()
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), options.timeoutMs ?? config.timeoutMs)
  const headers = new Headers(options.headers)

  if (options.requireAuth !== false) {
    headers.set('Authorization', `Bearer ${config.apiKey}`)
  }

  try {
    const response = await fetch(`${config.baseUrl}${path}`, {
      method: options.method || 'GET',
      body: options.body,
      headers,
      signal: controller.signal,
      cache: 'no-store',
    })

    if (!response.ok) {
      throw new VoiceApiError(response.status, await responseDetail(response))
    }

    return response
  } catch (error) {
    if (error instanceof VoiceApiError) throw error
    if (error instanceof Error && error.name === 'AbortError') {
      throw new VoiceApiError(504, 'RunPod voice API request timed out.')
    }
    throw new VoiceApiError(502, 'RunPod voice API is unavailable.')
  } finally {
    clearTimeout(timeout)
  }
}

export async function checkVoiceApiHealth() {
  const response = await runPodFetch('/health', { requireAuth: false, timeoutMs: 10_000 })
  return response.json() as Promise<VoiceHealthResponse>
}

export async function listVoices() {
  const response = await runPodFetch('/api/voices', { timeoutMs: 30_000 })
  const data = (await response.json()) as VoiceListResponse
  return {
    voices: Array.isArray(data.voices) ? data.voices : [],
  }
}

export async function uploadVoice(file: File, displayName?: string) {
  const form = new FormData()
  const cleanDisplayName = displayName?.trim()
  if (cleanDisplayName) {
    form.append('display_name', cleanDisplayName)
  }
  form.append('file', file, file.name || 'reference.wav')

  const response = await runPodFetch('/api/voices', {
    method: 'POST',
    body: form,
  })

  return response.json() as Promise<UploadedVoice>
}

export async function previewVoice(voiceId: string) {
  const response = await runPodFetch(`/api/voices/${encodeURIComponent(voiceId)}/preview`, {
    timeoutMs: 30_000,
  })

  return {
    audio: await response.arrayBuffer(),
    contentType: response.headers.get('content-type') || 'audio/wav',
    contentDisposition: response.headers.get('content-disposition') || '',
  }
}

export async function deleteVoice(voiceId: string) {
  const response = await runPodFetch(`/api/voices/${encodeURIComponent(voiceId)}`, {
    method: 'DELETE',
    timeoutMs: 30_000,
  })

  return response.json() as Promise<{ voice_id: string; deleted: boolean }>
}

export async function listDeveloperApiKeys() {
  const response = await runPodFetch('/api/developer-keys', { timeoutMs: 30_000 })
  const data = (await response.json()) as DeveloperApiKeyListResponse
  return {
    keys: Array.isArray(data.keys) ? data.keys : [],
  }
}

export async function createDeveloperApiKey(developerName: string) {
  const response = await runPodFetch('/api/developer-keys', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ developer_name: developerName }),
    timeoutMs: 30_000,
  })

  return response.json() as Promise<CreatedDeveloperApiKey>
}

export async function revokeDeveloperApiKey(keyId: string) {
  const response = await runPodFetch(`/api/developer-keys/${encodeURIComponent(keyId)}/revoke`, {
    method: 'POST',
    timeoutMs: 30_000,
  })

  return response.json() as Promise<DeveloperApiKey>
}

export async function generateTts(voiceId: string, text: string) {
  const response = await runPodFetch('/api/tts', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ voice_id: voiceId, text }),
  })

  return {
    audio: await response.arrayBuffer(),
    contentType: response.headers.get('content-type') || 'audio/wav',
    contentDisposition: response.headers.get('content-disposition') || 'attachment; filename="speech.wav"',
    timings: response.headers.get('x-tts-timings') || '',
    totalMs: response.headers.get('x-tts-total-ms') || '',
    cacheHit: response.headers.get('x-tts-cache-hit') || '',
  }
}
