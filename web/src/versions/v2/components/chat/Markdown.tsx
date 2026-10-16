import ReactMarkdown from 'react-markdown'
import './Markdown.css'

// LLM narration occasionally wraps a whole section in "** text **" -- note
// the whitespace hugging the markers. CommonMark's flanking-delimiter rule
// requires no space right inside ** for it to open/close emphasis, so that
// form isn't valid bold and react-markdown correctly leaves it as literal
// asterisks. Trim the inner whitespace so those pairs parse as real bold;
// any marker left without a partner after that is stray and gets dropped
// rather than shown as a bare "**".
function normalizeEmphasis(text: string): string {
  const parts = text.split('**')
  const markerCount = parts.length - 1
  const pairedThrough = markerCount - (markerCount % 2) // highest marker index completing a pair
  return parts
    .map((part, i) => {
      // odd-indexed parts sit between two markers; they're only a real
      // pair if a closing marker actually exists (i within pairedThrough)
      if (i % 2 === 1 && i <= pairedThrough - 1) {
        const trimmed = part.trim()
        return trimmed ? `**${trimmed}**` : ''
      }
      return part
    })
    .join('')
}

// LLM narration occasionally emits markdown emphasis (**bold**, *italic*,
// lists) even though the TAXAL/section prompts don't ask for it. The old
// Streamlit UI rendered this via st.markdown() natively; plain React <div>
// text left the raw ** markers visible. This renders the same subset
// (no raw HTML, no images) inline wherever response text is shown.
export function Markdown({ text }: { text: string }) {
  return (
    <div className="markdown-body">
      <ReactMarkdown>{normalizeEmphasis(text)}</ReactMarkdown>
    </div>
  )
}
