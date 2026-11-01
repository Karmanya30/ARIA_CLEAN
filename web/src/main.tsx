import { createRoot } from 'react-dom/client'
import './index.css'
import { VersionRouter } from './VersionRouter.tsx'
import { AuthGate } from './AuthGate'

createRoot(document.getElementById('root')!).render(<AuthGate><VersionRouter /></AuthGate>)
