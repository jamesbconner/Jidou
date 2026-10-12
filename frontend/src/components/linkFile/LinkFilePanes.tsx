import type { ContentType, FileRead } from '@/types/api'

/**
 * Presentational panes of LinkFileModal.
 *
 * The modal keeps every query, mutation and typed value, so request timing and
 * retained input across a mode switch are unchanged.
 */

export const EXISTING_PREFIX = 'e:'
export const IMPORTED_PREFIX = 'i:'

export type LinkMode = 'existing' | 'path'

/** An imported-but-reassignable filename drawn from the show's other episodes. */
export interface ImportedChoice {
  filename: string
  displayName: string
  label: string
}

function basename(path: string): string {
  return path.replace(/\\/g, '/').split('/').pop() ?? path
}

function ModeButton({
  active,
  onClick,
  children,
}: {
  active: boolean
  onClick: () => void
  children: string
}) {
  return (
    <button
      onClick={onClick}
      className={`px-3 py-1.5 rounded border ${
        active
          ? 'bg-[var(--color-ocean-600)] border-[var(--color-ocean-600)] text-white'
          : 'border-zinc-600 text-zinc-300 hover:bg-zinc-700'
      }`}
    >
      {children}
    </button>
  )
}

/** "Pick existing file" / "Enter file path" switch. */
export function ModeSwitch({ mode, onChange }: { mode: LinkMode; onChange: (mode: LinkMode) => void }) {
  return (
    <div className="flex gap-1.5 text-xs">
      <ModeButton active={mode === 'existing'} onClick={() => onChange('existing')}>
        Pick existing file
      </ModeButton>
      <ModeButton active={mode === 'path'} onClick={() => onChange('path')}>
        Enter file path
      </ModeButton>
    </div>
  )
}

interface ExistingFilePaneProps {
  selected: string
  onSelect: (value: string) => void
  disabled: boolean
  loading: boolean
  availableFiles: FileRead[]
  importPool: ImportedChoice[]
}

/** Dropdown of orphaned files and imported filenames that can back the episode. */
export function ExistingFilePane({
  selected,
  onSelect,
  disabled,
  loading,
  availableFiles,
  importPool,
}: ExistingFilePaneProps) {
  return (
    <div className="space-y-1.5">
      <div className="text-xs text-zinc-400">
        Select a file available for this show
      </div>
      <select
        value={selected}
        onChange={(e) => onSelect(e.target.value)}
        disabled={disabled}
        className="w-full bg-zinc-800 border border-zinc-600 rounded px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-[var(--color-ocean-500)] disabled:opacity-50"
      >
        <option value="">— pick a file —</option>
        {availableFiles.length > 0 && (
          <optgroup label="Existing files">
            {availableFiles.map((f) => (
              <option key={f.id} value={`${EXISTING_PREFIX}${f.id}`}>
                {basename(f.original_filename)} ({f.status})
              </option>
            ))}
          </optgroup>
        )}
        {importPool.length > 0 && (
          <optgroup label="Imported">
            {importPool.map((f) => (
              <option key={f.filename} value={`${IMPORTED_PREFIX}${f.filename}`}>
                {basename(f.displayName)} (currently: {f.label})
              </option>
            ))}
          </optgroup>
        )}
      </select>
      {!loading && availableFiles.length === 0 && importPool.length === 0 && (
        <p className="text-xs text-zinc-500">No files available to link for this show.</p>
      )}
    </div>
  )
}

interface PathPaneProps {
  contentType: ContentType
  onContentTypeChange: (type: ContentType) => void
  relativePath: string
  onRelativePathChange: (value: string) => void
  fullPath: string | null
  disabled: boolean
}

/** Content-type radios and the relative-path input, with the resolved full path beneath. */
export function PathPane({
  contentType,
  onContentTypeChange,
  relativePath,
  onRelativePathChange,
  fullPath,
  disabled,
}: PathPaneProps) {
  return (
    <div className="space-y-3">
      <div className="space-y-1">
        <div className="text-xs text-zinc-400">Content type</div>
        <div className="flex gap-4">
          {(['anime', 'tv', 'movie'] as ContentType[]).map((t) => (
            <label key={t} className="flex items-center gap-1.5 text-sm text-zinc-200 cursor-pointer">
              <input
                type="radio"
                name="link_file_content_type"
                value={t}
                checked={contentType === t}
                onChange={() => onContentTypeChange(t)}
                disabled={disabled}
                className="accent-[var(--color-ocean-600)]"
              />
              {t.charAt(0).toUpperCase() + t.slice(1)}
            </label>
          ))}
        </div>
      </div>

      <div className="space-y-1.5">
        <div className="text-xs text-zinc-400">
          Path within the {contentType} folder (show / season / filename)
        </div>
        <input
          value={relativePath}
          onChange={(e) => onRelativePathChange(e.target.value)}
          disabled={disabled}
          placeholder="Show Name/Season 01/show.s01e01.mkv"
          className="w-full bg-zinc-800 border border-zinc-600 rounded px-3 py-2 text-sm text-zinc-200 font-mono focus:outline-none focus:border-[var(--color-ocean-500)] disabled:opacity-50"
          autoFocus
        />
        {fullPath && (
          <p className="text-xs text-zinc-500 font-mono truncate">{fullPath}</p>
        )}
      </div>
    </div>
  )
}
