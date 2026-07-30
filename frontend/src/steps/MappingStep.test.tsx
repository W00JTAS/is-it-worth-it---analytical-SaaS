import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MappingStep } from './MappingStep'
import * as client from '../api/client'
import type { CsvPreview } from '../api/types'

const FILE = new File(['nazwa;cena'], 'catalog.csv', { type: 'text/csv' })

const PREVIEW: CsvPreview = {
  headers: ['Nazwa', 'Cena hurtowa', 'EAN', 'Kategoria', 'SKU'],
  mapping: { name: 'Nazwa', wholesale_price: 'Cena hurtowa', ean: 'EAN', category: 'Kategoria', sku: 'SKU' },
  sample_rows: [
    { Nazwa: 'Produkt A', 'Cena hurtowa': '10,00', EAN: '5901234123457', Kategoria: 'Elektronika', SKU: 'A1' },
  ],
  total_rows: 1,
  parsed_count: 1,
  warnings: [],
  warning_count: 0,
}

beforeEach(() => {
  vi.restoreAllMocks()
})
afterEach(() => {
  vi.restoreAllMocks()
})

describe('MappingStep', () => {
  it('loads the preview on mount and pre-selects the auto-detected columns', async () => {
    vi.spyOn(client, 'getCsvPreview').mockResolvedValue(PREVIEW)
    render(<MappingStep file={FILE} onConfirmed={vi.fn()} />)

    await screen.findByText('1 / 1 wierszy sparsowanych poprawnie')
    expect(screen.getByLabelText('Nazwa')).toHaveValue('Nazwa')
    expect(screen.getByLabelText('Cena hurtowa')).toHaveValue('Cena hurtowa')
    expect(screen.getByLabelText('EAN')).toHaveValue('EAN')
    expect(screen.getByLabelText('Kategoria')).toHaveValue('Kategoria')
    expect(screen.getByLabelText('SKU (opcjonalne)')).toHaveValue('SKU')
  })

  it('shows the sample rows table', async () => {
    vi.spyOn(client, 'getCsvPreview').mockResolvedValue(PREVIEW)
    render(<MappingStep file={FILE} onConfirmed={vi.fn()} />)

    await screen.findByText('Produkt A')
    expect(screen.getByText('5901234123457')).toBeInTheDocument()
  })

  it('shows truncated warnings with a remaining count', async () => {
    vi.spyOn(client, 'getCsvPreview').mockResolvedValue({
      ...PREVIEW,
      parsed_count: 3,
      total_rows: 25,
      warnings: ['Row 2: missing name, skipped'],
      warning_count: 22,
    })
    render(<MappingStep file={FILE} onConfirmed={vi.fn()} />)

    await screen.findByText('Row 2: missing name, skipped')
    expect(screen.getByText('...i 21 więcej')).toBeInTheDocument()
  })

  it('re-fetches the preview with the edited mapping when Odśwież podgląd is clicked', async () => {
    const spy = vi.spyOn(client, 'getCsvPreview').mockResolvedValue(PREVIEW)
    render(<MappingStep file={FILE} onConfirmed={vi.fn()} />)
    await screen.findByText('1 / 1 wierszy sparsowanych poprawnie')

    await userEvent.selectOptions(screen.getByLabelText('EAN'), 'Kategoria')
    await userEvent.click(screen.getByRole('button', { name: 'Odśwież podgląd' }))

    await waitFor(() =>
      expect(spy).toHaveBeenLastCalledWith(FILE, {
        name: 'Nazwa', wholesale_price: 'Cena hurtowa', ean: 'Kategoria', category: 'Kategoria', sku: 'SKU',
      }),
    )
  })

  it('disables Dalej until all required fields are mapped, and confirms the current mapping when clicked', async () => {
    vi.spyOn(client, 'getCsvPreview').mockResolvedValue({
      ...PREVIEW,
      mapping: { name: 'Nazwa', wholesale_price: null, ean: 'EAN', category: 'Kategoria', sku: null },
    })
    const onConfirmed = vi.fn()
    render(<MappingStep file={FILE} onConfirmed={onConfirmed} />)
    await screen.findByText('Produkt A')

    expect(screen.getByRole('button', { name: 'Dalej' })).toBeDisabled()

    await userEvent.selectOptions(screen.getByLabelText('Cena hurtowa'), 'Cena hurtowa')
    expect(screen.getByRole('button', { name: 'Dalej' })).toBeEnabled()

    await userEvent.click(screen.getByRole('button', { name: 'Dalej' }))

    expect(onConfirmed).toHaveBeenCalledWith({
      name: 'Nazwa', wholesale_price: 'Cena hurtowa', ean: 'EAN', category: 'Kategoria', sku: null,
    })
  })

  it('shows the API error message when the preview request fails', async () => {
    const { ApiError } = await import('../api/types')
    vi.spyOn(client, 'getCsvPreview').mockRejectedValue(new ApiError('CSV file has no header row', 400))
    render(<MappingStep file={FILE} onConfirmed={vi.fn()} />)

    expect(await screen.findByText('CSV file has no header row')).toBeInTheDocument()
  })
})
