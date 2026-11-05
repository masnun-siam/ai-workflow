/** A page's loading state: a status line over skeleton blocks of the given heights. */
export function Loading({ label, heights }: { label: string; heights: number[] }) {
  return (
    <div className="stack" aria-busy="true">
      <p className="muted" role="status">{label}</p>
      {heights.map((h, i) => <div key={i} className="skel" style={{ height: h }} />)}
    </div>
  );
}
