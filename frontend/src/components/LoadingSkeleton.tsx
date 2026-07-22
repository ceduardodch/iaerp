/**
 * Skeletons de carga (Sprint 8): placeholders animados que sustituyen a los
 * spinners/textos "Cargando…" para dar sensación de estructura mientras llega el
 * contenido. La animación de brillo vive en index.css (.skeleton).
 */

type SkeletonProps = {
  /** Ancho CSS (ej. '100%', '12rem'). Por defecto 100%. */
  width?: string
  /** Alto CSS (ej. '1rem'). Por defecto 1rem. */
  height?: string
  /** Radio de borde (ej. '.3rem', '50%'). */
  radius?: string
  className?: string
}

export function Skeleton({ width = '100%', height = '1rem', radius = '.3rem', className }: SkeletonProps) {
  return (
    <span
      className={`skeleton${className ? ` ${className}` : ''}`}
      style={{ width, height, borderRadius: radius }}
      aria-hidden="true"
    />
  )
}

/**
 * Bloque de skeleton para una sección que carga (p.ej. el fallback de un
 * componente lazy). Anuncia el estado a lectores de pantalla vía aria-live.
 */
export function SectionLoadingSkeleton({ label = 'Cargando…' }: { label?: string }) {
  return (
    <div className="section-skeleton" role="status" aria-live="polite" aria-busy="true">
      <span className="sr-only">{label}</span>
      <Skeleton width="40%" height="1.6rem" />
      <Skeleton width="100%" height="1rem" />
      <Skeleton width="92%" height="1rem" />
      <Skeleton width="96%" height="1rem" />
      <div className="section-skeleton-cards">
        <Skeleton height="7rem" />
        <Skeleton height="7rem" />
        <Skeleton height="7rem" />
      </div>
    </div>
  )
}
