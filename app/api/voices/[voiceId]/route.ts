import { NextResponse } from 'next/server'

import { deleteVoice } from '@/lib/voice-api'
import { apiErrorResponse } from '../../voice-response'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

const VOICE_ID_PATTERN = /^[A-Za-z0-9_-]{1,100}$/

type RouteContext = {
  params: Promise<{ voiceId: string }>
}

export async function DELETE(_request: Request, context: RouteContext) {
  try {
    const { voiceId } = await context.params
    const cleanVoiceId = voiceId.trim()

    if (!VOICE_ID_PATTERN.test(cleanVoiceId)) {
      return NextResponse.json({ detail: 'Invalid voice ID.' }, { status: 400 })
    }

    return NextResponse.json(await deleteVoice(cleanVoiceId))
  } catch (error) {
    return apiErrorResponse(error)
  }
}
