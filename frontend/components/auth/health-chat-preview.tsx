import Image from "next/image"
import { ShieldCheck, Users } from "lucide-react"

export interface ChatMessage {
  id: string
  sender: "user" | "assistant" | "system"
  name: string
  avatar?: string
  message: string
  timestamp: string
  isHighlight?: boolean
}

/**
 * A WhatsApp family group mid-conversation, not a private DM to the bot —
 * this is what JAWARA actually intervenes in: a health rumor about to get
 * forwarded, until the bot fact-checks it in front of everyone.
 */
const MESSAGES: ChatMessage[] = [
  {
    id: "1",
    sender: "user",
    name: "Akmal",
    message: "Ada yang lihat broadcast katanya rebusan daun pepaya bisa sembuhin DBD dalam sehari? 😳",
    timestamp: "09:41",
  },
  {
    id: "2",
    sender: "user",
    name: "Lukman",
    message: "Serius? Adikku baru kena DBD kemarin, langsung aku forward ah biar cepat sembuh",
    timestamp: "09:41",
  },
  {
    id: "3",
    sender: "user",
    name: "Mak Lemak",
    message: "Tunggu dulu Pak, itu udah dicek belum kebenarannya? Takutnya cuma hoax beredar lagi. Tanya dulu ama @Jawara Bot",
    timestamp: "09:42",
  },
  {
    id: "4",
    sender: "assistant",
    name: "Jawara Bot",
    message:
      "Halo semua 👋 Klaim itu belum terbukti medis , daun pepaya bisa jadi pendamping, tapi bukan pengganti penanganan DBD. Kalau demam tinggi 2 hari lebih, segera ke faskes terdekat.",
    timestamp: "09:42",
    isHighlight: true,
  },
  {
    id: "5",
    sender: "user",
    name: "Akmal",
    message: "Wah untung dicek dulu sebelum kesebar 🙏 makasih Jawara Bot",
    timestamp: "09:43",
  },
]

const PARTICIPANT_COLOR: Record<string, string> = {
  "Akmal": "bg-chart-2",
  "Lukman": "bg-chart-3",
  "Mak Lemak": "bg-chart-4",
}

function initials(name: string): string {
  return name
    .split(/\s+/)
    .map((part) => part[0])
    .join("")
    .toUpperCase()
    .slice(0, 2)
}

/**
 * Static screenshot-style render of a busy family group where a health rumor
 * is about to spread — until JAWARA steps in. No animation: the point is
 * social proof you can read at a glance, not a performance to sit through.
 */
export function HealthChatPreview() {
  return (
    <div className="flex w-full max-w-3xl flex-col gap-4">
      <div className="overflow-hidden rounded-3xl border border-white/10 bg-card/95 shadow-2xl shadow-black/40 backdrop-blur">
        <ChatHeader />
        <div className="flex flex-col gap-4 px-6 py-6">
          {MESSAGES.map((message, index) => (
            <ChatBubble key={message.id} message={message} index={index} />
          ))}
        </div>
      </div>
    </div>
  )
}

function ChatHeader() {
  return (
    <div className="flex items-center gap-3 border-b border-border bg-secondary/60 px-5 py-4">
      <div className="flex size-11 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground">
        <Users className="size-5" aria-hidden />
      </div>
      <div className="min-w-0 flex-1">
        <p className="truncate text-base font-semibold text-foreground">Komunitas Orang Sehat Sehatan</p>
        <p className="truncate text-xs text-muted-foreground">
          {MESSAGES.map((message) => message.name).join(", ")}
        </p>
      </div>
    </div>
  )
}

function ChatAvatar({ message }: { message: ChatMessage }) {
  if (message.sender === "assistant") {
    return (
      <div className="size-9 shrink-0 overflow-hidden rounded-full bg-primary">
        <Image src="/icon.png" alt="" width={36} height={36} className="size-full object-cover" />
      </div>
    )
  }
  return (
    <div
      className={`flex size-9 shrink-0 items-center justify-center rounded-full text-xs font-semibold text-white ${PARTICIPANT_COLOR[message.name] ?? "bg-muted-foreground"}`}
    >
      {initials(message.name)}
    </div>
  )
}

/** Per-bubble stagger, ~150ms apart, so the thread reads as landing message
 * by message rather than popping in as one block. `motion-safe:` keeps this
 * off entirely for `prefers-reduced-motion` users — no JS media-query needed. */
function ChatBubble({ message, index }: { message: ChatMessage; index: number }) {
  const isBot = message.sender === "assistant"

  return (
    <div
      className="flex items-start gap-3 motion-safe:animate-in motion-safe:fade-in motion-safe:slide-in-from-bottom-3 motion-safe:duration-500 motion-safe:ease-out motion-safe:fill-mode-backwards"
      style={{ animationDelay: `${index * 150}ms` }}
    >
      <ChatAvatar message={message} />
      <div className="flex min-w-0 max-w-[85%] flex-col gap-1">
        <div className="flex items-center gap-2 px-1">
          <span className={`text-sm font-semibold ${isBot ? "text-primary" : "text-foreground"}`}>
            {message.name}
          </span>
          {isBot ? (
            <span className="inline-flex items-center gap-1 rounded-full bg-primary/15 px-1.5 py-0.5 text-[0.625rem] font-medium text-primary">
              <ShieldCheck className="size-2.5" aria-hidden />
              Bot
            </span>
          ) : null}
        </div>

        <div
          className={
            isBot
              ? "rounded-2xl rounded-tl-sm border-2 border-primary/50 bg-primary/10 px-4 py-3 text-sm text-foreground"
              : "rounded-2xl rounded-tl-sm border border-border bg-secondary px-4 py-3 text-sm text-foreground"
          }
        >
          {message.message}
        </div>
        <span className="px-1 text-[0.6875rem] text-muted-foreground">{message.timestamp}</span>
      </div>
    </div>
  )
}
