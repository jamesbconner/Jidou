import { useRef, useState, useEffect, useCallback } from 'react'
import type { ReactNode } from 'react'

interface Props {
  children: ReactNode
}

/** Horizontal-scroll carousel shell. Entity-agnostic — pass any fixed-width cards as children. */
export function CardCarousel({ children }: Props) {
  const trackRef = useRef<HTMLDivElement>(null)
  const [canScrollPrev, setCanScrollPrev] = useState(false)
  const [canScrollNext, setCanScrollNext] = useState(false)

  const updateScrollState = useCallback(() => {
    const el = trackRef.current
    if (!el) return
    setCanScrollPrev(el.scrollLeft > 0)
    setCanScrollNext(el.scrollLeft + el.clientWidth < el.scrollWidth - 1)
  }, [])

  useEffect(() => {
    const el = trackRef.current
    if (!el) return
    // New children (e.g. filter/sort/limit change) should start scrolled to
    // the beginning — otherwise a stale scrollLeft from the previous result
    // set can leave the new items off-screen or show a blank strip.
    el.scrollLeft = 0
    updateScrollState()
    const observer = new ResizeObserver(updateScrollState)
    observer.observe(el)
    return () => observer.disconnect()
  }, [updateScrollState, children])

  function scrollBy(direction: 1 | -1) {
    const el = trackRef.current
    if (!el) return
    el.scrollBy({ left: direction * el.clientWidth * 0.9, behavior: 'smooth' })
  }

  return (
    <div className="relative group">
      {canScrollPrev && (
        <button
          onClick={() => scrollBy(-1)}
          aria-label="Scroll left"
          className="absolute left-0 top-1/2 -translate-y-1/2 z-10 w-8 h-8 rounded-full bg-white shadow flex items-center justify-center text-gray-600 hover:bg-gray-100"
        >
          ‹
        </button>
      )}
      <div
        ref={trackRef}
        onScroll={updateScrollState}
        className="flex gap-3 overflow-x-auto snap-x scroll-smooth"
      >
        {children}
      </div>
      {canScrollNext && (
        <button
          onClick={() => scrollBy(1)}
          aria-label="Scroll right"
          className="absolute right-0 top-1/2 -translate-y-1/2 z-10 w-8 h-8 rounded-full bg-white shadow flex items-center justify-center text-gray-600 hover:bg-gray-100"
        >
          ›
        </button>
      )}
    </div>
  )
}
