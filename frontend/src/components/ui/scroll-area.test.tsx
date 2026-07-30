import { describe, expect, it } from 'vitest'
import { render } from '@testing-library/react'
import { ScrollArea } from './scroll-area'

describe('ScrollArea', () => {
  it('renders both a vertical and a horizontal scrollbar', () => {
    // type="always" bypasses Radix's hover/overflow-detection-gated visibility (which
    // depends on real layout and pointer events unavailable in jsdom) so both scrollbars
    // mount unconditionally for this assertion.
    const { container } = render(
      <ScrollArea type="always" className="h-40 w-40">
        <div style={{ height: 400, width: 400 }}>content</div>
      </ScrollArea>
    )

    expect(container.querySelector('[data-slot="scroll-area-scrollbar"][data-orientation="vertical"]')).toBeInTheDocument()
    expect(container.querySelector('[data-slot="scroll-area-scrollbar"][data-orientation="horizontal"]')).toBeInTheDocument()
  })
})
