import type { ContentType, MediaPaths } from '@/types/api'

/**
 * Sanitize a show title for use as a folder name by replacing filesystem-illegal
 * characters with underscores.
 */
export function sanitizeFolderName(title: string): string {
  return title.replace(/[\\/:*?"<>|]/g, '_').trim()
}

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
      // Strip any trailing separator from host to avoid double-separator when
      // the env var was set with a trailing slash/backslash.
      const hostBase = host.replace(/[/\\]+$/, '')
      return hostBase + relative.replace(/\//g, sep)
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
  // Strip leading slashes from folderName so a user-typed leading slash does
  // not produce a double-slash in the stored path (e.g. /data/media/tv//Show).
  const sanitized = folderName.replace(/\\/g, '/').replace(/^\/+/, '')
  return `${base}/${sanitized}`
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
  if (!containerPath) return { contentType: 'anime', folderName: '' }

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

  // Fallback: extract the last non-empty path segment.
  const parts = containerPath.replace(/\\/g, '/').split('/').filter(Boolean)
  return { contentType: 'tv', folderName: parts[parts.length - 1] ?? '' }
}
