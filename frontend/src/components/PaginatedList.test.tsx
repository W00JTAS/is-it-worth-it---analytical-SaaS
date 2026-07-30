import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { PaginatedList } from './PaginatedList'

describe('PaginatedList', () => {
  it('renders only the first page of items when there are more than pageSize', () => {
    const items = Array.from({ length: 25 }, (_, i) => `item-${i + 1}`)
    render(<PaginatedList items={items} pageSize={10} renderItem={(item) => <span>{item}</span>} />)

    expect(screen.getByText('item-1')).toBeInTheDocument()
    expect(screen.getByText('item-10')).toBeInTheDocument()
    expect(screen.queryByText('item-11')).not.toBeInTheDocument()
  })

  it('hides pagination controls when everything fits on one page', () => {
    const items = ['a', 'b', 'c']
    render(<PaginatedList items={items} pageSize={10} renderItem={(item) => <span>{item}</span>} />)

    expect(screen.queryByRole('navigation', { name: /pagination/i })).not.toBeInTheDocument()
  })

  it('shows pagination controls and navigates to the next page', async () => {
    const user = userEvent.setup()
    const items = Array.from({ length: 25 }, (_, i) => `item-${i + 1}`)
    render(<PaginatedList items={items} pageSize={10} renderItem={(item) => <span>{item}</span>} />)

    expect(screen.getByRole('navigation', { name: /pagination/i })).toBeInTheDocument()

    await user.click(screen.getByLabelText('Go to next page'))

    expect(screen.getByText('item-11')).toBeInTheDocument()
    expect(screen.getByText('item-20')).toBeInTheDocument()
    expect(screen.queryByText('item-1')).not.toBeInTheDocument()
  })

  it('disables Previous on the first page and Next on the last page', async () => {
    const user = userEvent.setup()
    const items = Array.from({ length: 15 }, (_, i) => `item-${i + 1}`)
    render(<PaginatedList items={items} pageSize={10} renderItem={(item) => <span>{item}</span>} />)

    expect(screen.getByLabelText('Go to previous page')).toHaveAttribute('aria-disabled', 'true')

    await user.click(screen.getByLabelText('Go to next page'))

    expect(screen.getByText('item-15')).toBeInTheDocument()
    expect(screen.getByLabelText('Go to next page')).toHaveAttribute('aria-disabled', 'true')
  })

  it('resets to page 1 when the items array changes', async () => {
    const user = userEvent.setup()
    const itemsA = Array.from({ length: 25 }, (_, i) => `a-${i + 1}`)
    const itemsB = Array.from({ length: 25 }, (_, i) => `b-${i + 1}`)
    const { rerender } = render(
      <PaginatedList items={itemsA} pageSize={10} renderItem={(item) => <span>{item}</span>} />
    )

    await user.click(screen.getByLabelText('Go to next page'))
    expect(screen.getByText('a-11')).toBeInTheDocument()

    rerender(<PaginatedList items={itemsB} pageSize={10} renderItem={(item) => <span>{item}</span>} />)

    expect(screen.getByText('b-1')).toBeInTheDocument()
    expect(screen.queryByText('b-11')).not.toBeInTheDocument()
  })

  it('renders the empty state when items is empty', () => {
    render(
      <PaginatedList
        items={[]}
        pageSize={10}
        renderItem={(item) => <span>{String(item)}</span>}
        emptyState={<p>Brak wpisów</p>}
      />
    )

    expect(screen.getByText('Brak wpisów')).toBeInTheDocument()
  })

  it('clamps page to current pageCount to prevent transient blank renders when items shrink', async () => {
    const user = userEvent.setup()
    const longList = Array.from({ length: 25 }, (_, i) => `long-${i + 1}`)
    const shortList = Array.from({ length: 3 }, (_, i) => `short-${i + 1}`)
    const { rerender } = render(
      <PaginatedList items={longList} pageSize={10} renderItem={(item) => <span>{item}</span>} />
    )

    // Navigate to page 2 of the long list
    await user.click(screen.getByLabelText('Go to next page'))
    expect(screen.getByText('long-11')).toBeInTheDocument()

    // Rerender with a much shorter list that only has 1 page
    rerender(<PaginatedList items={shortList} pageSize={10} renderItem={(item) => <span>{item}</span>} />)

    // Should render the short list items, not be blank (safePage clamps to 1)
    expect(screen.getByText('short-1')).toBeInTheDocument()
    expect(screen.getByText('short-2')).toBeInTheDocument()
    expect(screen.getByText('short-3')).toBeInTheDocument()
    // Should not have pagination (all items fit on one page)
    expect(screen.queryByRole('navigation', { name: /pagination/i })).not.toBeInTheDocument()
  })
})
