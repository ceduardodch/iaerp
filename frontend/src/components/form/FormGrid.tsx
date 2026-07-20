type FormGridProps = {
  children: React.ReactNode
  columns?: 1 | 2 | 3
}

export function FormGrid({ children, columns = 1 }: FormGridProps) {
  return (
    <div className={`form-grid form-grid-${columns}`}>{children}</div>
  )
}
