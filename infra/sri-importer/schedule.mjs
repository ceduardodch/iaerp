export function fiscalDay(now = new Date()) {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'America/Guayaquil',
    year: 'numeric', month: '2-digit', day: '2-digit',
  }).format(now)
}

export function importIsDue(lastAttemptDay, now = new Date()) {
  const hour = Number(new Intl.DateTimeFormat('en-GB', {
    timeZone: 'America/Guayaquil', hour: '2-digit', hourCycle: 'h23',
  }).format(now))
  return hour >= 8 && fiscalDay(now) !== lastAttemptDay
}

// The import callback can finish while shutdown closes its browser. Keep an
// interruption marker independent of its finally block clearing running.
export function recoverRunState(status) {
  return {
    ...status,
    lastAttemptDay: status.running || status.interrupted ? null : status.lastAttemptDay,
    running: false,
    interrupted: false,
  }
}

export function interruptRun(status) {
  if (status.running) status.interrupted = true
}
