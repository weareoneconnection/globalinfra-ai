import { getTranslations } from 'next-intl/server';
import { api } from '@/lib/api';
type Module = { id:string; title:string; languages:string[]; risk:string; duration_min:number; modules:string[] };
export default async function Training() {
  const t = await getTranslations('Training');
  const rows=await api<Module[]>('/training');
  return <><div className="header-row"><div><div className="eyebrow">{t('eyebrow')}</div><h2 className="page-title">{t('title')}</h2><p className="page-subtitle">{t('subtitle')}</p></div><button className="button">{t('generate')}</button></div><div className="grid-2">{rows.map(m=><div className="card card-pad" key={m.id}><div style={{display:'flex',justifyContent:'space-between'}}><h3 style={{marginTop:0}}>{m.title}</h3><span className="badge medium">{m.risk}</span></div><p className="muted">{t('languagesLabel')}: {m.languages.join(' / ')} · {m.duration_min} {t('minutesSuffix')}</p><div className="workflow">{m.modules.map((x,i)=><div className="step" key={x}><div className="step-num">0{i+1}</div><div><h4>{x}</h4><p>{t('moduleNote')}</p></div><span className="badge ok">{t('ready')}</span></div>)}</div></div>)}</div></>;
}
