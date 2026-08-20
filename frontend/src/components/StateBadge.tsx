type Props = { state: string }

// Colour carries meaning: green is verified money, red is a refusal, amber is
// waiting on a human.
const COLOURS: Record<string, string> = {
  RECOVERED: "badge green",
  DENIED: "badge red",
  STOPPED: "badge red",
  INELIGIBLE: "badge grey",
  AWAITING_APPROVAL: "badge amber",
  ESCALATED: "badge amber",
  MAX_ATTEMPTS: "badge amber",
  FAILED: "badge red",
  AWAITING_PAYMENT: "badge blue",
  EXECUTING: "badge blue",
}

export function StateBadge({ state }: Props) {
  return <span className={COLOURS[state] ?? "badge grey"}>{state}</span>
}
