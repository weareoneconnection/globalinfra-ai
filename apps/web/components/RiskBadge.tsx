export function RiskBadge({ risk }: { risk: string }) {
  const r = risk.toLowerCase();
  return <span className={`badge ${r}`}>{risk.toUpperCase()}</span>;
}
