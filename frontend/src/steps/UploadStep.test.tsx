import { StrictMode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { UploadStep } from './UploadStep'

describe('UploadStep', () => {
  it('disables the next button until a file is chosen', async () => {
    render(<UploadStep onFileSelected={vi.fn()} onSampleSelected={vi.fn()} />)

    expect(screen.getByRole('button', { name: 'Continue' })).toBeDisabled()

    const file = new File(['nazwa;cena\nA;10,00'], 'catalog.csv', { type: 'text/csv' })
    const input = screen.getByLabelText(/wholesaler CSV/i)
    await userEvent.upload(input, file)

    expect(screen.getByRole('button', { name: 'Continue' })).toBeEnabled()
  })

  it('calls onFileSelected with the chosen file when Continue is clicked', async () => {
    const onFileSelected = vi.fn()
    render(<UploadStep onFileSelected={onFileSelected} onSampleSelected={vi.fn()} />)

    const file = new File(['nazwa;cena\nA;10,00'], 'catalog.csv', { type: 'text/csv' })
    const input = screen.getByLabelText(/wholesaler CSV/i)
    await userEvent.upload(input, file)
    await userEvent.click(screen.getByRole('button', { name: 'Continue' }))

    expect(onFileSelected).toHaveBeenCalledWith(file)
  })
})

describe('UploadStep sample-trial cards', () => {
  const originalFetch = globalThis.fetch

  afterEach(() => {
    globalThis.fetch = originalFetch
  })

  it('fetches the bundled CSV and calls onSampleSelected with a File and the fixed mapping', async () => {
    const csvBody = '"SKU";"ean";"nazwa";"kategoria";"cena"\n"A1";"5901234123457";"Czajnik";"AGD";"99.00"\n'
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      blob: () => Promise.resolve(new Blob([csvBody], { type: 'text/csv' })),
    }) as unknown as typeof fetch
    const onSampleSelected = vi.fn()
    render(<UploadStep onFileSelected={vi.fn()} onSampleSelected={onSampleSelected} />)

    await userEvent.click(screen.getByRole('button', { name: /kitchen/i }))

    await waitFor(() => expect(onSampleSelected).toHaveBeenCalledTimes(1))
    expect(globalThis.fetch).toHaveBeenCalledWith('/samples/kuchnia.csv')
    const [file, mapping] = onSampleSelected.mock.calls[0]
    expect(file).toBeInstanceOf(File)
    expect(file.name).toBe('kuchnia.csv')
    expect(mapping).toEqual({
      name: 'nazwa', wholesale_price: 'cena', ean: 'ean', category: 'kategoria', sku: 'SKU',
    })
  })

  it('renders all three category cards', () => {
    render(<UploadStep onFileSelected={vi.fn()} onSampleSelected={vi.fn()} />)

    expect(screen.getByRole('button', { name: /kitchen/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /toys/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /electronics/i })).toBeInTheDocument()
  })

  // --- Final whole-branch review, Fix 1: unmount guard --------------------

  it('does not call onSampleSelected if the component unmounts before the sample fetch resolves', async () => {
    let resolveFetch: (value: { ok: boolean; blob: () => Promise<Blob> }) => void = () => {}
    globalThis.fetch = vi.fn().mockReturnValue(
      new Promise((resolve) => { resolveFetch = resolve }),
    ) as unknown as typeof fetch
    const onSampleSelected = vi.fn()
    const { unmount } = render(<UploadStep onFileSelected={vi.fn()} onSampleSelected={onSampleSelected} />)

    await userEvent.click(screen.getByRole('button', { name: /kitchen/i }))

    unmount()

    const csvBody = '"SKU";"ean";"nazwa";"kategoria";"cena"\n"A1";"5901234123457";"Czajnik";"AGD";"99.00"\n'
    resolveFetch({ ok: true, blob: () => Promise.resolve(new Blob([csvBody], { type: 'text/csv' })) })
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(onSampleSelected).not.toHaveBeenCalled()
  })

  // --- Regression: StrictMode's dev-mode double-effect-invoke must not ----
  // --- permanently disarm the unmount guard added by the fix above --------

  it('completes a sample fetch normally under StrictMode (double-invoked effects)', async () => {
    const csvBody = '"SKU";"ean";"nazwa";"kategoria";"cena"\n"A1";"5901234123457";"Czajnik";"AGD";"99.00"\n'
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      blob: () => Promise.resolve(new Blob([csvBody], { type: 'text/csv' })),
    }) as unknown as typeof fetch
    const onSampleSelected = vi.fn()
    render(
      <StrictMode>
        <UploadStep onFileSelected={vi.fn()} onSampleSelected={onSampleSelected} />
      </StrictMode>,
    )

    await userEvent.click(screen.getByRole('button', { name: /kitchen/i }))

    // Without resetting isMountedRef.current at the top of the effect,
    // StrictMode's simulated mount->cleanup->mount leaves the guard
    // permanently tripped even though the component is genuinely mounted --
    // onSampleSelected would never fire and the button would stay on
    // "Wczytywanie…" forever.
    await waitFor(() => expect(onSampleSelected).toHaveBeenCalledTimes(1))
    expect(screen.getByRole('button', { name: /kitchen/i })).not.toHaveTextContent('Wczytywanie')
  })
})
