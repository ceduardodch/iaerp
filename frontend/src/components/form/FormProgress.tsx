type FormProgressProps = {
  steps: Array<{ title: string; status: 'completed' | 'current' | 'pending' }>
}

export function FormProgress({ steps }: FormProgressProps) {
  const currentStepIndex = steps.findIndex((step) => step.status === 'current')
  const totalSteps = steps.length

  return (
    <div className="form-progress" aria-label="Progreso del formulario">
      <ol className="form-progress-steps">
        {steps.map((step, index) => (
          <li
            key={index}
            className={`form-progress-step ${step.status}`}
            aria-current={step.status === 'current' ? 'step' : undefined}
          >
            <span className="form-progress-step-number">
              {step.status === 'completed' ? '✓' : index + 1}
            </span>
            <span className="form-progress-step-title">{step.title}</span>
            {index < totalSteps - 1 ? (
              <div className="form-progress-step-connector" />
            ) : null}
          </li>
        ))}
      </ol>
      <p className="form-progress-summary">
        Paso {currentStepIndex + 1} de {totalSteps}
      </p>
    </div>
  )
}
