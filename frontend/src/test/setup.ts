import '@testing-library/jest-dom/vitest'

import { cleanup } from '@testing-library/react'
import { afterAll, afterEach, beforeAll } from 'vitest'

import { server } from './server'

// Node >= 22 引入的全局 localStorage 在 jsdom 环境下不提供完整的 Storage 方法
// （getItem/clear 等缺失，导致请求拦截器读 token 抛错）。此处检测并降级为
// 内存实现，保证测试在 Node 20/22/25 等各版本下行为一致。
function ensureWebStorage(): void {
  const shimStorage = (): Storage => {
    const store = new Map<string, string>()
    return {
      get length() {
        return store.size
      },
      clear(): void {
        store.clear()
      },
      getItem(key: string): string | null {
        return store.get(key) ?? null
      },
      key(index: number): string | null {
        return [...store.keys()][index] ?? null
      },
      removeItem(key: string): void {
        store.delete(key)
      },
      setItem(key: string, value: string): void {
        store.set(key, String(value))
      },
    }
  }

  const install = (name: 'localStorage' | 'sessionStorage'): void => {
    const current = globalThis[name]
    if (current && typeof current.clear === 'function') {
      return
    }
    const shim = shimStorage()
    Object.defineProperty(globalThis, name, {
      value: shim,
      configurable: true,
      writable: true,
    })
    if (typeof window !== 'undefined' && window[name] !== shim) {
      Object.defineProperty(window, name, { value: shim, configurable: true, writable: true })
    }
  }

  install('localStorage')
  install('sessionStorage')
}

ensureWebStorage()

// 未声明的请求一律报错：逼迫每个测试显式声明依赖的后端契约（ADR-0016 Phase 3）。
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => {
  cleanup()
  server.resetHandlers()
})
afterAll(() => server.close())
