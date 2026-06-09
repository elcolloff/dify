import type { TokenStore } from './token-store'
import { describe, expect, it, vi } from 'vitest'
import { getTokenStore } from './manager'

function memStore(label: string): TokenStore & { _label: string } {
  const map = new Map<string, string>()
  const k = (h: string, e: string): string => `${h} ${e}`
  return {
    _label: label,
    read(host: string, email: string): string {
      return map.get(k(host, email)) ?? ''
    },
    write(host: string, email: string, bearer: string): void {
      map.set(k(host, email), bearer)
    },
    remove(host: string, email: string): void {
      map.delete(k(host, email))
    },
  }
}

describe('getTokenStore', () => {
  it('returns keychain store when probe succeeds', () => {
    const k = memStore('keyring')
    const f = memStore('file')
    const result = getTokenStore({
      factory: { keyring: () => k, file: () => f },
    })
    expect(result.mode).toBe('keychain')
    expect(result.store).toBe(k)
  })

  it('falls back to file when keyring set throws', () => {
    const k = memStore('keyring')
    const f = memStore('file')
    k.write = vi.fn(() => {
      throw new Error('locked')
    })
    const result = getTokenStore({
      factory: { keyring: () => k, file: () => f },
    })
    expect(result.mode).toBe('file')
    expect(result.store).toBe(f)
  })

  it('falls back to file when probe round-trip mismatches', () => {
    const k = memStore('keyring')
    const f = memStore('file')
    k.read = vi.fn(() => 'something-else') as TokenStore['read']
    const result = getTokenStore({
      factory: { keyring: () => k, file: () => f },
    })
    expect(result.mode).toBe('file')
    expect(result.store).toBe(f)
  })

  it('falls back to file when keyring constructor throws', () => {
    const f = memStore('file')
    const result = getTokenStore({
      factory: {
        keyring: () => { throw new Error('no backend') },
        file: () => f,
      },
    })
    expect(result.mode).toBe('file')
    expect(result.store).toBe(f)
  })

  it('cleans up probe entry after successful probe', () => {
    const k = memStore('keyring')
    const f = memStore('file')
    getTokenStore({
      factory: { keyring: () => k, file: () => f },
    })
    expect(k.read('__difyctl_probe__', '__difyctl_probe__')).toBe('')
  })
})
