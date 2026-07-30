import '@testing-library/jest-dom/vitest'
import { afterEach, beforeEach, vi } from 'vitest'

beforeEach(() => {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    configurable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  })
})

// RTL's cleanup() unmounts components but never touches document.documentElement or
// localStorage — reset both globally so test order and cross-file state can't matter.
afterEach(() => {
  document.documentElement.classList.remove('dark')
  window.localStorage.clear()
})
