import { NextResponse } from 'next/server'

import { createDeveloperApiKey, listDeveloperApiKeys } from '@/lib/voice-api'
import { apiErrorResponse } from '../voice-response'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

const MAX_DEVELOPER_NAME_LENGTH = 120

export async function GET() {
  try {
    return NextResponse.json(await listDeveloperApiKeys())
  } catch (error) {
    return apiErrorResponse(error)
  }
}

export async function POST(request: Request) {
  try {
    const body = await request.json().catch(() => null)
    const developerName = typeof body?.developer_name === 'string' ? body.developer_name.trim() : ''

    if (!developerName) {
      return NextResponse.json({ detail: 'Developer name is required.' }, { status: 400 })
    }
    if (developerName.length > MAX_DEVELOPER_NAME_LENGTH) {
      return NextResponse.json({ detail: `Developer name exceeds ${MAX_DEVELOPER_NAME_LENGTH} characters.` }, { status: 422 })
    }

    return NextResponse.json(await createDeveloperApiKey(developerName))
  } catch (error) {
    return apiErrorResponse(error)
  }
}
