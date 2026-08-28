import { previewVoice } from '@/lib/voice-api'
import { apiErrorResponse } from '../../../voice-response'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

const VOICE_ID_PATTERN = /^[A-Za-z0-9_-]{1,100}$/

type RouteContext = {
  params: Promise<{ voiceId: string }>
}

export async function GET(_request: Request, context: RouteContext) {
  try {
    const { voiceId } = await context.params
    const cleanVoiceId = voiceId.trim()

    if (!VOICE_ID_PATTERN.test(cleanVoiceId)) {
      return Response.json({ detail: 'Invalid voice ID.' }, { status: 400 })
    }

    const result = await previewVoice(cleanVoiceId)
    return new Response(result.audio, {
      headers: {
        'Content-Type': result.contentType,
        'Content-Disposition': result.contentDisposition || `inline; filename="${cleanVoiceId}.wav"`,
        'Cache-Control': 'no-store',
      },
    })
  } catch (error) {
    return apiErrorResponse(error)
  }
}
