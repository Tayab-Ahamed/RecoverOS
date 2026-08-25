export function SkeletonCard({ height = 100 }: { height?: number }) {
  return <div className="skeleton-card" style={{ height }} />
}

export function SkeletonText({ width = '80%' }: { width?: string }) {
  return <div className="skeleton-text" style={{ width }} />
}

export function MetricsSkeleton() {
  return (
    <div className="metrics-skeleton">
      {[1, 2, 3, 4].map(i => <SkeletonCard key={i} height={100} />)}
    </div>
  )
}
