import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent } from 'react'

/**
 * Selector buscable (patrón ARIA combobox 1.2).
 *
 * Un `<select>` nativo obliga a recorrer la lista entera: con cientos de
 * clientes o productos es inservible. Aquí se escribe para filtrar y la lista
 * muestra solo lo que coincide.
 *
 * Las flechas arriba/abajo tienen dos significados según el estado: con la
 * lista ABIERTA recorren las opciones; con la lista CERRADA no se interceptan y
 * el contenedor las recibe (`onKeyDown`), que es como la hoja de cálculo de la
 * factura navega entre filas. Así el mismo control sirve dentro de un formulario
 * y dentro de la grilla sin romper ninguno de los dos.
 */

export type ErpComboboxOption = {
  value: string
  label: string
  /** Segunda línea opcional: identificación, IVA del producto, etc. */
  hint?: string
}

type ErpComboboxProps = {
  options: ErpComboboxOption[]
  value: string
  onChange: (value: string) => void
  ariaLabel: string
  placeholder?: string
  required?: boolean
  disabled?: boolean
  className?: string
  /** Se invoca solo cuando la lista está cerrada (navegación del contenedor). */
  onKeyDown?: (event: KeyboardEvent<HTMLInputElement>) => void
  /** Coordenadas de la grilla de factura, para el foco por flechas. */
  dataRow?: number
  dataCol?: number
}

function normalize(text: string): string {
  // Sin tildes y en minúsculas: "peña" encuentra "PENA" y viceversa.
  return text.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase()
}

export function ErpCombobox({
  options,
  value,
  onChange,
  ariaLabel,
  placeholder = 'Escribe para buscar…',
  required = false,
  disabled = false,
  className = '',
  onKeyDown,
  dataRow,
  dataCol,
}: ErpComboboxProps) {
  const listId = useId()
  const wrapRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [activeIndex, setActiveIndex] = useState(0)

  const selected = options.find((option) => option.value === value)

  const matches = useMemo(() => {
    if (!query.trim()) return options
    const needle = normalize(query)
    return options.filter(
      (option) =>
        normalize(option.label).includes(needle) ||
        (option.hint ? normalize(option.hint).includes(needle) : false),
    )
  }, [options, query])

  // Cerrar al hacer clic fuera: sin esto la lista queda flotando sobre la tabla.
  useEffect(() => {
    if (!open) return
    function handlePointerDown(event: MouseEvent) {
      if (!wrapRef.current?.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handlePointerDown)
    return () => document.removeEventListener('mousedown', handlePointerDown)
  }, [open])

  useEffect(() => {
    if (activeIndex >= matches.length) setActiveIndex(0)
  }, [activeIndex, matches.length])

  function commit(option: ErpComboboxOption) {
    onChange(option.value)
    setQuery('')
    setOpen(false)
    inputRef.current?.focus()
  }

  function handleKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (!open) {
      if (event.key === 'ArrowDown') {
        event.preventDefault()
        setOpen(true)
        setActiveIndex(0)
        return
      }
      // Cerrado: el contenedor manda (filas de la hoja de cálculo, Enter, etc.).
      onKeyDown?.(event)
      return
    }

    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      if (matches.length === 0) return
      const step = event.key === 'ArrowDown' ? 1 : -1
      setActiveIndex((current) => (current + step + matches.length) % matches.length)
      return
    }
    if (event.key === 'Enter') {
      event.preventDefault()
      const option = matches[activeIndex]
      if (option) commit(option)
      return
    }
    if (event.key === 'Escape') {
      event.preventDefault()
      setQuery('')
      setOpen(false)
      return
    }
    if (event.key === 'Tab') setOpen(false)
  }

  return (
    <div className={`erp-combobox ${className}`.trim()} ref={wrapRef}>
      <input
        ref={inputRef}
        type="text"
        role="combobox"
        aria-label={ariaLabel}
        aria-expanded={open}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={open && matches[activeIndex] ? `${listId}-${activeIndex}` : undefined}
        autoComplete="off"
        required={required}
        disabled={disabled}
        placeholder={selected ? undefined : placeholder}
        // Mientras se escribe manda el texto tecleado; al cerrar vuelve a verse
        // la etiqueta elegida, para que el campo nunca quede mostrando una
        // búsqueda a medias que no corresponde al valor guardado.
        value={open ? query : selected?.label ?? ''}
        onChange={(event) => {
          setQuery(event.target.value)
          setActiveIndex(0)
          setOpen(true)
        }}
        onFocus={() => setQuery('')}
        onBlur={() => setOpen(false)}
        onClick={() => setOpen(true)}
        onKeyDown={handleKeyDown}
        data-row={dataRow}
        data-col={dataCol}
      />
      {open ? (
        <ul className="erp-combobox-list" role="listbox" id={listId} aria-label={ariaLabel}>
          {matches.length === 0 ? (
            <li className="erp-combobox-empty" role="presentation">
              Sin coincidencias
            </li>
          ) : (
            matches.map((option, index) => (
              <li
                key={option.value}
                id={`${listId}-${index}`}
                role="option"
                aria-selected={option.value === value}
                className={index === activeIndex ? 'is-active' : undefined}
                // mousedown y no click: el blur del input cerraría la lista antes.
                onMouseDown={(event) => {
                  event.preventDefault()
                  commit(option)
                }}
                onMouseEnter={() => setActiveIndex(index)}
              >
                <span>{option.label}</span>
                {option.hint ? <small>{option.hint}</small> : null}
              </li>
            ))
          )}
        </ul>
      ) : null}
    </div>
  )
}
