import { describe, expect, it, vi } from 'vitest'
import { act, renderHook } from '@testing-library/react'
import { useTheme } from './useTheme'

function mockMatchMedia(matches: boolean) {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    configurable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches,
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  })
}

describe('useTheme', () => {
  it('defaults to light when there is no stored preference and the system prefers light', () => {
    window.localStorage.clear()
    mockMatchMedia(false)

    const { result } = renderHook(() => useTheme())

    expect(result.current.theme).toBe('light')
    expect(document.documentElement.classList.contains('dark')).toBe(false)
  })

  it('defaults to dark when there is no stored preference and the system prefers dark', () => {
    window.localStorage.clear()
    mockMatchMedia(true)

    const { result } = renderHook(() => useTheme())

    expect(result.current.theme).toBe('dark')
    expect(document.documentElement.classList.contains('dark')).toBe(true)
  })

  it('prefers a stored localStorage value over the system preference', () => {
    window.localStorage.setItem('isItWorthIt.theme', 'dark')
    mockMatchMedia(false)

    const { result } = renderHook(() => useTheme())

    expect(result.current.theme).toBe('dark')
  })

  it('toggleTheme flips the theme, updates the dark class, and persists to localStorage', () => {
    window.localStorage.clear()
    mockMatchMedia(false)

    const { result } = renderHook(() => useTheme())
    expect(result.current.theme).toBe('light')

    act(() => {
      result.current.toggleTheme()
    })

    expect(result.current.theme).toBe('dark')
    expect(document.documentElement.classList.contains('dark')).toBe(true)
    expect(window.localStorage.getItem('isItWorthIt.theme')).toBe('dark')
  })
})
