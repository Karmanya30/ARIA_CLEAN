import { createContext, useContext, type ReactNode } from 'react'

/** The signed-in account's details (email, sign out, connect Google), built by AuthGate and shown in Settings.
 * null when there is no account to show (private mode). */
export const AccountPanelContext = createContext<ReactNode>(null)
export const useAccountPanel = () => useContext(AccountPanelContext)
