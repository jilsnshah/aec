export interface CsvColumn<T> {
  header: string
  value: (row: T) => string | number | null | undefined
}

function cell(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return ''
  const text = String(value)
  // Quote anything a spreadsheet could misread, and neutralise formulas.
  const safe = /^[=+\-@]/.test(text) && Number.isNaN(Number(text)) ? `'${text}` : text
  return /[",\n\r]/.test(safe) || safe !== text ? `"${safe.replace(/"/g, '""')}"` : safe
}

/** Build a CSV file from rows and offer it as a download. */
export function downloadCsv<T>(filename: string, columns: CsvColumn<T>[], rows: T[]) {
  const lines = [
    columns.map((column) => cell(column.header)).join(','),
    ...rows.map((row) => columns.map((column) => cell(column.value(row))).join(',')),
  ]
  // The byte-order mark makes Excel read the file as UTF-8 (₹, accents).
  const blob = new Blob(['﻿' + lines.join('\r\n')], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

/** Today's date for file names: 2026-10-29. */
export function fileStamp(date = new Date()): string {
  const pad = (value: number) => String(value).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}
