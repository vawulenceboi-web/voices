import { NextResponse } from 'next/server'

import { revokeDeveloperApiKey } from '@/lib/voice-api'
import { apiErrorResponse } from '../../../voice-response'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

const KEY_ID_PATTERN = /^[A-Fa-f0-9-]{1,64}$/

type RouteContext = {
  params: Promise<{ keyId: string }>
}

export async function POST(_request: Request, context: RouteContext) {
  try {
    const { keyId } = await context.params
    const cleanKeyId = keyId.trim()

    if (!KEY_ID_PATTERN.test(cleanKeyId)) {
      return NextResponse.json({ detail: 'Invalid developer API key ID.' }, { status: 400 })
    }

    return NextResponse.json(await revokeDeveloperApiKey(cleanKeyId))
  } catch (error) {
    return apiErrorResponse(error)
  }
}
