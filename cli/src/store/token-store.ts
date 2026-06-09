import { Entry } from '@napi-rs/keyring'
import { YamlStore } from './store'

/**
 * Credential store keyed by an opaque (host, email) pair. Unlike the generic
 * dotted-key `Store`, host and email are never split — they are literal map
 * keys (file) or part of a flat entry name (keychain). `read` returns '' when
 * a credential is absent.
 */
export type TokenStore = {
  read: (host: string, email: string) => string
  write: (host: string, email: string, bearer: string) => void
  remove: (host: string, email: string) => void
}

const DOC_VERSION = 1

type TokenDoc = {
  version?: number
  tokens?: Record<string, Record<string, string>>
}

export class FileTokenStore implements TokenStore {
  private readonly store: YamlStore

  constructor(filePath: string) {
    this.store = new YamlStore(filePath)
  }

  read(host: string, email: string): string {
    const doc = this.store.getTyped<TokenDoc>()
    if (doc === null || doc.version !== DOC_VERSION)
      return ''
    return doc.tokens?.[host]?.[email] ?? ''
  }

  write(host: string, email: string, bearer: string): void {
    const doc = this.load()
    const hostMap = doc.tokens[host] ?? {}
    hostMap[email] = bearer
    doc.tokens[host] = hostMap
    this.store.setTyped(doc)
  }

  remove(host: string, email: string): void {
    const doc = this.store.getTyped<TokenDoc>()
    if (doc === null || doc.version !== DOC_VERSION)
      return
    const tokens = doc.tokens ?? {}
    const hostMap = tokens[host]
    if (hostMap === undefined || !(email in hostMap))
      return
    delete hostMap[email]
    if (Object.keys(hostMap).length === 0)
      delete tokens[host]
    this.store.setTyped({ version: DOC_VERSION, tokens })
  }

  private load(): { version: number, tokens: Record<string, Record<string, string>> } {
    const doc = this.store.getTyped<TokenDoc>()
    if (doc === null || doc.version !== DOC_VERSION)
      return { version: DOC_VERSION, tokens: {} }
    return { version: DOC_VERSION, tokens: doc.tokens ?? {} }
  }
}

/**
 * One OS-keyring entry per (host, email). The entry name is intentionally
 * identical to the legacy `tokens.<host>.<email>` key so existing keychain
 * credentials keep working without a re-login. The value is the bearer stored
 * exactly as the legacy `KeyringBasedStore` stored it (JSON-encoded string).
 */
export class KeychainTokenStore implements TokenStore {
  private readonly service: string

  constructor(service: string) {
    this.service = service
  }

  read(host: string, email: string): string {
    try {
      const v = new Entry(this.service, entryName(host, email)).getPassword()
      if (v === null || v === undefined || v === '')
        return ''
      return JSON.parse(v) as string
    }
    catch {
      return ''
    }
  }

  write(host: string, email: string, bearer: string): void {
    new Entry(this.service, entryName(host, email)).setPassword(JSON.stringify(bearer))
  }

  remove(host: string, email: string): void {
    try {
      new Entry(this.service, entryName(host, email)).deletePassword()
    }
    catch { /* missing entry is fine */ }
  }
}

function entryName(host: string, email: string): string {
  return `tokens.${host}.${email}`
}
