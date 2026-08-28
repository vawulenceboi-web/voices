import { NextResponse } from 'next/server'

import { listVoices, uploadVoice } from '@/lib/voice-api'
import { apiErrorResponse } from '../voice-response'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

export async function GET() {
  try {
    return NextResponse.json(await listVoices())
  } catch (error) {
    return apiErrorResponse(error)
  }
}

export async function POST(request: Request) {
  try {
    const form = await request.formData()
    const file = form.get('file')

    if (!(file instanceof File) || file.size === 0) {
      return NextResponse.json({ detail: 'Upload a non-empty voice sample.' }, { status: 400 })
    }

    const displayName = form.get('display_name') || form.get('name')
    const cleanDisplayName = typeof displayName === 'string' ? displayName.trim() : ''

    return NextResponse.json(await uploadVoice(file, cleanDisplayName))
  } catch (error) {
    return apiErrorResponse(error)
  }
}
