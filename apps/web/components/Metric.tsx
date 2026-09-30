export function Metric({ label, value, delta }: { label: string; value: string | number; delta?: string }) {
  return <div className="card metric"><div className="label">{label}</div><div className="value">{value}</div>{delta && <div className="delta">{delta}</div>}</div>;
}
