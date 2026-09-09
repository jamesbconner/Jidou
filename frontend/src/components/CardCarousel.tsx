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
          className="absolute left-0 top-1/2 -translate-y-1/2 z-10 w-8 h-8 rounded-full bg-white dark:bg-gray-800 shadow flex items-center justify-center text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700"
        >
          ‹
        </button>
      )}
      <div
        ref={trackRef}
        onScroll={updateScrollState}
        // overflow-x-auto also clips the cross axis (overflow-y computes to
        // auto), so a card's focus/hover/in-library ring — drawn outside its
        // border box — is cut off at the top and at the first/last card. The
        // p-1 / -m-1 pair reserves 4px of bleed room inside the scroller
        // without shifting the cards relative to the section heading, and
        // scroll-pl-1 keeps snap-start from aligning the first card to the
        // padding edge (which would scroll that left bleed back out of view).
        className="flex gap-3 overflow-x-auto snap-x scroll-smooth scroll-pl-1 p-1 -m-1"
      >
        {children}
      </div>
      {canScrollNext && (
        <button
          onClick={() => scrollBy(1)}
          aria-label="Scroll right"
          className="absolute right-0 top-1/2 -translate-y-1/2 z-10 w-8 h-8 rounded-full bg-white dark:bg-gray-800 shadow flex items-center justify-center text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700"
        >
          ›
        </button>
      )}
    </div>
  )
}
