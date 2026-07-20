import { useState } from 'react'

type FormSectionProps = {
  title: string
  description?: string
  defaultExpanded?: boolean
  children: React.ReactNode
}

export function FormSection({
  title,
  description,
  defaultExpanded = true,
  children,
}: FormSectionProps) {
  const [isExpanded, setIsExpanded] = useState(defaultExpanded)

  return (
    <section className="form-section">
      <button
        type="button"
        className="form-section-header"
        onClick={() => setIsExpanded(!isExpanded)}
        aria-expanded={isExpanded}
      >
        <h3>{title}</h3>
        {description ? <p className="form-section-description">{description}</p> : null}
        <span className={`form-section-toggle ${isExpanded ? 'expanded' : 'collapsed'}`}>
          <svg
            width="20"
            height="20"
            viewBox="0 0 20 20"
            fill="none"
            aria-hidden="true"
          >
            <path
              d="M6 8L10 12L14 8"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </span>
      </button>
      {isExpanded ? <div className="form-section-content">{children}</div> : null}
    </section>
  )
}
