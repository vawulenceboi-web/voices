import { Analytics } from '@vercel/analytics/next'
import type { Metadata, Viewport } from 'next'
import { DM_Mono, Instrument_Serif } from 'next/font/google'
import './globals.css'

const mono = DM_Mono({ subsets: ['latin'], variable: '--font-mono', weight: ['400', '500'] })
const serif = Instrument_Serif({ subsets: ['latin'], variable: '--font-serif', weight: '400' })

export const metadata: Metadata = { title: 'Chatterbox Voice Lab', description: 'A standalone local voice server control panel.', generator: 'v0.app' }
export const viewport: Viewport = { width: 'device-width', initialScale: 1, maximumScale: 1, colorScheme: 'light', themeColor: '#f4f1ea' }
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) { return <html lang="en" className="bg-background"><body className={`${mono.variable} ${serif.variable} antialiased`}>{children}{process.env.NODE_ENV === 'production' && <Analytics />}</body></html> }
