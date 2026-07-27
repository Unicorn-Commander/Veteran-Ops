import { FolderUp, UploadCloud } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { cx } from './ui'

/** Recursively walk a dropped directory entry into a flat File[] (so a veteran
 * can drop a whole folder tree, not just loose files). Entries must be pulled
 * from the DataTransfer synchronously in the drop handler; this only awaits the
 * async FileSystem reads afterward. */
async function readEntry(entry: FileSystemEntry): Promise<File[]> {
  if (entry.isFile) {
    return new Promise((resolve) =>
      (entry as FileSystemFileEntry).file(
        (f) => resolve([f]),
        () => resolve([]),
      ),
    )
  }
  if (entry.isDirectory) {
    const reader = (entry as FileSystemDirectoryEntry).createReader()
    const readBatch = (): Promise<FileSystemEntry[]> =>
      new Promise((resolve) => reader.readEntries((e) => resolve(e), () => resolve([])))
    const out: File[] = []
    let batch = await readBatch()
    while (batch.length) {
      for (const e of batch) out.push(...(await readEntry(e)))
      batch = await readBatch() // readEntries yields in chunks; loop until empty
    }
    return out
  }
  return []
}

/** Generic multi-file drag-and-drop zone (Documents.tsx). Purely presentational
 * — the caller decides what to do with the picked files. Accepts loose files,
 * whole FOLDERS (via the "select a folder" affordance and recursive folder
 * drag-drop), and ZIPs. Exposes its drag-over state via `onDragStateChange`. */
export function DropZone({
  onFiles,
  accept,
  disabled,
  hint,
  onDragStateChange,
  folders = true,
}: {
  onFiles: (files: File[]) => void
  accept?: string
  disabled?: boolean
  hint?: string
  onDragStateChange?: (over: boolean) => void
  /** Show the "or select a whole folder" affordance + accept folder drops. */
  folders?: boolean
}) {
  const [dragOver, setDragOver] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const folderRef = useRef<HTMLInputElement>(null)

  // webkitdirectory isn't a typed React attribute — set it imperatively.
  useEffect(() => {
    if (folderRef.current) folderRef.current.setAttribute('webkitdirectory', '')
  }, [])

  const setDrag = (over: boolean) => {
    setDragOver(over)
    onDragStateChange?.(over)
  }

  const handleFiles = (list: FileList | null) => {
    if (!list || list.length === 0) return
    onFiles(Array.from(list))
  }

  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault()
    setDrag(false)
    if (disabled) return
    // Pull entries synchronously (the DataTransfer is invalidated after the
    // handler returns), then recurse folders. Fall back to flat files when the
    // browser doesn't expose the entries API.
    const items = e.dataTransfer.items
    const entries: FileSystemEntry[] = []
    if (folders && items && items.length) {
      for (let i = 0; i < items.length; i++) {
        const entry = items[i].webkitGetAsEntry?.()
        if (entry) entries.push(entry)
      }
    }
    if (entries.length) {
      const files = (await Promise.all(entries.map(readEntry))).flat()
      if (files.length) onFiles(files)
    } else {
      handleFiles(e.dataTransfer.files)
    }
  }

  return (
    // Non-interactive drop region: drag/drop + a mouse-only click-to-browse
    // convenience. Keyboard/AT users operate the real <button>s inside (a
    // <button> can't nest inside a role="button" — that was the bug).
    <div
      onDragOver={(e) => {
        e.preventDefault()
        if (!disabled) setDrag(true)
      }}
      onDragLeave={() => setDrag(false)}
      onDrop={(e) => void handleDrop(e)}
      onClick={() => !disabled && inputRef.current?.click()}
      className={cx(
        'group flex cursor-pointer flex-col items-center justify-center gap-2 rounded-pane border-2 border-dashed px-6 py-12 text-center transition-all duration-200 ease-out',
        dragOver
          ? 'scale-[1.01] border-brand bg-brand-soft shadow-glow'
          : 'border-line bg-surface/50 hover:border-brand/50 hover:bg-brand-soft/30',
        disabled && 'pointer-events-none opacity-60'
      )}
    >
      <button
        type="button"
        disabled={disabled}
        onClick={(e) => {
          e.stopPropagation()
          if (!disabled) inputRef.current?.click()
        }}
        className="flex flex-col items-center gap-2 rounded-control focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2"
      >
        <span
          className={cx(
            'flex h-12 w-12 items-center justify-center rounded-full bg-brand-soft text-brand transition-transform duration-200 ease-out group-hover:-translate-y-0.5',
            dragOver && '-translate-y-1 scale-110'
          )}
        >
          <UploadCloud size={24} />
        </span>
        <span className="text-sm font-medium text-txt">
          {dragOver ? 'Drop to upload' : 'Drop files or folders here, or click to browse'}
        </span>
      </button>
      <p className="text-xs text-muted">{hint ?? 'PDF, PNG, JPG, TIFF, or TXT — up to 50MB each'}</p>
      {folders && (
        <button
          type="button"
          disabled={disabled}
          onClick={(e) => {
            e.stopPropagation()
            folderRef.current?.click()
          }}
          className="mt-1 inline-flex items-center gap-1.5 rounded-control border border-line bg-surface2 px-3 py-1.5 text-xs font-semibold text-muted transition-colors hover:border-brand/50 hover:text-brand"
        >
          <FolderUp size={13} /> Select a whole folder
        </button>
      )}
      <input
        ref={inputRef}
        type="file"
        multiple
        accept={accept}
        className="hidden"
        onChange={(e) => {
          handleFiles(e.target.files)
          e.target.value = ''
        }}
      />
      <input
        ref={folderRef}
        type="file"
        multiple
        className="hidden"
        onChange={(e) => {
          handleFiles(e.target.files)
          e.target.value = ''
        }}
      />
    </div>
  )
}
