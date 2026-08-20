type Props = { provenance: Record<string, number> }

/**
 * Data provenance is displayed permanently and prominently. Synthetic and live
 * data must never be silently mixed, and a viewer must never have to guess
 * which they are looking at.
 */
export function ProvenanceBanner({ provenance }: Props) {
  const labels = Object.keys(provenance)
  if (labels.length === 0) return null

  const hasLive = labels.some((l) => l.includes("LIVE"))
  const mixed = labels.length > 1

  return (
    <div className={`provenance ${mixed ? "mixed" : hasLive ? "live" : "synthetic"}`}>
      {mixed
        ? `WARNING: MIXED DATA SOURCES (${labels.join(" + ")})`
        : hasLive
          ? "LIVE TEST MODE DATA"
          : "SYNTHETIC EVALUATION DATA"}
    </div>
  )
}
