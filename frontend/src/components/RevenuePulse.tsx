import { useEffect, useRef, useState } from 'react'
import type { Metrics } from '../types'

/**
 * Animated counter that counts up from 0 to `target` over `duration` ms.
 * Used to give metric numbers a satisfying reveal animation on first load.
 */
function useCountUp(target: number, duration = 900, suffix = '') {
  const [value, setValue] = useState(0)
  const rafRef = useRef<number | null>(null)
  const startRef = useRef<number | null>(null)
  const prevTarget = useRef<number>(0)

  useEffect(() => {
    if (target === 0) { setValue(0); return }
    const from = prevTarget.current
    prevTarget.current = target
    startRef.current = null

    const tick = (now: number) => {
      if (!startRef.current) startRef.current = now
      const elapsed = now - startRef.current
      const progress = Math.min(elapsed / duration, 1)
      // ease-out cubic
      const eased = 1 - Math.pow(1 - progress, 3)
      setValue(Math.round(from + (target - from) * eased))
      if (progress < 1) {
        rafRef.current = requestAnimationFrame(tick)
      } else {
        setValue(target)
      }
    }
    rafRef.current = requestAnimationFrame(tick)
    return () => { if (rafRef.current) cancelAnimationFrame(rafRef.current) }
  }, [target, duration, suffix])

  return value
}

function AnimatedMoney({ display, raw }: { display: string; raw: number }) {
  // Extract numeric part and format with count-up
  const match = display.match(/^(.*?)(\d[\d,.]*)(.*)$/)
  const prefix = match?.[1] ?? ''
  const suffix = match?.[3] ?? ''
  // raw is in paise; we want rupees
  const rupees = Math.round(raw / 100)
  const animated = useCountUp(rupees)
  const formatted = animated.toLocaleString('en-IN')
  return <>{prefix}{formatted}{suffix}</>
}

function AnimatedRate({ value }: { value: number }) {
  const pct = Math.round(value * 1000) / 10
  const animated = useCountUp(Math.round(pct * 10), 900)
  return <>{(animated / 10).toFixed(1)}%</>
}

export function RevenuePulse({ metrics }: { metrics: Metrics }) {
  return (
    <section className="revenue-pulse">
      <div className="pulse-stat lead">
        <span>RECOVERY PULSE</span>
        <strong className="metric-animated">
          <AnimatedMoney display={metrics.recovered_revenue.display} raw={metrics.recovered_revenue.paise} />
        </strong>
        <small>verified revenue returned to orbit</small>
      </div>
      <div className="pulse-stat">
        <span>FLOATING VALUE</span>
        <strong className="metric-animated">
          <AnimatedMoney display={metrics.revenue_at_risk.display} raw={metrics.revenue_at_risk.paise} />
        </strong>
        <small>{metrics.cases} signals in this batch</small>
      </div>
      <div className="pulse-stat">
        <span>FIELD CONVERSION</span>
        <strong className="metric-animated">
          <AnimatedRate value={metrics.recovery_rate} />
        </strong>
        <small>capture-backed recovery rate</small>
      </div>
      <div className="pulse-stat pulse-status">
        <span>CONTROL STATUS</span>
        <strong><i /> NOMINAL</strong>
        <small>0 policy violations observed</small>
      </div>
    </section>
  )
}
