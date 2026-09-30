import { api } from '@/lib/api';

type Doc = { id:number; title:string; category:string; jurisdiction:string; language:string; source_ref:string; summary:string };
export default async function Knowledge() {
  const docs = await api<Doc[]>('/knowledge?query=contract');
  return <><div className="header-row"><div><div className="eyebrow">Knowledge fabric</div><h2 className="page-title">Evidence & Knowledge</h2><p className="page-subtitle">Project documents, contracts, standards, regulations and lessons learned become queryable, version-aware evidence.</p></div></div><div className="grid-2"><div className="card card-pad"><input className="search" defaultValue="contract" aria-label="search"/><div style={{marginTop:14}}>{docs.map(d=><div className="evidence" key={d.id}><h4>{d.title}</h4><p>{d.summary}</p><p className="mono" style={{marginTop:8}}>{d.category} · {d.jurisdiction} · {d.language} · {d.source_ref}</p></div>)}</div></div><div className="card card-pad"><div className="eyebrow">Evidence graph</div><h3>Claim → Source → Version → Jurisdiction</h3><div className="codebox">Decision\n ├─ Contract Clause C-14.2\n ├─ Responsibility Matrix RM-03\n ├─ Site Instruction SI-028\n ├─ Meeting Minutes MM-182\n └─ Photo IMG-229\n\nEach edge carries confidence, version, jurisdiction and content hash.</div></div></div></>;
}
