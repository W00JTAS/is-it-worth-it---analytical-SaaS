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

  useEffect(() => {
    setPage(1)
  }, [items])

  if (items.length === 0) {
    return emptyState ?? null
  }

  const start = (page - 1) * pageSize
  const pageItems = items.slice(start, start + pageSize)
  const isFirstPage = page === 1
  const isLastPage = page === pageCount

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
                {page} / {pageCount}
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
