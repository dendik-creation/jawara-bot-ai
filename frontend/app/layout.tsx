import type { Metadata } from "next"
import { Geist_Mono, IBM_Plex_Sans } from "next/font/google"

import "./globals.css"
import { AuthProvider } from "@/components/auth/auth-provider"
import { ThemeProvider } from "@/components/theme-provider"
import { cn } from "@/lib/utils"

const ibmPlexSans = IBM_Plex_Sans({ subsets: ["latin"], variable: "--font-sans" })

const fontMono = Geist_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
})

export const metadata: Metadata = {
  title: "JAWARA Control Panel",
  description: "Control & Monitoring Center untuk platform keamanan WhatsApp JAWARA",
}

/**
 * The shell used to live here. It moved to `app/(panel)/layout.tsx` when login
 * arrived: /login must render without a sidebar, and a signed-out visitor must
 * not see the panel chrome at all.
 */
export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html
      lang="id"
      suppressHydrationWarning
      className={cn("antialiased", fontMono.variable, "font-sans", ibmPlexSans.variable)}
    >
      <body>
        <ThemeProvider>
          <AuthProvider>{children}</AuthProvider>
        </ThemeProvider>
      </body>
    </html>
  )
}
