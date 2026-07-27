import {
  AlarmClock,
  AlertCircle,
  ArrowRight,
  ArrowUp,
  Check,
  Gauge,
  History,
  MessagesSquare,
  Plus,
  RotateCcw,
  ScanText,
  Sparkles,
  Square,
  Trash2,
} from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { Logo } from '../components/Brand'
import { ProSeDisclaimer } from '../components/Disclaimer'
import { EmptyState, ErrorBlock, LoadingBlock, Spinner } from '../components/ui'
import { humanize } from '../lib/format'
import { hueInk } from '../lib/hues'
import { ApiError, raiderApiExtras } from '../lib/api'
import {
  createConversation,
  deleteConversation,
  getActiveConversationId,
  getConversation,
  listConversations,
  setActiveConversationId,
  upsertMessages,
  type RaiderConversation,
} from '../lib/raiderChatStore'
import { raiderStatus, streamRaiderChat, type RaiderChatMessage } from '../lib/raiderApi'
import type { InterviewSeed } from '../types'

/* Rating Raider — the flagship conversational surface. A stressed, non-technical
 * veteran talks to Rating Raider (our CWO claims agent) here: they type plainly, watch it
 * work its engines live as "working" chips, and read the answer as it types in.
 * Everything is grounded server-side in their record + 38 CFR; this page is the
 * warm, trustworthy window onto that. Home section (violet), legal-lane voice. */

// Keep in step with backend MAX_HISTORY_MESSAGES / bound_history char budget.
const HISTORY_LIMIT = 24
const HISTORY_CHAR_BUDGET = 28_000

/** Drop oldest turns until the remaining conversation fits the char budget. */
function boundClientHistory(msgs: RaiderChatMessage[]): RaiderChatMessage[] {
  const capped = msgs.slice(-HISTORY_LIMIT).map((m) => ({
    role: m.role,
    content: m.content.length > 4000 ? `${m.content.slice(0, 3999)}…` : m.content,
  }))
  let total = 0
  const kept: RaiderChatMessage[] = []
  for (let i = capped.length - 1; i >= 0; i -= 1) {
    const n = capped[i].content.length
    if (kept.length && total + n > HISTORY_CHAR_BUDGET) break
    kept.unshift(capped[i])
    total += n
  }
  return kept.length ? kept : capped.slice(-1)
}

// ── Tool → human progress label ──────────────────────────────────────────────
// Present-tense while running ("working" chip), past-tense once done (quiet trace
// of what it consulted — transparency the veteran can trust).
const TOOL_META: Record<string, { running: string; done: string }> = {
  get_my_situation: { running: 'Reviewing your situation…', done: 'Reviewed your record' },
  run_deep_dive: { running: 'Running your deep dive…', done: 'Ran your deep dive' },
  find_secondary_conditions: { running: 'Looking for secondary conditions…', done: 'Checked secondaries' },
  screen_tdiu: { running: 'Screening TDIU…', done: 'Screened TDIU' },
  check_readiness: { running: 'Checking your evidence…', done: 'Checked your evidence' },
  search_va_rulebook: { running: 'Checking the VA rulebook…', done: 'Checked 38 CFR' },
  list_deadlines: { running: 'Checking your VA deadlines…', done: 'Checked your deadlines' },
  check_concurrent_pay: { running: 'Checking concurrent pay…', done: 'Checked concurrent pay' },
  preview_form: { running: 'Pulling up the form…', done: 'Reviewed the form' },
  list_workflows: { running: 'Finding the right workflow…', done: 'Found the right workflow' },
  review_my_evidence: { running: 'Reviewing your evidence…', done: 'Reviewed your evidence' },
  find_supporting_research: { running: 'Finding supporting research…', done: 'Found supporting research' },
  take_me_to: { running: 'Taking you there…', done: 'Opened the page for you' },
  prepare_cp_exam: { running: 'Preparing C&P exam guidance…', done: 'Prepared C&P exam guidance' },
  get_case_picture: { running: 'Reading your whole case picture…', done: 'Read your case picture' },
  search_my_records: { running: 'Searching your records…', done: 'Searched your records' },
}

function toolLabel(name: string, done: boolean): string {
  const meta = TOOL_META[name]
  if (meta) return done ? meta.done : meta.running
  return done ? humanize(name) : `${humanize(name)}…`
}

// Starter prompts — grounded in the research (under-rating, secondaries,
// deadlines, decision-letter decode). Short chip label, fuller sent prompt.
const STARTERS: { icon: typeof Gauge; label: string; prompt: string }[] = [
  { icon: Gauge, label: 'Am I being under-rated?', prompt: 'Am I being under-rated? Compare my current ratings to what the VA criteria require.' },
  { icon: Sparkles, label: 'What secondaries am I missing?', prompt: 'What secondary conditions might I be missing, based on my service-connected conditions?' },
  { icon: AlarmClock, label: 'What deadlines am I facing?', prompt: 'What time-sensitive VA deadlines am I facing right now?' },
  { icon: ScanText, label: 'Understand my decision letter', prompt: 'Help me understand my VA decision letter and what my options are.' },
  {
    icon: Sparkles,
    label: 'Prep me for a C&P exam',
    prompt:
      'Help me prepare for a C&P exam like a VA examiner would assess me — what DBQ applies, what criteria they look at, and how to describe symptoms honestly (worst day, frequency, function). Not medical advice.',
  },
  {
    icon: Check,
    label: 'Am I ready to file?',
    prompt:
      'Based on my record, am I ready to prepare a claim for filing? Walk me through evidence readiness, what is still missing, and the concrete next step — without predicting what VA will decide.',
  },
  {
    icon: MessagesSquare,
    label: 'What should I do next?',
    prompt:
      'What is the single most important next step on my claim right now, and why? Point me to the right workflow in this app.',
  },
]

// ── Markdown-ish render (no dependency — same escape→build-HTML approach as
// Filing.tsx's renderContent, extended for the conversational richness the agent
// emits: **bold**, `code`, bullet + numbered lists, and paragraphs). Renders into
// a `.vo-prose` container. XSS-safe: text is escaped first; only known tags are
// introduced afterward. ─────────────────────────────────────────────────────────
const BULLET = /^\s*[-*]\s+(.*)$/
const NUMBERED = /^\s*\d+[.)]\s+(.*)$/

function escapeHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

function inlineFmt(s: string): string {
  return s
    .replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>')
    .replace(/`([^`\n]+)`/g, '<code>$1</code>')
}

function renderAgentMarkdown(text: string): string {
  return escapeHtml(text)
    .split(/\n{2,}/)
    .map((block) => block.replace(/\s+$/, ''))
    .filter((block) => block.trim() !== '')
    .map((block) => {
      const lines = block.split('\n')
      const bulletLines = lines.filter((l) => BULLET.test(l))
      const numberedLines = lines.filter((l) => NUMBERED.test(l))
      if (bulletLines.length === lines.length && bulletLines.length > 0) {
        const items = bulletLines.map((l) => `<li>${inlineFmt(l.replace(BULLET, '$1'))}</li>`).join('')
        return `<ul>${items}</ul>`
      }
      if (numberedLines.length === lines.length && numberedLines.length > 0) {
        const items = numberedLines.map((l) => `<li>${inlineFmt(l.replace(NUMBERED, '$1'))}</li>`).join('')
        return `<ol>${items}</ol>`
      }
      return `<p>${inlineFmt(block).replace(/\n/g, '<br/>')}</p>`
    })
    .join('')
}

// Blinking type-caret appended to the streaming answer. Utility classes live here
// as a literal so Tailwind emits them; bg-current inherits the prose text color.
const CARET =
  '<span aria-hidden="true" class="ml-0.5 inline-block h-[1.05em] w-[2px] -translate-y-[1px] animate-pulsedot rounded-full bg-current align-middle"></span>'

// ── Model ────────────────────────────────────────────────────────────────────
interface ToolActivity {
  id: number
  name: string
  done: boolean
}
interface ChatMessage {
  id: number
  role: 'user' | 'assistant'
  content: string
  streaming?: boolean
  error?: string
  activity?: ToolActivity[]
}

function friendlyError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 503) return "Rating Raider isn't available right now. Please try again in a moment."
    if (err.status === 401) return 'Your session expired — please sign in again.'
    if (err.status === 0) return "I couldn't reach the line just now. Check your connection and try again."
  }
  return "Rating Raider's reply was interrupted. Check your connection, then try again."
}

export function Raider() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const [status, setStatus] = useState<{ available: boolean } | null>(null)
  const [statusLoading, setStatusLoading] = useState(true)
  const [statusError, setStatusError] = useState<string | null>(null)
  const [statusAttempt, setStatusAttempt] = useState(0)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [interviewSeed, setInterviewSeed] = useState<InterviewSeed | null>(null)
  const [interviewLoading, setInterviewLoading] = useState(false)
  const [conversationId, setConversationId] = useState<string | null>(null)
  const [conversations, setConversations] = useState<RaiderConversation[]>(() => listConversations())
  const [historyOpen, setHistoryOpen] = useState(false)
  const postAnalysisMode = searchParams.get('mode') === 'post_analysis'
  const interviewStartedRef = useRef(false)
  const hydratedRef = useRef(false)

  const idRef = useRef(0)
  const nid = useCallback(() => ++idRef.current, [])
  const abortRef = useRef<AbortController | null>(null)
  const sendingRef = useRef(false)
  const navigationTimerRef = useRef<number | null>(null)
  const stickRef = useRef(true)
  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const messagesRef = useRef<ChatMessage[]>([])
  const conversationIdRef = useRef<string | null>(null)

  useEffect(() => {
    messagesRef.current = messages
  }, [messages])

  useEffect(() => {
    conversationIdRef.current = conversationId
  }, [conversationId])

  // Hydrate active (or new) conversation once on mount / when mode changes.
  useEffect(() => {
    if (hydratedRef.current && !postAnalysisMode) return
    const qId = searchParams.get('c')
    let conv: RaiderConversation | null = null
    if (qId) conv = getConversation(qId)
    if (!conv && !postAnalysisMode) {
      const active = getActiveConversationId()
      if (active) conv = getConversation(active)
    }
    if (postAnalysisMode) {
      // Fresh interview thread so we don't mix with an old general chat.
      conv = createConversation('post_analysis')
      interviewStartedRef.current = false
    } else if (!conv) {
      conv = createConversation('general')
    }
    setConversationId(conv.id)
    setActiveConversationId(conv.id)
    const restored: ChatMessage[] = (conv.messages || []).map((m) => ({
      id: m.id,
      role: m.role,
      content: m.content,
      ...(m.error ? { error: m.error } : {}),
    }))
    if (restored.length) {
      const maxId = restored.reduce((n, m) => Math.max(n, m.id || 0), 0)
      idRef.current = Math.max(idRef.current, maxId)
      setMessages(restored)
      if (restored.some((m) => m.role === 'user')) interviewStartedRef.current = true
    } else {
      setMessages([])
    }
    setConversations(listConversations())
    hydratedRef.current = true
  }, [postAnalysisMode, searchParams])

  // Persist after every message change (skip pure empty new chat until first content).
  useEffect(() => {
    const cid = conversationIdRef.current
    if (!cid || !hydratedRef.current) return
    const persistable = messages
      .filter((m) => !m.streaming)
      .map((m) => ({
        id: m.id,
        role: m.role as 'user' | 'assistant',
        content: m.content,
        ...(m.error ? { error: m.error } : {}),
      }))
    if (persistable.length === 0 && messages.length === 0) return
    // Don't save while mid-stream incomplete empty assistant
    if (messages.some((m) => m.streaming)) {
      // still save user turns + finished assistants so navigate mid-stream keeps history
      const partial = messages
        .filter((m) => m.role === 'user' || (m.role === 'assistant' && !m.streaming && m.content))
        .map((m) => ({
          id: m.id,
          role: m.role as 'user' | 'assistant',
          content: m.content,
          ...(m.error ? { error: m.error } : {}),
        }))
      if (partial.length) {
        upsertMessages(cid, partial, {
          kind: postAnalysisMode ? 'post_analysis' : 'general',
        })
        setConversations(listConversations())
      }
      return
    }
    upsertMessages(cid, persistable, {
      kind: postAnalysisMode ? 'post_analysis' : undefined,
    })
    setConversations(listConversations())
  }, [messages, postAnalysisMode])

  const startNewChat = useCallback(() => {
    abortRef.current?.abort()
    interviewStartedRef.current = false
    setInterviewSeed(null)
    const conv = createConversation('general')
    setConversationId(conv.id)
    setMessages([])
    setInput('')
    setConversations(listConversations())
    setHistoryOpen(false)
    if (searchParams.get('mode') || searchParams.get('c')) {
      const next = new URLSearchParams(searchParams)
      next.delete('mode')
      next.delete('c')
      setSearchParams(next, { replace: true })
    }
  }, [searchParams, setSearchParams])

  const openConversation = useCallback(
    (id: string) => {
      abortRef.current?.abort()
      const conv = getConversation(id)
      if (!conv) return
      setConversationId(conv.id)
      setActiveConversationId(conv.id)
      interviewStartedRef.current = conv.messages.some((m) => m.role === 'user')
      setInterviewSeed(null)
      const restored: ChatMessage[] = conv.messages.map((m) => ({
        id: m.id,
        role: m.role,
        content: m.content,
        ...(m.error ? { error: m.error } : {}),
      }))
      const maxId = restored.reduce((n, m) => Math.max(n, m.id || 0), 0)
      idRef.current = Math.max(idRef.current, maxId)
      setMessages(restored)
      setHistoryOpen(false)
      const next = new URLSearchParams(searchParams)
      next.delete('mode')
      next.set('c', id)
      setSearchParams(next, { replace: true })
    },
    [searchParams, setSearchParams],
  )

  const removeConversation = useCallback(
    (id: string) => {
      deleteConversation(id)
      const remaining = listConversations()
      setConversations(remaining)
      if (conversationIdRef.current === id) {
        if (remaining[0]) openConversation(remaining[0].id)
        else startNewChat()
      }
    },
    [openConversation, startNewChat],
  )

  // Status probe — a failed check gets its own retryable state so a connection
  // problem is never mistaken for an unavailable account feature.
  useEffect(() => {
    let active = true
    const ctrl = new AbortController()
    setStatusLoading(true)
    setStatusError(null)
    raiderStatus(ctrl.signal)
      .then((s) => {
        if (active) setStatus(s)
      })
      .catch((err) => {
        if (!active || ctrl.signal.aborted) return
        setStatus(null)
        setStatusError(
          err instanceof ApiError && err.status === 401
            ? 'Your session expired. Sign in again, then retry the connection check.'
            : "We couldn't check whether Rating Raider is online. Check your connection, then try again.",
        )
      })
      .finally(() => active && setStatusLoading(false))
    return () => {
      active = false
      ctrl.abort()
    }
  }, [statusAttempt])

  // Post-analysis coach interview: load seed, show opening + Start gap interview.
  useEffect(() => {
    if (!postAnalysisMode || statusLoading || statusError) return
    if (status && !status.available) return
    let active = true
    setInterviewLoading(true)
    raiderApiExtras
      .interviewSeed('post_analysis')
      .then((seed) => {
        if (!active) return
        setInterviewSeed(seed)
        const opening = (seed.opening || '').trim()
        if (opening && messagesRef.current.length === 0) {
          setMessages([{ id: nid(), role: 'assistant', content: opening }])
        }
      })
      .catch(() => {
        if (!active) return
        const fallback: InterviewSeed = {
          mode: 'post_analysis',
          opening:
            "I can walk you through the real gaps in your file after your case review — work history, nexus, CFS vs fibro, and goals — then order next steps. Educational only; I don't file for you.",
          starter_user_message:
            'I just finished a full case review. Please interview me about the real gaps in my file and then give me an ordered next-step plan. Ask one question at a time.',
          questions: [],
        }
        setInterviewSeed(fallback)
        if (messagesRef.current.length === 0 && fallback.opening) {
          setMessages([{ id: nid(), role: 'assistant', content: fallback.opening }])
        }
      })
      .finally(() => {
        if (active) setInterviewLoading(false)
      })
    return () => {
      active = false
    }
  }, [postAnalysisMode, statusLoading, statusError, status, nid])

  // Auto-scroll only while the veteran is already near the bottom, so reading
  // back through history isn't yanked away when new tokens land. The scroll
  // parent is the Shell's <main id="main-content">.
  useEffect(() => {
    const el = document.getElementById('main-content')
    if (!el) return
    const onScroll = () => {
      stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 140
    }
    el.addEventListener('scroll', onScroll, { passive: true })
    return () => el.removeEventListener('scroll', onScroll)
  }, [])

  // Abort an in-flight turn if the veteran navigates away.
  useEffect(
    () => () => {
      abortRef.current?.abort()
      if (navigationTimerRef.current !== null) window.clearTimeout(navigationTimerRef.current)
    },
    [],
  )

  const scrollToBottom = useCallback((behavior: ScrollBehavior = 'auto') => {
    const reduceMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    bottomRef.current?.scrollIntoView({ block: 'end', behavior: reduceMotion ? 'auto' : behavior })
  }, [])

  const patch = useCallback((id: number, fn: (m: ChatMessage) => ChatMessage) => {
    setMessages((prev) => prev.map((m) => (m.id === id ? fn(m) : m)))
  }, [])

  const startTurn = useCallback(
    async (history: RaiderChatMessage[], assistantId: number) => {
      const controller = new AbortController()
      abortRef.current = controller
      try {
        for await (const ev of streamRaiderChat(history, controller.signal)) {
          if (ev.type === 'tool') {
            patch(assistantId, (m) => {
              const activity = m.activity ? [...m.activity] : []
              if (ev.status === 'start') {
                activity.push({ id: nid(), name: ev.name, done: false })
              } else {
                for (let i = activity.length - 1; i >= 0; i--) {
                  if (activity[i].name === ev.name && !activity[i].done) {
                    activity[i] = { ...activity[i], done: true }
                    break
                  }
                }
              }
              return { ...m, activity }
            })
          } else if (ev.type === 'token') {
            patch(assistantId, (m) => ({ ...m, content: m.content + ev.text }))
          } else if (ev.type === 'replace') {
            patch(assistantId, (m) => ({ ...m, content: ev.text }))
          } else if (ev.type === 'ui') {
            // Rating Raider is driving the screen — navigate the veteran where it's taking them.
            if (ev.action.type === 'navigate' && ev.action.route) {
              patch(assistantId, (m) => ({
                ...m,
                activity: [...(m.activity ?? []), { id: nid(), name: 'take_me_to', done: true }],
              }))
              if (navigationTimerRef.current !== null) window.clearTimeout(navigationTimerRef.current)
              navigationTimerRef.current = window.setTimeout(() => {
                navigationTimerRef.current = null
                if (!controller.signal.aborted) navigate(ev.action.route!)
              }, 600)
            }
          } else if (ev.type === 'done') {
            patch(assistantId, (m) => ({ ...m, streaming: false }))
          }
          if (stickRef.current) scrollToBottom('auto')
        }
        patch(assistantId, (m) => ({ ...m, streaming: false }))
      } catch (err) {
        patch(assistantId, (m) => ({
          ...m,
          streaming: false,
          error: controller.signal.aborted
            ? 'Response stopped. You can run this answer again when you are ready.'
            : friendlyError(err),
        }))
      } finally {
        if (abortRef.current === controller) abortRef.current = null
        sendingRef.current = false
        setSending(false)
      }
    },
    [nid, patch, scrollToBottom],
  )

  const send = useCallback(
    (raw: string) => {
      const text = raw.trim()
      if (!text || sendingRef.current) return
      sendingRef.current = true
      const userMsg: ChatMessage = { id: nid(), role: 'user', content: text }
      const assistantId = nid()
      const assistantMsg: ChatMessage = { id: assistantId, role: 'assistant', content: '', streaming: true, activity: [] }

      const history = boundClientHistory(
        [...messagesRef.current, userMsg]
          .filter((m) => !m.error && m.content.trim() !== '')
          .map((m) => ({ role: m.role, content: m.content })),
      )

      setMessages((prev) => [...prev, userMsg, assistantMsg])
      setInput('')
      if (inputRef.current) inputRef.current.style.height = 'auto'
      setSending(true)
      stickRef.current = true
      requestAnimationFrame(() => scrollToBottom('smooth'))
      void startTurn(history, assistantId)
    },
    [nid, scrollToBottom, startTurn],
  )

  const startGapInterview = useCallback(() => {
    if (interviewStartedRef.current || sendingRef.current) return
    interviewStartedRef.current = true
    const starter =
      interviewSeed?.starter_user_message?.trim() ||
      'I just finished a full case review. Please interview me about the real gaps in my file and then give me an ordered next-step plan. Ask one question at a time.'
    // Clear mode from URL so a refresh doesn't re-seed the interview card.
    if (searchParams.get('mode')) {
      const next = new URLSearchParams(searchParams)
      next.delete('mode')
      setSearchParams(next, { replace: true })
    }
    send(starter)
  }, [interviewSeed, searchParams, setSearchParams, send])

  // Re-run the last turn (after an error or an unhelpful answer): drop any trailing
  // assistant messages, then stream a fresh answer for the last user message.
  const regenerate = useCallback(() => {
    if (sendingRef.current) return
    const prior = messagesRef.current
    let end = prior.length
    while (end > 0 && prior[end - 1].role === 'assistant') end--
    const base = prior.slice(0, end)
    const history = boundClientHistory(
      base
        .filter((m) => !m.error && m.content.trim() !== '')
        .map((m) => ({ role: m.role, content: m.content })),
    )
    if (history.length === 0) return
    sendingRef.current = true
    const assistantId = nid()
    setMessages([...base, { id: assistantId, role: 'assistant', content: '', streaming: true, activity: [] }])
    setSending(true)
    stickRef.current = true
    requestAnimationFrame(() => scrollToBottom('smooth'))
    void startTurn(history, assistantId)
  }, [nid, scrollToBottom, startTurn])

  const stop = useCallback(() => {
    abortRef.current?.abort()
    requestAnimationFrame(() => inputRef.current?.focus())
  }, [])

  const onComposerKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      send(input)
    }
  }

  const onComposerInput = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInput(e.target.value)
    const t = e.currentTarget
    t.style.height = 'auto'
    t.style.height = `${Math.min(t.scrollHeight, 168)}px`
  }

  if (statusLoading) {
    return (
      <div data-section="home" className="vo-page mx-auto flex min-h-[60vh] w-full max-w-3xl items-center justify-center p-4 sm:p-6">
        <LoadingBlock label="Waking up Rating Raider…" />
      </div>
    )
  }

  if (statusError) {
    return (
      <div data-section="home" className="vo-page mx-auto flex min-h-[60vh] w-full max-w-2xl items-center p-4 sm:p-6">
        <div className="w-full">
          <ErrorBlock message={statusError} onRetry={() => setStatusAttempt((attempt) => attempt + 1)} />
        </div>
      </div>
    )
  }

  if (status && !status.available) {
    return (
      <div data-section="home" className="vo-page mx-auto w-full max-w-2xl p-4 sm:p-6">
        <EmptyState
          hue="violet"
          icon={<MessagesSquare size={22} />}
          title="Rating Raider chat isn't available yet"
          description="Rating Raider needs to be switched on for your account. In the meantime, your Claim Plan and other claim tools can still help you organize and review your records."
          action={
            <Link to="/strategy" className="vo-btn-primary">
              Open your Claim Plan
            </Link>
          }
        />
      </div>
    )
  }

  const empty = messages.length === 0
  const available = !status || status.available
  const interviewMode = postAnalysisMode || interviewSeed?.mode === 'post_analysis'
  const onlyAssistantSoFar = messages.length === 0 || messages.every((m) => m.role === 'assistant')
  const showInterviewCta =
    !!interviewSeed &&
    !interviewStartedRef.current &&
    !sending &&
    onlyAssistantSoFar &&
    !!interviewMode

  return (
    <div data-section="home" className="vo-page relative mx-auto flex w-full max-w-3xl flex-col px-3 pb-2 sm:px-5">
      {/* Standing pro-se disclaimer — visible on the chat surface in every state. */}
      <ProSeDisclaimer className="mt-3" />
      <div className="flex flex-1 flex-col pt-5">
        {empty && !postAnalysisMode && !interviewSeed ? (
          <EmptyHero available={available} onPick={send} />
        ) : empty && postAnalysisMode && interviewLoading ? (
          <LoadingBlock label="Loading your gap interview…" />
        ) : (
          <>
            <IdentityHeader available={available} postAnalysis={!!interviewSeed || postAnalysisMode} />
            <ConversationBar
              conversations={conversations}
              activeId={conversationId}
              historyOpen={historyOpen}
              onToggleHistory={() => setHistoryOpen((v) => !v)}
              onNew={startNewChat}
              onOpen={openConversation}
              onDelete={removeConversation}
            />
            <ol
              role="log"
              aria-label="Conversation with Rating Raider"
              aria-live="polite"
              aria-relevant="additions text"
              className="space-y-6"
            >
              {messages.map((m) =>
                m.role === 'user' ? (
                  <UserRow key={m.id} content={m.content} />
                ) : (
                  <AgentRow key={m.id} message={m} onRetry={regenerate} />
                ),
              )}
            </ol>
            {showInterviewCta && (
              <InterviewStartCard
                seed={interviewSeed!}
                onStart={startGapInterview}
                onPickQuestion={(q) => {
                  interviewStartedRef.current = true
                  if (searchParams.get('mode')) {
                    const next = new URLSearchParams(searchParams)
                    next.delete('mode')
                    setSearchParams(next, { replace: true })
                  }
                  send(q)
                }}
                disabled={sending}
              />
            )}
            {/* After post-analysis chat: clear path into Claim Plan coach. */}
            {(interviewStartedRef.current || (messages.some((m) => m.role === 'user') && interviewSeed)) && (
              <div className="mt-6 rounded-control border border-line bg-surface/80 p-4">
                <p className="text-sm font-semibold text-txt">Ready for the ordered plan?</p>
                <p className="mt-1 text-xs text-muted">
                  Open Claim Plan for <strong className="text-txt">Do this first</strong>, Outstanding, and reclaim
                  paths. Educational organizing only.
                </p>
                <Link to="/strategy?from=interview" className="vo-btn-primary mt-3 inline-flex text-sm">
                  Open Claim Plan <ArrowRight size={14} />
                </Link>
              </div>
            )}
          </>
        )}
        <div ref={bottomRef} className="h-px" aria-hidden />
      </div>

      {/* Composer — sticks to the bottom of the scrollport (the Shell's <main>);
          the thread scrolls beneath its blur. */}
      <div className="vo-sticky-mobile-footer sticky z-10 -mx-3 mt-4 border-t border-line bg-surface/80 px-3 pb-3 pt-3 backdrop-blur-md sm:-mx-5 sm:px-5">
        <form
          onSubmit={(e) => {
            e.preventDefault()
            send(input)
          }}
          className="flex items-end gap-2 rounded-2xl border border-line bg-surface px-3 py-2 shadow-soft transition-colors focus-within:border-brand focus-within:ring-2 focus-within:ring-brand-soft"
        >
          <textarea
            ref={inputRef}
            value={input}
            onChange={onComposerInput}
            onKeyDown={onComposerKeyDown}
            rows={1}
            maxLength={8000}
            placeholder="Ask Rating Raider anything about your claim…"
            aria-label="Message Rating Raider"
            className="max-h-[168px] min-h-10 min-w-0 flex-1 resize-none self-center bg-transparent py-2.5 text-body leading-relaxed text-txt placeholder:text-faint focus:outline-none"
          />
          {sending ? (
            <button
              type="button"
              onClick={stop}
              aria-label="Stop Rating Raider's response"
              title="Stop response"
              className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-line bg-surface2 text-txt transition-colors hover:bg-surface"
            >
              <Square size={15} className="fill-current" aria-hidden="true" />
            </button>
          ) : (
            <button
              type="submit"
              disabled={!input.trim()}
              aria-label="Send message"
              title="Send"
              style={{ backgroundColor: 'var(--brand-strong)' }}
              className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full text-white shadow-sm transition enabled:hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <ArrowUp size={17} aria-hidden="true" />
            </button>
          )}
        </form>
        <p className="mt-2 px-1 text-center text-micro leading-relaxed text-faint">
          Rating Raider explains and organizes — it never files for you or predicts VA's decision. Confirm forms,
          deadlines, and criteria on VA.gov or with an accredited VSO.
        </p>
      </div>
    </div>
  )
}

// ── Empty-state hero ─────────────────────────────────────────────────────────
function EmptyHero({ available, onPick }: { available: boolean; onPick: (prompt: string) => void }) {
  return (
    <div className="flex min-h-[56vh] flex-1 flex-col items-center justify-center px-2 py-8 text-center">
      <div className="relative mb-5">
        <div
          aria-hidden
          className="absolute inset-0 -z-10 scale-150 rounded-full blur-2xl"
          style={{ background: 'radial-gradient(circle, var(--brand-soft), transparent 70%)' }}
        />
        <Logo size={78} />
      </div>
      <h1 className="vo-page-title">Talk to Rating Raider</h1>
      <p className="mt-2.5 max-w-[48ch] text-body leading-relaxed text-muted">
        I'm your Chief Warrant Officer for this claim. Ask me anything — I use your record and the VA rulebook to
        explain what to review and help you organize a next step. I never file for you or predict VA's decision.
      </p>
      {!available && (
        <p className="mt-3 text-caption text-warn">
          Heads up: Rating Raider looks offline right now — you can still try, and I'll tell you if I can't connect.
        </p>
      )}
      <div className="mt-7 grid w-full max-w-xl gap-2.5 sm:grid-cols-2">
        {STARTERS.map((s) => (
          <button
            key={s.label}
            type="button"
            onClick={() => onPick(s.prompt)}
            className="vo-hue-link text-left"
          >
            <s.icon size={17} className="shrink-0 text-h-violet" aria-hidden="true" />
            <span className="min-w-0 flex-1">{s.label}</span>
          </button>
        ))}
      </div>
    </div>
  )
}

// ── Identity header (active chat) ────────────────────────────────────────────
function IdentityHeader({ available, postAnalysis }: { available: boolean; postAnalysis?: boolean }) {
  return (
    <div className="mb-6 flex items-center gap-3 border-b border-line pb-4">
      <Logo size={40} />
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-heading font-semibold text-txt">Rating Raider</span>
          {available && (
            <span
              className="inline-flex items-center gap-1 text-micro font-semibold uppercase tracking-wider"
              style={{ color: hueInk('emerald') }}
            >
              <span aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-success shadow-[0_0_6px_var(--success)]" />
              Online
            </span>
          )}
        </div>
        <p className="text-caption leading-relaxed text-muted">
          {postAnalysis
            ? 'Post-analysis coach — optional gap interview, then an ordered plan. Educational only; never files for you.'
            : 'Your CWO — explains the rules, organizes your record, and helps you prepare. Never files for you.'}
        </p>
      </div>
    </div>
  )
}

/** Past chats + new chat — localStorage-backed so navigate-away keeps history. */
function ConversationBar({
  conversations,
  activeId,
  historyOpen,
  onToggleHistory,
  onNew,
  onOpen,
  onDelete,
}: {
  conversations: RaiderConversation[]
  activeId: string | null
  historyOpen: boolean
  onToggleHistory: () => void
  onNew: () => void
  onOpen: (id: string) => void
  onDelete: (id: string) => void
}) {
  const withContent = conversations.filter((c) => c.messages.some((m) => m.content.trim()))
  return (
    <div className="mb-4 rounded-control border border-line bg-surface/70">
      <div className="flex flex-wrap items-center gap-2 px-3 py-2">
        <button type="button" className="vo-btn-ghost text-xs" onClick={onToggleHistory} aria-expanded={historyOpen}>
          <History size={14} />
          Past chats {withContent.length > 0 ? `(${withContent.length})` : ''}
        </button>
        <button type="button" className="vo-btn-secondary text-xs" onClick={onNew}>
          <Plus size={14} /> New chat
        </button>
        <p className="text-micro text-faint">Saved on this device — leave and come back anytime.</p>
      </div>
      {historyOpen && (
        <ul className="max-h-56 divide-y divide-line overflow-y-auto border-t border-line">
          {withContent.length === 0 ? (
            <li className="px-3 py-3 text-xs text-muted">No saved conversations yet.</li>
          ) : (
            withContent.map((c) => {
              const active = c.id === activeId
              const when = c.updatedAt ? new Date(c.updatedAt).toLocaleString() : ''
              return (
                <li key={c.id} className={active ? 'bg-h-violet-soft/30' : undefined}>
                  <div className="flex items-start gap-2 px-3 py-2">
                    <button
                      type="button"
                      className="min-w-0 flex-1 text-left"
                      onClick={() => onOpen(c.id)}
                    >
                      <span className="block truncate text-sm font-medium text-txt">{c.title}</span>
                      <span className="block text-micro text-faint">
                        {c.kind === 'post_analysis' ? 'Interview · ' : ''}
                        {when}
                      </span>
                    </button>
                    <button
                      type="button"
                      className="vo-btn-ghost shrink-0 p-1.5 text-faint hover:text-danger"
                      title="Delete chat"
                      onClick={() => {
                        if (window.confirm('Delete this conversation from this device?')) onDelete(c.id)
                      }}
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                </li>
              )
            })
          )}
        </ul>
      )}
    </div>
  )
}

/** CTA after opening bubble: Start gap interview seeds starter_user_message. */
function InterviewStartCard({
  seed,
  onStart,
  onPickQuestion,
  disabled,
}: {
  seed: InterviewSeed
  onStart: () => void
  onPickQuestion: (prompt: string) => void
  disabled: boolean
}) {
  const questions = seed.questions ?? []
  return (
    <div className="mt-5 rounded-2xl border border-h-violet/30 bg-h-violet-soft/40 p-4 sm:p-5">
      <p className="text-sm font-semibold text-txt">Optional but recommended</p>
      <p className="mt-1 text-sm leading-relaxed text-muted">
        A short gap interview fills in what the file cannot see (work, CFS vs fibro, knees, goals). Answers help
        organize your checklist and Claim Plan — not a VA interview, and Rating Raider does not file for you.
      </p>
      <div className="mt-4 flex flex-wrap gap-2">
        <button type="button" onClick={onStart} disabled={disabled} className="vo-btn-primary">
          <MessagesSquare size={15} /> Start gap interview
        </button>
        <Link to="/strategy?from=interview" className="vo-btn-secondary text-sm">
          Skip to Claim Plan <ArrowRight size={14} />
        </Link>
      </div>
      {questions.length > 0 && (
        <div className="mt-4">
          <p className="mb-2 text-micro font-bold uppercase tracking-wide text-faint">Or jump to a topic</p>
          <div className="flex flex-wrap gap-2">
            {questions.slice(0, 6).map((q) => (
              <button
                key={q.id}
                type="button"
                disabled={disabled}
                onClick={() => onPickQuestion(q.question)}
                className="vo-btn-secondary text-xs"
                title={q.why || q.topic}
              >
                {q.topic || q.question.slice(0, 40)}
              </button>
            ))}
          </div>
        </div>
      )}
      {seed.closing_hint && (
        <p className="mt-3 text-xs text-faint">{seed.closing_hint}</p>
      )}
    </div>
  )
}

// ── Message rows ─────────────────────────────────────────────────────────────
function UserRow({ content }: { content: string }) {
  return (
    <li className="flex justify-end">
      <div className="max-w-[85%] whitespace-pre-wrap break-words rounded-2xl rounded-br-md border border-brand/20 bg-brand-soft px-4 py-2.5 text-body leading-relaxed text-txt">
        <span className="sr-only">You said: </span>
        {content}
      </div>
    </li>
  )
}

function AgentRow({ message, onRetry }: { message: ChatMessage; onRetry: () => void }) {
  const activeTool = message.activity?.some((a) => !a.done)
  const showThinking = message.streaming && !message.content && !activeTool
  return (
    <li className="flex gap-3">
      <Logo size={30} className="mt-0.5 shrink-0" />
      <div className="min-w-0 flex-1 space-y-2.5">
        <span className="sr-only">Rating Raider: </span>
        {message.activity && message.activity.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {message.activity.map((a) => (
              <ToolChip key={a.id} name={a.name} done={a.done} />
            ))}
          </div>
        )}

        {message.content ? (
          <div
            className="vo-prose max-w-[46rem] break-words rounded-2xl rounded-tl-md border border-line bg-surface/60 px-4 py-3 backdrop-blur"
            dangerouslySetInnerHTML={{ __html: renderAgentMarkdown(message.content) + (message.streaming ? CARET : '') }}
          />
        ) : showThinking ? (
          <ThinkingBubble />
        ) : null}

        {message.error && (
          <div
            className="flex flex-wrap items-center gap-2 rounded-control border border-[color-mix(in_oklab,var(--danger)_40%,transparent)] bg-danger-soft px-3 py-2 text-sm"
            role="alert"
            style={{ color: 'color-mix(in srgb, var(--danger) var(--mix-ink, 92%), var(--txt))' }}
          >
            <AlertCircle size={15} className="shrink-0" aria-hidden="true" />
            <span className="min-w-[12rem] flex-1">{message.error}</span>
            <button type="button" onClick={onRetry} className="vo-btn-secondary shrink-0 text-xs">
              <RotateCcw size={13} aria-hidden="true" />
              Try again
            </button>
          </div>
        )}
      </div>
    </li>
  )
}

function ToolChip({ name, done }: { name: string; done: boolean }) {
  if (done) {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full border border-line bg-surface2 px-2.5 py-1 text-xs font-medium text-muted">
        <Check size={12} className="text-success" aria-hidden="true" />
        {toolLabel(name, true)}
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-2 rounded-full border border-h-violet/30 bg-h-violet-soft px-2.5 py-1 text-xs font-medium text-h-violet">
      <Spinner size={12} />
      {toolLabel(name, false)}
    </span>
  )
}

function ThinkingBubble() {
  return (
    <div
      className="inline-flex items-center gap-1.5 rounded-2xl rounded-tl-md border border-line bg-surface/60 px-4 py-3.5 backdrop-blur"
    >
      <span className="sr-only">Rating Raider is thinking.</span>
      {[0, 160, 320].map((d) => (
        <span
          key={d}
          className="h-1.5 w-1.5 animate-pulsedot rounded-full bg-muted"
          style={{ animationDelay: `${d}ms` }}
          aria-hidden="true"
        />
      ))}
    </div>
  )
}
