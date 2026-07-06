import '@testing-library/jest-dom'

// jsdom's requestAnimationFrame implementation (since v16.1.0) keeps an
// internal setInterval alive with no way to cancel it, which prevents the
// Node process from exiting after the test run finishes
// (https://github.com/jsdom/jsdom/issues/2886). @dnd-kit (used by the
// Watchlist page for drag-and-drop) calls requestAnimationFrame internally,
// which was hanging `vitest run` indefinitely in CI. Replacing it with a
// plain setTimeout-based implementation avoids the leak.
globalThis.requestAnimationFrame = (cb: FrameRequestCallback): number =>
  setTimeout(() => cb(Date.now()), 0) as unknown as number
globalThis.cancelAnimationFrame = (id: number): void => clearTimeout(id)

// jsdom does not implement ResizeObserver at all. CardCarousel (and any
// future component that measures its own size) needs some implementation
// present so mounting it in tests doesn't throw ReferenceError; jsdom never
// reports real layout changes anyway, so a no-op observer is sufficient.
class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}
globalThis.ResizeObserver = ResizeObserverStub as unknown as typeof ResizeObserver
