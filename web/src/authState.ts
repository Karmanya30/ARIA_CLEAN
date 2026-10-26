let authenticatedOwner: string | null = null
export const accountOwner = () => authenticatedOwner
export function setAccountOwner(id: string | null) { authenticatedOwner = id }
