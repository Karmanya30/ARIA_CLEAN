import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

// Deliberately not wrapped in <StrictMode>: it double-invokes effects in
// dev to help find bugs, which is fine for most components but not for
// TavusPanel's effect (starts a real, paid Tavus conversation) -- the
// double-invoke would create one, immediately end it via the fake-unmount
// cleanup, and never create a replacement, leaving a dead embed and a
// wasted API call every time. Not worth the dev-time diagnostic value
// here versus the cost/correctness risk.
createRoot(document.getElementById('root')!).render(<App />)
