import { NextResponse } from 'next/server'

import { checkVoiceApiHealth, VoiceApiError } from '@/lib/voice-api'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

export async function GET() {
  try {
    const upstream = await checkVoiceApiHealth()
    return NextResponse.json({
      status: 'ok',
      local: { status: 'ready' },
      runpod: {
        reachable: true,
        status: upstream.status,
        engine: upstream.engine || null,
      },
    })
  } catch (error) {
    return NextResponse.json({
      status: 'degraded',
      local: { status: 'ready' },
      runpod: {
        reachable: false,
        status: error instanceof VoiceApiError ? error.status : 500,
        detail: error instanceof Error ? error.message : 'RunPod voice API is unavailable.',
      },
    })
  }
}
