import type { ReactNode } from 'react'
import './Disclaimers.css'

export const DISCLAIMERS_UPDATED = '13 October 2026'

const SECTIONS: { id: string; short: string; title: string; body: ReactNode }[] = [
  {
    id: 'advice',
    short: 'Not advice',
    title: 'Not investment advice',
    body: (
      <>
        <p>
          Everything ARIA shows or says is general information for learning and research. It is not investment, tax, legal or accounting advice, and it is not
          a recommendation, offer or solicitation to buy, sell or hold any security, fund, coin, bond, derivative or other product.
        </p>
        <p>
          ARIA does not know your whole financial situation, your goals or your tolerance for loss. Words like &ldquo;BUY&rdquo;, &ldquo;HOLD&rdquo;,
          &ldquo;SELL&rdquo;, &ldquo;fair value&rdquo; or &ldquo;target&rdquo; are outputs of a model, shown so you can see how the numbers fit together. They
          are not personalised calls.
        </p>
      </>
    ),
  },
  {
    id: 'sebi',
    short: 'Not SEBI-registered',
    title: 'ARIA is not a SEBI-registered adviser, analyst, broker or distributor',
    body: (
      <>
        <p>
          ARIA is not registered with the Securities and Exchange Board of India (SEBI) as an investment adviser or a research analyst, and it is not a stock
          broker, mutual fund distributor, portfolio manager or any other regulated intermediary. It does not execute trades, hold your money or take orders.
        </p>
        <p>
          If you want advice that takes your circumstances into account, talk to a SEBI-registered investment adviser. You can check a registration on
          SEBI&rsquo;s website before you rely on anyone.
        </p>
      </>
    ),
  },
  {
    id: 'ai',
    short: 'AI can be wrong',
    title: 'AI-generated content can be wrong',
    body: (
      <>
        <p>
          Explanations, summaries, answers and the wording of research reports are written by large language models. These models can state things
          confidently that are false (&ldquo;hallucinations&rdquo;), misread a number, mix up two companies or instruments, or miss something important. ARIA
          checks its own figures against the data it fetched and tags where a number came from, but it cannot catch everything.
        </p>
        <ul>
          <li>
            <strong>Data</strong> means fetched from a named source. <strong>Calculated</strong> means worked out by ARIA&rsquo;s code from that data.{' '}
            <strong>AI</strong> means wording or interpretation written by a language model.
          </li>
          <li>Check anything that matters against the company&rsquo;s filings, the fund&rsquo;s factsheet or the exchange before you act on it.</li>
        </ul>
      </>
    ),
  },
  {
    id: 'models',
    short: 'Forecast limits',
    title: 'Model and forecast limitations, with ARIA’s own measured results',
    body: (
      <>
        <p>
          ARIA tests its forecasts against what companies actually reported later. The results are modest, and you should read them before you trust any
          projection:
        </p>
        <ul>
          <li>
            The base-case revenue forecast typically missed the reported figure by about <strong>10% at one year</strong> and about{' '}
            <strong>25% at five years</strong>.
          </li>
          <li>
            The range between the bear and bull cases contained the reported figure only about <strong>8&ndash;16% of the time</strong>. Treat the range as a
            rough scenario spread, not as a confidence interval.
          </li>
          <li>
            BUY / HOLD / SELL calls showed <strong>no robust edge</strong> over simple baselines in the historical test.
          </li>
        </ul>
        <p>
          The full wording, method and tables are in the &ldquo;Quantitative forecast validation&rdquo; section of every research report and in the ARIA
          validation summary. Valuation models also depend heavily on assumptions (growth, margins, discount rate) that are uncertain and that you may
          reasonably disagree with.
        </p>
      </>
    ),
  },
  {
    id: 'past',
    short: 'Past performance',
    title: 'Past performance and backtests do not predict the future',
    body: (
      <p>
        Charts, historical returns, SIP simulations and backtests show what happened in the past, with the benefit of hindsight. They ignore taxes, exit loads,
        brokerage, slippage and changes in fund managers or rules. Markets change, and a pattern that worked before can stop working or reverse.
      </p>
    ),
  },
  {
    id: 'data',
    short: 'Delayed data',
    title: 'Market data may be delayed or incomplete',
    body: (
      <>
        <p>
          Prices and other data come from free third-party sources and are often delayed (usually about 15 minutes, sometimes longer), may be missing, rounded
          or stale, and can contain errors. A &ldquo;stale&rdquo; label means ARIA could not refresh and is showing the last value it had. Do not use ARIA for
          time-critical decisions or to place orders; confirm the live price with your broker or the exchange.
        </p>
        <p>Mutual fund NAVs are published once a day, so they trail the market by design.</p>
      </>
    ),
  },
  {
    id: 'products',
    short: 'Product risks',
    title: 'Risks specific to each kind of instrument',
    body: (
      <ul>
        <li>
          <strong>Stocks and ETFs:</strong> prices can fall sharply and you can lose the whole amount invested. ETFs can trade away from the value of what they
          hold and can be thinly traded.
        </li>
        <li>
          <strong>Mutual funds:</strong> mutual fund investments are subject to market risks. Read all scheme-related documents carefully. Returns are not
          guaranteed, and a fund&rsquo;s past returns say little about the next few years.
        </li>
        <li>
          <strong>SIP:</strong> a systematic investment plan is a way of investing regularly, not a way of avoiding loss. A SIP does not guarantee returns or
          protect against a falling market. ARIA&rsquo;s SIP figures are simulations on historical prices.
        </li>
        <li>
          <strong>Bonds and debt funds:</strong> prices fall when interest rates rise (interest-rate risk), the issuer may delay or fail to pay (credit risk),
          and some bonds are hard to sell before maturity (liquidity risk).
        </li>
        <li>
          <strong>Crypto assets:</strong> largely unregulated in India, extremely volatile, open to fraud, hacks and loss of access, and taxed heavily. You can
          lose everything.
        </li>
        <li>
          <strong>Commodities and currencies:</strong> prices are driven by global events and can move fast; currency moves can add to or wipe out returns on
          foreign assets.
        </li>
        <li>
          <strong>Derivatives (futures and options):</strong> these are leveraged and most individual traders lose money. ARIA does not suggest derivative
          trades.
        </li>
        <li>
          <strong>Indices</strong> cannot be bought directly; you invest through products that track them, which have their own costs and tracking errors.
        </li>
      </ul>
    ),
  },
  {
    id: 'tax',
    short: 'Taxes',
    title: 'Taxes',
    body: (
      <p>
        Tax rules differ by instrument, holding period and your income, and they change often. ARIA&rsquo;s tax explanations are general and may be out of
        date. Returns shown in ARIA are usually before tax. Speak to a qualified tax professional before you decide.
      </p>
    ),
  },
  {
    id: 'responsibility',
    short: 'Your responsibility',
    title: 'Your decisions and responsibility',
    body: (
      <p>
        You alone are responsible for your financial decisions. Do your own research, only invest money you can afford to lose, diversify, and keep an
        emergency fund. To the fullest extent the law allows, ARIA and its makers are not liable for any loss or damage that results from using, or being unable
        to use, ARIA or the information in it.
      </p>
    ),
  },
  {
    id: 'privacy',
    short: 'Privacy and data',
    title: 'Privacy and data',
    body: (
      <ul>
        <li>
          <strong>On this device:</strong> your theme and colour mode, watchlists, onboarding state and a random device id (ARIA has no accounts and no login) are
          kept in your browser&rsquo;s storage. The device id is how your saved reports and profile are found again.
        </li>
        <li>
          <strong>On the ARIA server:</strong> your chat history for the session, the financial profile you enter, any statements you upload, your progress and
          your saved research reports are stored under that device id. You can clear the profile and the style ARIA learned about you in Settings and Your
          Profile. ARIA does not sell this data or share it for advertising.
        </li>
        <li>
          <strong>AI providers:</strong> to answer, ARIA sends your question and the relevant context (for example market data, or facts from your profile when
          you ask a personal question) to third-party language-model providers such as Groq and Google Gemini. Do not type passwords, account numbers or other
          secrets into ARIA.
        </li>
        <li>
          <strong>Voice:</strong> if you use the microphone, the recording is sent to ARIA&rsquo;s server and turned into text by a speech-to-text model
          there; the temporary audio file is deleted afterwards and recordings are not kept. Spoken replies are generated from the reply text, which may be
          sent to a text-to-speech service.
        </li>
        <li>
          <strong>Avatar mode:</strong> the live video avatar is provided by Tavus; using it sends your conversation to Tavus.
        </li>
      </ul>
    ),
  },
  {
    id: 'sources',
    short: 'Data sources',
    title: 'Third-party data sources and attribution',
    body: (
      <>
        <p>
          ARIA uses free public sources, including Yahoo Finance (prices and charts), Screener.in (company financials), AMFI and public fund-data services
          (mutual fund NAVs), exchange and company filings, and Google News and publisher RSS feeds (headlines). Trademarks and data belong to their owners.
          ARIA is not endorsed by, or affiliated with, any of them or with any exchange. Their terms apply to the data, and availability or accuracy is not
          guaranteed.
        </p>
        <p>Charts are drawn with the open-source TradingView Lightweight Charts library.</p>
      </>
    ),
  },
  {
    id: 'contact',
    short: 'Contact',
    title: 'Contact and feedback',
    body: (
      <p>
        Found a wrong number, a confusing answer or something that looks unsafe? Please tell the person or team who gave you access to ARIA, or report it where
        you received it (for example the project&rsquo;s issue tracker), and include the instrument, the page and the time. Corrections to this page are welcome
        in the same way.
      </p>
    ),
  },
]

export function DisclaimersPage() {
  const jump = (id: string) =>
    document
      .getElementById(`dc-${id}`)
      ?.scrollIntoView({ behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start' })
  return (
    <article className="dc" aria-labelledby="dc-title">
      <header>
        <h1 id="dc-title">Disclaimers</h1>
        <p className="dc-updated">Last updated {DISCLAIMERS_UPDATED}</p>
      </header>
      <p className="dc-lead" role="note">
        ARIA is an AI research and education tool, not a SEBI-registered adviser. Nothing here is investment advice. Markets are risky and you can lose money.
        Please read this page once; it is short and written to be understood.
      </p>
      <nav aria-label="On this page">
        <ul className="dc-toc">
          {SECTIONS.map((s) => (
            <li key={s.id}>
              <button type="button" onClick={() => jump(s.id)}>
                {s.short}
              </button>
            </li>
          ))}
        </ul>
      </nav>
      {SECTIONS.map((s) => (
        <section key={s.id} id={`dc-${s.id}`} aria-labelledby={`dc-h-${s.id}`}>
          <h2 id={`dc-h-${s.id}`}>{s.title}</h2>
          {s.body}
        </section>
      ))}
      <p className="dc-foot">The one-line version of this page appears at the top of every screen and at the top of every exported report.</p>
    </article>
  )
}
