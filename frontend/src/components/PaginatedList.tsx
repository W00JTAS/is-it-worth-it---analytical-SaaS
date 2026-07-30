import { useEffect, useState, type ReactNode } from 'react'
import {
  Pagination,
  PaginationContent,
  PaginationItem,
  PaginationNext,
  PaginationPrevious,
} from '@/components/ui/pagination'

interface PaginatedListProps<T> {
  items: readonly T[]
  pageSize: number
  renderItem: (item: T, index: number) => ReactNode
  emptyState?: ReactNode
}

export function PaginatedList<T>({ items, pageSize, renderItem, emptyState }: PaginatedListProps<T>) {
  const [page, setPage] = useState(1)
  const pageCount = Math.max(1, Math.ceil(items.length / pageSize))

  // Resets to page 1 whenever `items` changes identity — callers must pass a referentially
  // stable array (e.g. from useState), not an inline-derived one like items.filter(...),
  // or the page will reset on every render.
  useEffect(() => {
    setPage(1)
  }, [items])

  if (items.length === 0) {
    return emptyState ? <div className="space-y-3">{emptyState}</div> : null
  }

  const safePage = Math.min(page, pageCount)
  const start = (safePage - 1) * pageSize
  const pageItems = items.slice(start, start + pageSize)
  const isFirstPage = safePage === 1
  const isLastPage = safePage === pageCount

  return (
    <div className="space-y-3">
      <ul className="space-y-1">
        {pageItems.map((item, index) => (
          <li key={start + index}>{renderItem(item, start + index)}</li>
        ))}
      </ul>
      {pageCount > 1 && (
        <Pagination>
          <PaginationContent>
            <PaginationItem>
              <PaginationPrevious
                href="#"
                onClick={(event) => {
                  event.preventDefault()
                  setPage((current) => Math.max(1, current - 1))
                }}
                aria-disabled={isFirstPage}
                className={isFirstPage ? 'pointer-events-none opacity-50' : undefined}
              />
            </PaginationItem>
            <PaginationItem>
              <span className="px-3 text-sm text-muted-foreground">
                {safePage} / {pageCount}
              </span>
            </PaginationItem>
            <PaginationItem>
              <PaginationNext
                href="#"
                onClick={(event) => {
                  event.preventDefault()
                  setPage((current) => Math.min(pageCount, current + 1))
                }}
                aria-disabled={isLastPage}
                className={isLastPage ? 'pointer-events-none opacity-50' : undefined}
              />
            </PaginationItem>
          </PaginationContent>
        </Pagination>
      )}
    </div>
  )
}
