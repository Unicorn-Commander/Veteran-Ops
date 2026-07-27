import { ArrowLeft, FileText, Lock } from 'lucide-react'
import { useEffect, type CSSProperties, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { Wordmark } from '../components/Brand'
import { LoadingBlock, ErrorBlock, Panel } from '../components/ui'
import { useAsync } from '../hooks/useAsync'
import { legalApi } from '../lib/api'
import { hueStyle } from '../lib/hues'

// /legal — terms of use + privacy policy (GET /api/legal, no auth: it's shown
// pre-signup and is a VA Lighthouse production-access prerequisite). The
// backend serves plain markdown; we render it with a tiny local parser —
// no new dependencies, no innerHTML (everything goes through React nodes).

/** Inline markdown: **bold** and _italic_ → React nodes (no HTML injection). */
function renderInline(text: string, keyBase: string): ReactNode[] {
  const out: ReactNode[] = []
  const re = /\*\*(.+?)\*\*|_([^_]+)_/g
  let last = 0
  let m: RegExpExecArray | null
  let k = 0
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) out.push(text.slice(last, m.index))
    if (m[1] !== undefined) out.push(<strong key={`${keyBase}-${k++}`}>{m[1]}</strong>)
    else out.push(<em key={`${keyBase}-${k++}`}>{m[2]}</em>)
    last = m.index + m[0].length
  }
  if (last < text.length) out.push(text.slice(last))
  return out
}

/** Block-level markdown: #/##/### headings, `- ` bullet lists, paragraphs.
 * Exactly what the backend's legal documents use — nothing more. */
function Markdown({ source }: { source: string }) {
  const blocks = source.split(/\n{2,}/).map((b) => b.trim()).filter(Boolean)
  return (
    <div className="vo-prose">
      {blocks.map((block, i) => {
        const lines = block.split('\n')
        if (lines.every((l) => /^-\s+/.test(l.trim()) || l.startsWith('  '))) {
          // Bullet list (continuation lines indented under their item).
          const items: string[] = []
          for (const l of lines) {
            if (/^-\s+/.test(l.trim())) items.push(l.trim().replace(/^-\s+/, ''))
            else if (items.length > 0) items[items.length - 1] += ` ${l.trim()}`
          }
          return (
            <ul key={i}>
              {items.map((item, j) => (
                <li key={j}>{renderInline(item, `${i}-${j}`)}</li>
              ))}
            </ul>
          )
        }
        const heading = /^(#{1,3})\s+(.*)$/.exec(lines[0])
        if (heading && lines.length === 1) {
          const text = renderInline(heading[2], `h-${i}`)
          if (heading[1].length === 1)
            return (
              <h2 key={i} className="mb-2 mt-5 text-xl font-bold text-txt first:mt-0">
                {text}
              </h2>
            )
          return <h3 key={i}>{text}</h3>
        }
        return <p key={i}>{renderInline(block.replace(/\n/g, ' '), `p-${i}`)}</p>
      })}
    </div>
  )
}

export function Legal() {
  const { data, loading, error, reload } = useAsync(() => legalApi.get())

  // Standalone route (no Shell): honor the saved theme choice ourselves.
  useEffect(() => {
    const saved = localStorage.getItem('vo_theme')
    document.documentElement.dataset.theme = saved === 'light' ? 'light' : ''
  }, [])

  return (
    <div data-section="settings" className="vo-page mx-auto w-full max-w-3xl space-y-5 p-4 pb-16 sm:p-6">
      <div className="flex items-center justify-between pt-2">
        <Wordmark size={30} />
        <Link to="/" className="vo-btn-ghost text-sm">
          <ArrowLeft size={15} /> Back to Rating Raider
        </Link>
      </div>

      <div className="vo-section-band">
        <p className="vo-caption mb-1">The fine print, in plain language</p>
        <h1 className="vo-page-title">Terms &amp; privacy</h1>
        <p className="vo-page-sub">
          What Rating Raider is (self-help educational software you operate yourself), what it never does, and how
          your data is handled. Veterans should be able to read this without a lawyer.
        </p>
      </div>

      <nav aria-label="Jump to section" className="flex flex-wrap gap-1.5">
        <a href="#legal-terms" className="vo-chip-hue no-underline" style={hueStyle('violet') as CSSProperties}>
          Terms of use
        </a>
        <a href="#legal-privacy" className="vo-chip-hue no-underline" style={hueStyle('teal') as CSSProperties}>
          Privacy policy
        </a>
      </nav>

      {loading ? (
        <LoadingBlock label="Loading terms and privacy…" />
      ) : error || !data ? (
        <ErrorBlock message={error ?? 'Could not load the legal documents.'} onRetry={reload} />
      ) : (
        <>
          <div id="legal-terms" className="scroll-mt-6">
            <Panel
              hue="violet"
              title={
                <span className="flex items-center gap-2">
                  <FileText size={15} /> Terms of use
                </span>
              }
            >
              <div className="p-5">
                <Markdown source={data.terms} />
              </div>
            </Panel>
          </div>
          <div id="legal-privacy" className="scroll-mt-6">
            <Panel
              hue="teal"
              title={
                <span className="flex items-center gap-2">
                  <Lock size={15} /> Privacy policy
                </span>
              }
            >
              <div className="p-5">
                <Markdown source={data.privacy} />
              </div>
            </Panel>
          </div>
        </>
      )}
    </div>
  )
}
