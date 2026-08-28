import { generateTts } from '@/lib/voice-api'
import { apiErrorResponse } from '../voice-response'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'
export const maxDuration = 300

const VOICE_ID_PATTERN = /^[A-Za-z0-9_-]{1,100}$/
const MAX_TEXT_LENGTH = 3000

export async function POST(request: Request) {
  try {
    const body = await request.json().catch(() => null)
    const voiceId = typeof body?.voice_id === 'string' ? body.voice_id.trim() : ''
    const text = typeof body?.text === 'string' ? body.text.trim() : ''

    if (!voiceId) {
      return Response.json({ detail: 'Select a voice first.' }, { status: 400 })
    }
    if (!VOICE_ID_PATTERN.test(voiceId)) {
      return Response.json({ detail: 'Invalid voice ID.' }, { status: 400 })
    }
    if (!text) {
      return Response.json({ detail: 'Enter text before generating speech.' }, { status: 400 })
    }
    if (text.length > MAX_TEXT_LENGTH) {
      return Response.json({ detail: `Text exceeds ${MAX_TEXT_LENGTH} characters.` }, { status: 422 })
    }

    const result = await generateTts(voiceId, text)
    return new Response(result.audio, {
      headers: {
        'Content-Type': result.contentType,
        'Content-Disposition': result.contentDisposition,
        'Cache-Control': 'no-store',
        'X-TTS-Timings': result.timings,
        'X-TTS-Total-Ms': result.totalMs,
        'X-TTS-Cache-Hit': result.cacheHit,
      },
    })
  } catch (error) {
    return apiErrorResponse(error)
  }
}
