import Link from 'next/link';

export type Domain = { id:string; name:string; number:string; question:string; accent:string; capabilities:string[]; health:number; trend:string; signal:string; open:number };

export function DomainCard({ domain, compact=false }: { domain:Domain; compact?:boolean }) {
  return <Link href={`/intelligence/${domain.id}`} className={`domain-card accent-${domain.accent} ${compact ? 'compact' : ''}`}>
    <div className="domain-head"><span className="domain-number">{domain.number}</span><span className="domain-health">{domain.health}<small>/100</small></span></div>
    <h3>{domain.name}</h3>
    {!compact && <p>{domain.question}</p>}
    <div className="health-track"><span style={{width:`${domain.health}%`}} /></div>
    <div className="domain-foot"><span>{domain.signal}</span><b>{domain.open} open</b></div>
  </Link>;
}
