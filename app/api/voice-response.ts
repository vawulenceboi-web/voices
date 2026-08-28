import { NextResponse } from 'next/server'

import { VoiceApiError } from '@/lib/voice-api'

export function apiErrorResponse(error: unknown) {
  if (error instanceof VoiceApiError) {
    return NextResponse.json({ detail: error.message }, { status: error.status })
  }

  return NextResponse.json({ detail: 'Unexpected local voice API error.' }, { status: 500 })
}
