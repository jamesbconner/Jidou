import type { ContentType, MediaPaths } from '@/types/api'

/**
 * Translate a container-side path to the equivalent host-side path using the
 * media_paths mapping from the config API.
 *
 * Returns the original path unchanged if no configured base matches, so the
 * UI degrades gracefully when host paths are not configured.
 */
export function toHostPath(containerPath: string, mediaPaths: MediaPaths): string {
  for (const { container, host } of Object.values(mediaPaths)) {
    if (containerPath === container || containerPath.startsWith(container + '/')) {
      const relative = containerPath.slice(container.length)
      // Mirror the separator style of the host base so Windows paths render
      // with backslashes and POSIX paths use forward slashes.
      const sep = host.includes('\\') ? '\\' : '/'
      return host + relative.replace(/\//g, sep)
    }
  }
  return containerPath
}

/**
 * Build a container-side path from a content type and a show folder name.
 * This is the inverse of toHostPath for the input side of path widgets.
 */
export function toContainerPath(
  contentType: ContentType,
  folderName: string,
  mediaPaths: MediaPaths,
): string {
  const base = mediaPaths[contentType].container
  return `${base}/${folderName.replace(/\\/g, '/')}`
}

/**
 * Parse an existing container path into its content type and folder name
 * components, using the configured media bases for recognition.
 *
 * Falls back to ('tv', basename) when no base matches.
 */
export function parseContainerPath(
  containerPath: string | null,
  mediaPaths: MediaPaths,
): { contentType: ContentType; folderName: string } {
  if (!containerPath) return { contentType: 'tv', folderName: '' }

  const entries: Array<[ContentType, string]> = [
    ['tv', mediaPaths.tv.container],
    ['anime', mediaPaths.anime.container],
    ['movie', mediaPaths.movie.container],
  ]

  for (const [type, base] of entries) {
    if (containerPath === base || containerPath.startsWith(base + '/')) {
      const folderName = containerPath.slice(base.length).replace(/^\//, '')
      return { contentType: type, folderName }
    }
  }

  // Fallback: extract the last path segment.
  const parts = containerPath.replace(/\\/g, '/').split('/')
  return { contentType: 'tv', folderName: parts[parts.length - 1] ?? '' }
}
