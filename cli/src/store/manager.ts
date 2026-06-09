import type { StorageMode, Store } from './store'
import type { TokenStore } from './token-store'
import { join } from 'node:path'
import { resolveCacheDir, resolveConfigDir } from './dir'
import { YamlStore } from './store'
import { FileTokenStore, KeychainTokenStore } from './token-store'

export const CACHE_APP_INFO = 'app-info'
export const CACHE_NUDGE = 'nudge'
const HOSTS_FILE = 'hosts.yml'
const TOKENS_FILE = 'tokens.yml'
export const CONFIG_FILE_NAME = 'config.yml'

const KEYRING_SERVICE = 'difyctl'

function getStore(filePath: string): YamlStore {
  return new YamlStore(filePath)
}

export function cachePath(cacheDir: string, name: string): string {
  return join(cacheDir, `${name}.yml`)
}

export function getConfigurationStore(): YamlStore {
  return getStore(join(resolveConfigDir(), CONFIG_FILE_NAME))
}

export function getCache(cacheName: string): Store {
  return getStore(cachePath(resolveCacheDir(), cacheName))
}

export function getHostStore(): YamlStore {
  return getStore(join(resolveConfigDir(), HOSTS_FILE))
}

const PROBE_HOST = '__difyctl_probe__'
const PROBE_EMAIL = '__difyctl_probe__'
const PROBE_VALUE = 'probe-v1'

export type GetTokenStoreOptions = {
  readonly factory?: {
    readonly keyring?: () => TokenStore
    readonly file?: () => TokenStore
  }
}

/**
 * Single entry point for the credential store. Probes the OS keyring; if it
 * round-trips a value, returns the keychain-backed store. Otherwise falls
 * back to the YAML file at `<configDir>/tokens.yml`. Both implementations
 * satisfy the `TokenStore` interface, so callers interact uniformly.
 *
 * Business logic should always obtain the token store through this factory
 * rather than constructing one directly.
 */
export function getTokenStore(opts: GetTokenStoreOptions = {}): { store: TokenStore, mode: StorageMode } {
  const fileFactory = opts.factory?.file ?? (() => new FileTokenStore(join(resolveConfigDir(), TOKENS_FILE)))
  const keyringFactory = opts.factory?.keyring ?? (() => new KeychainTokenStore(KEYRING_SERVICE))
  try {
    const k = keyringFactory()
    k.write(PROBE_HOST, PROBE_EMAIL, PROBE_VALUE)
    const got = k.read(PROBE_HOST, PROBE_EMAIL)
    k.remove(PROBE_HOST, PROBE_EMAIL)
    if (got !== PROBE_VALUE)
      throw new Error('keyring round-trip mismatch')
    return { store: k, mode: 'keychain' }
  }
  catch {
    return { store: fileFactory(), mode: 'file' }
  }
}
