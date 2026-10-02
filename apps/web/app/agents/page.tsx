import { getTranslations } from 'next-intl/server';
import { api } from '@/lib/api';
type Agent = { id:string; name:string; group:string; role:string; risk_level:string; tools:string[] };
export default async function Agents() {
  const t = await getTranslations('Agents');
  const agents = await api<Agent[]>('/agents'); const groups=[...new Set(agents.map(a=>a.group))];
  return <><div className="header-row"><div><div className="eyebrow">{t('eyebrow')}</div><h2 className="page-title">{t('title')}</h2><p className="page-subtitle">{t('subtitle')}</p></div><span className="badge ok">{t('available', { count: agents.length })}</span></div>
  <div className="router-strip"><div className="router-case"><small>{t('incomingLabel')}</small><b>{t('incomingValue')}</b></div><span className="router-arrow">›</span><div className="router-core"><span>AI</span><div><small>{t('routerLabel')}</small><b>{t('routerValue')}</b></div></div><span className="router-arrow">›</span><div className="router-team"><small>{t('teamLabel')}</small><b>{t('teamValue')}</b></div></div>
  {groups.map(group=><section className="agent-group section" key={group}><div className="outside-title"><div><span className="section-kicker">{t('practiceKicker')}</span><h3>{group}</h3></div><span>{t('agentsCount', { count: agents.filter(a=>a.group===group).length })}</span></div><div className="agent-grid">{agents.filter(a=>a.group===group).map(a=><div className="agent-card" key={a.id}><div className="agent-card-head"><div className="agent-icon">{a.name.split(' ').map(x=>x[0]).join('').slice(0,2)}</div><span className={`risk-dot ${a.risk_level}`} /></div><h4>{a.name}</h4><p>{a.role}</p><div className="tool-list">{a.tools.map(tool=><span key={tool}>{tool}</span>)}</div></div>)}</div></section>)}
  </>;
}
