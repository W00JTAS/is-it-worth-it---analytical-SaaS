import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { UploadStep } from './UploadStep'

describe('UploadStep', () => {
  it('disables the next button until a file is chosen', async () => {
    render(<UploadStep onFileSelected={vi.fn()} />)

    expect(screen.getByRole('button', { name: 'Dalej' })).toBeDisabled()

    const file = new File(['nazwa;cena\nA;10,00'], 'catalog.csv', { type: 'text/csv' })
    const input = screen.getByLabelText(/plik CSV/i)
    await userEvent.upload(input, file)

    expect(screen.getByRole('button', { name: 'Dalej' })).toBeEnabled()
  })

  it('calls onFileSelected with the chosen file when Dalej is clicked', async () => {
    const onFileSelected = vi.fn()
    render(<UploadStep onFileSelected={onFileSelected} />)

    const file = new File(['nazwa;cena\nA;10,00'], 'catalog.csv', { type: 'text/csv' })
    const input = screen.getByLabelText(/plik CSV/i)
    await userEvent.upload(input, file)
    await userEvent.click(screen.getByRole('button', { name: 'Dalej' }))

    expect(onFileSelected).toHaveBeenCalledWith(file)
  })
})
