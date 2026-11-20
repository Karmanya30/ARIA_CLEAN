import { useEffect, useRef, useState, type PointerEvent, type ReactNode } from 'react'
import {
  ArrowRight, BadgeCheck, Calculator, Check, Compass, Database, Download, FileSearch, FileText, GraduationCap, LineChart,
  Lock, MessageSquare, Mic, Moon, Scale, Search, ShieldCheck, Sparkles, Sun, TrendingUp, Video, Wallet,
} from 'lucide-react'
import { BrandLogo, BrandMark } from './components/brand/BrandLogo'
import { Sparkline } from './versions/v2/components/markets/Sparkline'
import { setModeSetting, useModeSetting } from './versions/v2/theme'
import './landing.css'

const REDUCE = typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches

/** Deterministic random walk, so the illustrative charts look the same on every visit. */
function walk(n: number, seed: number, drift = 0) {
  let s = seed, x = 100
  return Array.from({ length: n }, () => { s = (s * 16807) % 2147483647; x += (s / 2147483647 - 0.5 + drift) * 2.4; return x })
}

/** Spotlight + tilt: writes the pointer position as CSS variables; landing.css decides what uses them. */
function track(e: PointerEvent<HTMLElement>) {
  const el = e.currentTarget, r = el.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top
  el.style.setProperty('--px', `${x}px`); el.style.setProperty('--py', `${y}px`)
  el.style.setProperty('--rx', `${(y / r.height - 0.5) * -7}deg`); el.style.setProperty('--ry', `${(x / r.width - 0.5) * 7}deg`)
}
function untrack(e: PointerEvent<HTMLElement>) {
  e.currentTarget.style.setProperty('--rx', '0deg'); e.currentTarget.style.setProperty('--ry', '0deg')
}

function useInView<T extends Element>(threshold = 0.25) {
  const ref = useRef<T>(null)
  const [seen, setSeen] = useState(false)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const io = new IntersectionObserver(([e]) => { if (e.isIntersecting) { setSeen(true); io.disconnect() } }, { threshold })
    io.observe(el)
    return () => io.disconnect()
  }, [threshold])
  return [ref, seen] as const
}

function Typewriter({ text, run, speed = 34 }: { text: string; run: boolean; speed?: number }) {
  const [n, setN] = useState(REDUCE ? text.length : 0)
  useEffect(() => {
    if (!run || REDUCE) return
    let k = 0
    const id = setInterval(() => { k += 1; setN(k); if (k >= text.length) clearInterval(id) }, speed)
    return () => clearInterval(id)
  }, [run, text, speed])
  return <>{text.slice(0, n)}</>
}

/* ── Hero chat demo: types a question, "thinks", counts up a figure from ARIA's calculators ── */
const DEMOS = [
  { q: 'How much SIP do I need for ₹1 crore in 15 years?', big: 19819, unit: 'a month',
    line: 'at 12% a year. You put in ₹35.7 lakh; growth adds about ₹64.3 lakh.', tool: 'SIP calculator', curve: 'M4 86 C 90 84, 150 76, 196 56 S 272 12, 296 4' },
  { q: 'EMI on a ₹50 lakh home loan at 8.5% for 20 years?', big: 43391, unit: 'a month',
    line: 'Over 20 years you pay about ₹54.1 lakh in interest on top of the loan.', tool: 'EMI calculator', curve: 'M4 10 C 80 14, 160 30, 220 52 S 280 80, 296 86' },
]

function ChatDemo() {
  const [i, setI] = useState(0)
  const [typed, setTyped] = useState(REDUCE ? DEMOS[0].q : '')
  const [phase, setPhase] = useState<'type' | 'think' | 'answer'>(REDUCE ? 'answer' : 'type')
  const [n, setN] = useState(REDUCE ? DEMOS[0].big : 0)
  useEffect(() => {
    if (REDUCE) return
    let dead = false
    const d = DEMOS[i]
    const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))
    void (async () => {
      setPhase('type'); setN(0)
      for (let k = 1; k <= d.q.length; k++) { if (dead) return; setTyped(d.q.slice(0, k)); await sleep(30) }
      await sleep(350); if (dead) return
      setPhase('think'); await sleep(1100); if (dead) return
      setPhase('answer')
      const t0 = performance.now()
      await new Promise<void>((res) => {
        const f = (t: number) => {
          if (dead) return res()
          const p = Math.min(1, (t - t0) / 1100)
          setN(Math.round(d.big * (1 - (1 - p) ** 3)))
          if (p < 1) requestAnimationFrame(f); else res()
        }
        requestAnimationFrame(f)
      })
      await sleep(4600)
      if (!dead) setI((x) => (x + 1) % DEMOS.length)
    })()
    return () => { dead = true }
  }, [i])
  const d = DEMOS[i]
  return <figure className="lp-chat" aria-label="Example conversation with ARIA">
    <div className={`lp-chat-q${phase === 'type' ? ' is-typing' : ''}`}>{typed}</div>
    <div className="lp-chat-a">
      <BrandMark className="lp-chat-mark" />
      {phase !== 'answer'
        ? <div className="lp-chat-think" aria-label="ARIA is working"><i /><i /><i style={{ width: '45%' }} /></div>
        : <div className="lp-chat-body">
          <p className="lp-chat-big">₹{n.toLocaleString('en-IN')} <span>{d.unit}</span></p>
          <svg className="lp-chat-curve" viewBox="0 0 300 90" preserveAspectRatio="none" aria-hidden="true" key={i}>
            <path d={d.curve} />
          </svg>
          <p className="lp-chat-line">{d.line}</p>
          <ul className="lp-chat-tags" aria-label="How this was produced">
            <li><Calculator size={13} aria-hidden="true" /> {d.tool}</li>
            <li><BadgeCheck size={13} aria-hidden="true" /> Figures checked</li>
          </ul>
        </div>}
    </div>
    <figcaption>Example answers. Figures come from ARIA's own calculators.</figcaption>
  </figure>
}

/* ── Product showcase: four real screens of the app, recreated with illustrative data ── */
const SHOWS = [
  { id: 'avatar', icon: Video, title: 'Talking avatar', text: 'Ask out loud. ARIA answers with a voice and a lip-synced face.', url: 'chat · live avatar' },
  { id: 'report', icon: FileText, title: 'Equity research, live', text: 'A full valuation report in about a minute. Every figure is tagged with where it came from.', url: 'reports' },
  { id: 'markets', icon: LineChart, title: 'Markets dashboard', text: 'Indices, sectors and movers, with the news behind each move.', url: 'markets' },
  { id: 'explore', icon: Compass, title: 'Explore anything', text: 'Any stock, fund, ETF or coin. See its history and test a SIP on it.', url: 'explore' },
] as const

function AvatarScreen({ active }: { active: boolean }) {
  const video = useRef<HTMLVideoElement>(null)
  useEffect(() => {
    const v = video.current
    if (!v) return
    if (active && !REDUCE) v.play().catch(() => undefined); else v.pause()
  }, [active])
  return <div className="lp-av">
    <video ref={video} src="/landing/aria-avatar.mp4" muted loop playsInline preload="metadata" aria-label="ARIA's avatar speaking" />
    <span className="lp-live"><i /> Live</span>
    <span className="lp-av-name">ARIA · Finance tutor</span>
    <div className="lp-av-user"><Mic size={14} aria-hidden="true" /> “Explain index funds simply”</div>
    <div className="lp-av-cap">
      <Typewriter run={active} speed={28} text="An index fund buys every stock in an index like the Nifty 50, so you own a small piece of all of them, at a low cost." />
    </div>
    <div className="lp-wave" aria-hidden="true">{Array.from({ length: 22 }, (_, k) => <i key={k} style={{ animationDelay: `${-k * 0.13}s` }} />)}</div>
  </div>
}

function ReportScreen() {
  const SCORES = [['Growth', 72], ['Profitability', 81], ['Balance sheet', 88], ['Valuation', 54]] as const
  return <div className="lp-rep">
    <header>
      <div><b>Example Industries Ltd</b><span>NSE · Capital goods · illustrative</span></div>
      <span className="lp-rep-ver">Report v3 · saved</span>
    </header>
    <section>
      <h4>Fair value range</h4>
      <div className="lp-range">
        <div className="lp-range-bar"><i className="bear" /><i className="base" /><i className="bull" /></div>
        <span className="lp-range-now" style={{ left: '38%' }}>Price ₹1,350</span>
        <div className="lp-range-lbl"><span>Bear ₹1,180</span><span>Base ₹1,420</span><span>Bull ₹1,690</span></div>
      </div>
    </section>
    <div className="lp-rep-cols">
      <section>
        <h4>Scorecard</h4>
        {SCORES.map(([k, v], i) => <div className="lp-score" key={k}>
          <span>{k}</span><div><i style={{ width: `${v}%`, transitionDelay: `${0.25 + i * 0.12}s` }} /></div><b>{v}</b>
        </div>)}
      </section>
      <section>
        <h4>DuPont: where ROE comes from</h4>
        <div className="lp-dupont">
          <span><b>18.3%</b>ROE</span>=<span><b>9.1%</b>margin</span>×<span><b>1.30</b>turnover</span>×<span><b>1.55</b>leverage</span>
        </div>
        <ul className="lp-src" aria-label="Figure tags">
          <li className="act">ACTUAL</li><li className="calc">CALCULATED</li><li className="est">ESTIMATE</li>
        </ul>
      </section>
    </div>
    <footer><span><ShieldCheck size={15} aria-hidden="true" /> 10 of 10 audit checks passed</span><span className="lp-rep-dl"><Download size={14} aria-hidden="true" /> PDF</span></footer>
  </div>
}

const CLOSES = walk(46, 11, 0.07)
function CandleChart() {
  const W = 560, H = 210, pad = 8
  const bars = CLOSES.map((c, i) => {
    const o = i ? CLOSES[i - 1] : c - 0.8, wick = Math.abs(c - o) * 0.45 + 0.35
    return { o, c, h: Math.max(o, c) + wick, l: Math.min(o, c) - wick }
  })
  const lo = Math.min(...bars.map((b) => b.l)), hi = Math.max(...bars.map((b) => b.h))
  const y = (v: number) => pad + (1 - (v - lo) / (hi - lo)) * (H - pad * 2)
  const step = W / bars.length
  const avg = CLOSES.map((_, i) => { const s = CLOSES.slice(Math.max(0, i - 7), i + 1); return s.reduce((a, b) => a + b, 0) / s.length })
  const [hover, setHover] = useState<number | null>(null)
  const hb = hover === null ? null : bars[hover]
  return <div className="lp-candles">
    <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" aria-label="Illustrative candlestick chart"
      onPointerMove={(e) => { const r = e.currentTarget.getBoundingClientRect(); setHover(Math.max(0, Math.min(bars.length - 1, Math.floor(((e.clientX - r.left) / r.width) * bars.length)))) }}
      onPointerLeave={() => setHover(null)}>
      {[0.25, 0.5, 0.75].map((g) => <line key={g} className="grid" x1="0" x2={W} y1={H * g} y2={H * g} />)}
      {bars.map((b, i) => <g key={i} className={b.c >= b.o ? 'up' : 'down'} style={{ animationDelay: `${i * 18}ms` }}>
        <line x1={i * step + step / 2} x2={i * step + step / 2} y1={y(b.h)} y2={y(b.l)} />
        <rect x={i * step + step * 0.2} width={step * 0.6} y={y(Math.max(b.o, b.c))} height={Math.max(1.5, Math.abs(y(b.o) - y(b.c)))} rx="1.5" />
      </g>)}
      <polyline className="avg" points={avg.map((v, i) => `${i * step + step / 2},${y(v)}`).join(' ')} />
      {hb && hover !== null && <g className="cross">
        <line x1={hover * step + step / 2} x2={hover * step + step / 2} y1="0" y2={H} />
        <line x1="0" x2={W} y1={y(hb.c)} y2={y(hb.c)} />
      </g>}
    </svg>
    <div className="lp-candles-tip" aria-live="polite">{hb && hover !== null
      ? <>Day {hover + 1} · O {hb.o.toFixed(1)} · C <b className={hb.c >= hb.o ? 'up' : 'down'}>{hb.c.toFixed(1)}</b></>
      : 'Hover the chart'}</div>
  </div>
}

const INDICES = [['Nifty 50', 3], ['Sensex', 5], ['Bank Nifty', 9]].map(([name, seed]) => {
  const pts = walk(30, seed as number, 0.04), d = (pts[pts.length - 1] - pts[0]) / 10 // as if the index sat near 1,000
  return { name: name as string, pts, d: `${d >= 0 ? '+' : '−'}${Math.abs(d).toFixed(1)}%` } // label always matches the line
})
const SECTORS = [['IT', 1.4], ['Bank', -0.3], ['Auto', 0.9], ['Pharma', 0.4], ['FMCG', -0.6], ['Metal', 2.1], ['Energy', -1.1], ['Realty', 1.7]] as const

function MarketsScreen() {
  return <div className="lp-mk">
    <div className="lp-mk-top">
      {INDICES.map((x) => <div className="lp-mk-card" key={x.name}>
        <span>{x.name}</span><b className={x.d.startsWith('+') ? 'up' : 'down'}>{x.d}</b>
        <Sparkline points={x.pts} label={x.name} />
      </div>)}
    </div>
    <div className="lp-mk-main">
      <div className="lp-mk-chart"><div className="lp-mk-head"><b>Nifty 50</b><span>3 months · daily</span></div><CandleChart /></div>
      <div className="lp-heat">
        <div className="lp-mk-head"><b>Sectors</b><span>today</span></div>
        <div className="lp-heat-grid">{SECTORS.map(([s, v], i) => <span key={s} className={v >= 0 ? 'up' : 'down'}
          style={{ '--a': Math.min(1, Math.abs(v) / 2.2), animationDelay: `${i * 0.4}s` } as React.CSSProperties}>{s}<b>{v > 0 ? '+' : ''}{v}%</b></span>)}</div>
      </div>
    </div>
    <span className="lp-illus">Illustrative data</span>
  </div>
}

function ExploreScreen({ active }: { active: boolean }) {
  const line = walk(40, 21, 0.12)
  return <div className="lp-ex">
    <div className="lp-ex-search"><Search size={16} aria-hidden="true" /><span><Typewriter run={active} text="parag parikh" speed={70} /></span><i className="lp-caret" /></div>
    <ul className="lp-ex-results">
      <li className="on"><b>Parag Parikh Flexi Cap Fund</b><span>Mutual fund · Equity</span></li>
      <li><b>Parag Parikh ELSS Tax Saver Fund</b><span>Mutual fund · ELSS</span></li>
      <li><b>Parag Parikh Conservative Hybrid Fund</b><span>Mutual fund · Hybrid</span></li>
    </ul>
    <div className="lp-ex-card">
      <div className="lp-ex-chart"><span>History · illustrative</span><Sparkline points={line} label="Fund history, illustrative" /></div>
      <div className="lp-ex-sip">
        <span>Test a SIP</span>
        <p>₹10,000 a month for 10 years</p>
        <b>₹23.2 lakh</b>
        <small>if it grows 12% a year · you invest ₹12 lakh</small>
      </div>
    </div>
    <div className="lp-ex-ask"><span><MessageSquare size={14} aria-hidden="true" /> Is this fund right for a 10-year goal?</span><span>Compare with an index fund</span></div>
  </div>
}

function Showcase() {
  const [active, setActive] = useState(0)
  const [ref, seen] = useInView<HTMLDivElement>(0.3)
  const shows: Record<string, (on: boolean) => ReactNode> = {
    avatar: (on) => <AvatarScreen active={on} />, report: () => <ReportScreen />,
    markets: () => <MarketsScreen />, explore: (on) => <ExploreScreen active={on} />,
  }
  return <div ref={ref} className={`lp-show${seen ? ' is-seen' : ''}`}>
    <div className="lp-show-tabs" role="tablist" aria-label="ARIA screens">
      {SHOWS.map((s, i) => <button key={s.id} type="button" role="tab" aria-selected={i === active} aria-controls={`lp-panel-${s.id}`}
        className={i === active ? 'is-active' : ''} onClick={() => setActive(i)}>
        <span className="lp-show-ico"><s.icon size={18} aria-hidden="true" /></span>
        <span className="lp-show-copy"><b>{s.title}</b><span>{s.text}</span></span>
        {i === active && <span className="lp-show-bar" onAnimationEnd={() => setActive((i + 1) % SHOWS.length)}><i /></span>}
      </button>)}
    </div>
    <div className="lp-window" onPointerMove={track} onPointerLeave={untrack}>
      <div className="lp-window-bar" aria-hidden="true"><i /><i /><i /><span>aria / {SHOWS[active].url}</span></div>
      <div className="lp-window-body">
        {SHOWS.map((s, i) => <div key={s.id} id={`lp-panel-${s.id}`} role="tabpanel" aria-hidden={i !== active}
          className={`lp-panel${i === active ? ' is-active' : ''}`}>{shows[s.id](i === active && seen)}</div>)}
      </div>
    </div>
  </div>
}

/* ── How an answer is made: a pinned visual that changes as the steps scroll past ── */
const STEPS = [
  { icon: MessageSquare, title: 'You ask', text: 'Type or speak, in English or Hinglish. Typos are fine.' },
  { icon: Database, title: 'ARIA gathers real data', text: 'Prices, company filings, news and your saved profile.' },
  { icon: Calculator, title: 'Code does the maths', text: 'Calculators compute every figure. The AI only explains the result.' },
  { icon: ShieldCheck, title: 'Unsupported figures are removed', text: 'A sentence with a number that is not in the fetched data is cut before you see it.' },
]

function Story() {
  const [step, setStep] = useState(1)
  const list = useRef<HTMLOListElement>(null)
  useEffect(() => {
    const items = list.current?.querySelectorAll('li')
    if (!items) return
    const io = new IntersectionObserver((es) => es.forEach((e) => e.isIntersecting && setStep(Number((e.target as HTMLElement).dataset.step))),
      { rootMargin: '-45% 0px -45% 0px' })
    items.forEach((li) => io.observe(li))
    return () => io.disconnect()
  }, [])
  const at = Array.from({ length: step }, (_, k) => `at-${k + 1}`).join(' ')
  return <div className="lp-story">
    <div className="lp-story-sticky">
      <div className={`lp-story-vis ${at}`} aria-hidden="true">
        <div className="lp-sv-q s1">“Can I afford a ₹40 lakh flat on ₹1.2 lakh a month?”</div>
        <svg className="lp-sv-lines s2" viewBox="0 0 400 170" preserveAspectRatio="none">
          <path d="M40 18 C 130 18, 150 85, 200 85" /><path d="M360 18 C 270 18, 250 85, 200 85" />
          <path d="M40 152 C 130 152, 150 85, 200 85" /><path d="M360 152 C 270 152, 250 85, 200 85" />
        </svg>
        <span className="lp-sv-src s2" style={{ left: '4%', top: 100 }}>Prices</span>
        <span className="lp-sv-src s2" style={{ right: '4%', top: 100 }}>Filings</span>
        <span className="lp-sv-src s2" style={{ left: '4%', top: 236 }}>News</span>
        <span className="lp-sv-src s2" style={{ right: '4%', top: 236 }}>Your profile</span>
        <div className="lp-sv-core"><BrandMark /></div>
        <div className="lp-sv-calc s3"><Calculator size={15} /> ₹32 lakh loan · EMI ₹27,770 · 23% of income</div>
        <div className="lp-sv-ans s4">
          <p>With an ₹8 lakh down payment, the EMI is about 23% of your income, well under the 40% many lenders use as a ceiling.</p>
          <p className="lp-sv-fake"><span>Property here always rises 15% a year.</span></p>
          <p className="lp-sv-ok"><Check size={14} /> Removed: no source for that figure</p>
        </div>
      </div>
    </div>
    <ol ref={list} className="lp-story-steps">
      {STEPS.map(({ icon: Icon, title, text }, i) => <li key={title} data-step={i + 1} className={step === i + 1 ? 'is-active' : ''}>
        <span className="lp-story-n">0{i + 1}</span>
        <Icon size={22} aria-hidden="true" />
        <h3>{title}</h3>
        <p>{text}</p>
      </li>)}
    </ol>
  </div>
}

function Counter({ to, suffix = '' }: { to: number; suffix?: string }) {
  const [ref, seen] = useInView<HTMLSpanElement>(0.6)
  const [n, setN] = useState(REDUCE ? to : 0)
  useEffect(() => {
    if (!seen || REDUCE) return
    const t0 = performance.now()
    let raf = 0
    const f = (t: number) => { const p = Math.min(1, (t - t0) / 1400); setN(Math.round(to * (1 - (1 - p) ** 3))); if (p < 1) raf = requestAnimationFrame(f) }
    raf = requestAnimationFrame(f)
    return () => cancelAnimationFrame(raf)
  }, [seen, to])
  return <span ref={ref}>{n.toLocaleString('en-IN')}{suffix}</span>
}

const MODULES = [
  { icon: Wallet, name: 'Personal Finance', text: 'Budgets, SIP targets, EMIs and tax under the old and new regimes, worked out from your own numbers.', cls: 'fin' },
  { icon: GraduationCap, name: 'Finance Tutor', text: 'One concept at a time, with short quizzes that track what you have mastered.', cls: 'tut' },
  { icon: TrendingUp, name: 'Market Analysis', text: 'Why Nifty, Sensex or a sector moved today, with the headlines behind it.', cls: 'mkt' },
  { icon: FileSearch, name: 'Equity Research', text: 'Valuation reports on Indian companies, where every figure shows where it came from.', cls: 'res' },
]
const TRUST = [
  { icon: Scale, title: 'No buy or sell tips', text: 'ARIA explains and compares. Decisions stay with you.' },
  { icon: BadgeCheck, title: 'Figures you can check', text: 'Numbers come from calculators and fetched data, never from the AI’s imagination.' },
  { icon: Lock, title: 'Your data stays yours', text: 'Each account sees only its own profile and chats, and you can erase everything in one step.' },
]
const TICKER = ['Nifty 50', 'Sensex', 'Bank Nifty', 'SIP', 'EMI', 'Section 80C', 'Old vs new regime', 'XIRR', 'P/E', 'DCF', 'DuPont', 'Mutual funds', 'Gold', 'USD / INR']

/** Public front page, shown to signed-out visitors before the sign-in form. */
export function Landing({ onSignIn, onGetStarted, canSignUp }: { onSignIn: () => void; onGetStarted: () => void; canSignUp: boolean }) {
  const root = useRef<HTMLDivElement>(null)
  useModeSetting() // re-render when the mode changes
  const night = document.documentElement.dataset.mode === 'night'
  const primary = canSignUp ? 'Get started free' : 'Sign in to start'
  const scrollTo = (id: string) => document.getElementById(id)?.scrollIntoView({ behavior: REDUCE ? 'auto' : 'smooth', block: 'start' })

  useEffect(() => { // fade sections in as they scroll into view
    const io = new IntersectionObserver((es) => es.forEach((e) => { if (e.isIntersecting) { e.target.classList.add('is-in'); io.unobserve(e.target) } }), { threshold: 0.12 })
    root.current?.querySelectorAll('.lp-reveal').forEach((el) => io.observe(el))
    return () => io.disconnect()
  }, [])

  const words = 'Your money questions, answered with'.split(' ')
  return <div className="lp" ref={root}>
    <header className="lp-nav">
      <BrandLogo className="lp-logo" />
      <nav aria-label="Page sections">
        <button type="button" onClick={() => scrollTo('lp-product')}>Product</button>
        <button type="button" onClick={() => scrollTo('lp-features')}>Features</button>
        <button type="button" onClick={() => scrollTo('lp-how')}>How it works</button>
        <button type="button" onClick={() => scrollTo('lp-trust')}>Trust</button>
      </nav>
      <div className="lp-nav-actions">
        <button type="button" className="lp-mode" onClick={() => setModeSetting(night ? 'light' : 'night')} aria-label={night ? 'Switch to light mode' : 'Switch to night mode'}>
          {night ? <Sun size={18} aria-hidden="true" /> : <Moon size={18} aria-hidden="true" />}
        </button>
        <button type="button" className="lp-btn lp-btn-ghost" onClick={onSignIn}>Log in</button>
        {canSignUp && <button type="button" className="lp-btn lp-btn-primary lp-hide-sm" onClick={onGetStarted}>Get started</button>}
      </div>
    </header>

    <main>
      <section className="lp-hero" onPointerMove={track} onPointerLeave={untrack}>
        <div className="lp-aurora" aria-hidden="true" />
        <div className="lp-grid-bg" aria-hidden="true" />
        <div className="lp-spot" aria-hidden="true" />
        <div className="lp-hero-in">
          <div className="lp-hero-copy">
            <p className="lp-pill"><i /> Chat · Voice · Talking avatar</p>
            <h1>
              {words.map((w, i) => <span className="lp-w" key={i} style={{ animationDelay: `${i * 0.07}s` }}>{w} </span>)}
              <span className="lp-w lp-grad" style={{ animationDelay: `${words.length * 0.07}s` }}>numbers you can check.</span>
            </h1>
            <p className="lp-lead">One assistant for personal finance, learning, markets and company research in India. It works from real data and your own profile, and it never gives buy or sell tips.</p>
            <div className="lp-cta">
              <button type="button" className="lp-btn lp-btn-primary lp-btn-lg lp-shine" onClick={onGetStarted}>{primary} <ArrowRight size={18} aria-hidden="true" /></button>
              <button type="button" className="lp-btn lp-btn-ghost lp-btn-lg" onClick={() => scrollTo('lp-product')}><Sparkles size={17} aria-hidden="true" /> See it in action</button>
            </div>
            <p className="lp-mini"><Check size={14} aria-hidden="true" /> Free to use <Check size={14} aria-hidden="true" /> Educational, not advice</p>
          </div>
          <div className="lp-stage">
            <span className="lp-chip c1" aria-hidden="true"><TrendingUp size={14} /> Nifty 50</span>
            <span className="lp-chip c2" aria-hidden="true"><Scale size={14} /> Old vs new regime</span>
            <span className="lp-chip c3" aria-hidden="true"><Mic size={14} /> Ask by voice</span>
            <div className="lp-tilt"><ChatDemo /></div>
          </div>
        </div>
      </section>

      <div className="lp-ticker" aria-hidden="true">
        <div>{[...TICKER, ...TICKER].map((t, i) => <span key={i}>{t}<i>✦</i></span>)}</div>
      </div>

      <section id="lp-product" className="lp-section lp-reveal">
        <p className="lp-kicker">Inside ARIA</p>
        <h2>See it <span className="lp-grad">at work</span></h2>
        <p className="lp-section-lead">Four screens from the app. Pick one, or let them play.</p>
        <Showcase />
      </section>

      <section id="lp-features" className="lp-section lp-reveal">
        <p className="lp-kicker">Four tools</p>
        <h2>One conversation. <span className="lp-grad">Every money question.</span></h2>
        <div className="lp-bento">
          {MODULES.map(({ icon: Icon, name, text, cls }) => <article key={name} className={`lp-tile lp-tile-${cls}`} onPointerMove={track} onPointerLeave={untrack}>
            <span className="lp-icon"><Icon size={22} aria-hidden="true" /></span>
            <h3>{name}</h3>
            <p>{text}</p>
            <div className="lp-tile-art" aria-hidden="true">
              {cls === 'fin' && <><div className="lp-donut" /><ul className="lp-budget"><li><i style={{ width: '50%' }} />Needs 50%</li><li><i style={{ width: '30%' }} />Wants 30%</li><li><i style={{ width: '20%' }} />Savings 20%</li></ul></>}
              {cls === 'tut' && <div className="lp-flip"><div><b>What is XIRR?</b><span>Tap to reveal</span></div><div><b>Mastery 3 / 5</b><span className="lp-mastery"><i /></span></div></div>}
              {cls === 'mkt' && <div className="lp-mini-bars">{[55, 72, 40, 86, 64, 50, 92, 70, 60, 80].map((h, i) => <i key={i} style={{ '--h': `${h}%`, animationDelay: `${i * 0.12}s` } as React.CSSProperties} />)}</div>}
              {cls === 'res' && <div className="lp-lines"><p><span /><em className="act">ACTUAL</em></p><p><span /><em className="calc">CALCULATED</em></p><p><span /><em className="est">ESTIMATE</em></p></div>}
            </div>
          </article>)}
        </div>
      </section>

      <section id="lp-how" className="lp-section lp-reveal">
        <p className="lp-kicker">Under the hood</p>
        <h2>How an answer is made</h2>
        <Story />
      </section>

      <section id="lp-trust" className="lp-trust lp-reveal">
        <div className="lp-trust-in">
          <p className="lp-kicker">Trust</p>
          <h2>Built to be <span className="lp-grad">trusted</span></h2>
          <div className="lp-stats">
            <div><b><Counter to={4} /></b><span>tools in one chat</span></div>
            <div><b><Counter to={1425} suffix="+" /></b><span>automated tests</span></div>
            <div><b><Counter to={0} /></b><span>buy or sell tips, ever</span></div>
            <div><b><Counter to={1} /></b><span>click to erase your data</span></div>
          </div>
          <div className="lp-trust-grid">
            {TRUST.map(({ icon: Icon, title, text }) => <article key={title}>
              <span className="lp-icon"><Icon size={22} aria-hidden="true" /></span>
              <h3>{title}</h3>
              <p>{text}</p>
            </article>)}
          </div>
        </div>
      </section>

      <section className="lp-final lp-reveal">
        <div className="lp-horizon" aria-hidden="true" />
        <h2>Start with <span className="lp-grad">one question</span></h2>
        <p>Sign in and ask ARIA about your budget, a concept or a company.</p>
        <button type="button" className="lp-btn lp-btn-primary lp-btn-lg lp-shine" onClick={onGetStarted}>{primary} <ArrowRight size={18} aria-hidden="true" /></button>
      </section>
    </main>

    <footer className="lp-footer">
      <BrandLogo className="lp-logo" />
      <p>ARIA is an educational project from IIIT Sri City. It explains financial information and does not give investment advice. Check important decisions with a SEBI-registered adviser.</p>
    </footer>
  </div>
}
