const ACRONYMS = new Set(['db', 'rss', 'tmdb'])

/** Display name for a task type: `refresh_show_metadata` -> `Refresh Show Metadata`, `rss_import` -> `RSS Import`. */
export function taskTypeLabel(taskType: string): string {
  return taskType
    .split('_')
    .map((word) => (ACRONYMS.has(word) ? word.toUpperCase() : word.charAt(0).toUpperCase() + word.slice(1)))
    .join(' ')
}
