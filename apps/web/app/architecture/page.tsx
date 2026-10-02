import { getTranslations } from 'next-intl/server';
import { api } from '@/lib/api';
import { Domain } from '@/components/DomainCard';

type Thread = { event:string; nodes:{type:string;label:string;domain:string}[] };
type Professional = { id:string;name:string;scope:string;intelligence_domain:string };
type ProtocolStep = { step:string; label:string; desc:string };

export default async function Architecture() {
  const t = await getTranslations('Architecture');
  const [domains,thread,professional]=await Promise.all([api<Domain[]>('/domains'),api<Thread>('/digital-thread'),api<Professional[]>('/domains/professional')]);
  const matrixCols = t.raw('matrixCols') as string[];
  const matrixRows = t.raw('matrixRows') as string[];
  const protocolStack = t.raw('protocolStack') as ProtocolStep[];
  return <><div className="header-row"><div><div className="eyebrow">{t('eyebrow')}</div><h2 className="page-title">{t('title')}</h2><p className="page-subtitle">{t('subtitle')}</p></div><span className="badge info">{t('badge')}</span></div>
  <section className="card architecture-core"><div className="architecture-title"><span>{t('coreLabel')}</span><b>{t('coreTitle')}</b><small>{t('coreSub')}</small></div><div className="architecture-domains">{domains.map(d=><div className={`arch-domain accent-${d.accent}`} key={d.id}><span>{d.number}</span><b>{d.name.replace(' Intelligence','')}</b><small>{t('disciplines', { count: professional.filter(p=>p.intelligence_domain===d.id).length })}</small></div>)}</div></section>
  <section className="section card"><div className="section-title"><div><span className="section-kicker">{t('threadKicker')}</span><h3>{thread.event}</h3></div><span>{t('threadSpan', { count: thread.nodes.length })}</span></div><div className="thread-flow">{thread.nodes.map((n,i)=><div className={`thread-node accent-${domains.find(d=>d.id===n.domain)?.accent||'cyan'}`} key={`${n.type}-${i}`}><span>{n.type}</span><b>{n.label}</b>{i<thread.nodes.length-1&&<i>›</i>}</div>)}</div></section>
  <div className="grid-2 section"><div className="card card-pad"><span className="section-kicker">{t('matrixKicker')}</span><h3>{t('matrixTitle')}</h3><p className="page-subtitle">{t('matrixDesc')}</p><div className="matrix-mini"><div />{matrixCols.map(c=><b key={c}>{c}</b>)}{matrixRows.map((x,i)=><div className="matrix-row" key={x}><strong>{x}</strong>{[0,1,2,3,4,5].map(y=><span className={(y+i)%3===0?'hot':''} key={`${x}-${y}`} />)}</div>)}</div></div>
  <div className="card card-pad"><span className="section-kicker">{t('protocolKicker')}</span><h3>{t('protocolTitle')}</h3><div className="protocol-stack">{protocolStack.map(x=><div key={x.label}><span>{x.step}</span><b>{x.label}</b><small>{x.desc}</small></div>)}</div></div></div>
  </>;
}
