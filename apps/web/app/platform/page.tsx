import { getTranslations } from 'next-intl/server';
import { api } from '@/lib/api';

type Capabilities={version:string;stage:string;capabilities:Record<string,string>;counts:Record<string,number>};
type Identity={subject:string;organization_id:string;roles:string[];project_ids:number[];auth_mode:string;authorization:string};
type Quality={id:string;suite:string;model_provider:string;model_name:string;status:string;score:number;dataset_version:string;created_at:string};

export default async function PlatformPage(){
  const t=await getTranslations('Platform');
  const [platform,identity,quality]=await Promise.all([api<Capabilities>('/platform/capabilities'),api<Identity>('/identity/me'),api<Quality[]>('/ai/quality-runs')]);
  return <><div className="header-row"><div><div className="eyebrow">{t('eyebrow')}</div><h2 className="page-title">{t('title')}</h2><p className="page-subtitle">{t('subtitle')}</p></div><span className="badge ok">{platform.version} · PILOT READY</span></div>
  <div className="phase7-metrics grid-4">{Object.entries(platform.counts).map(([key,value])=><div className="metric card" key={key}><span className="label">{key.replaceAll('_',' ')}</span><b className="value">{value}</b><div className="delta">GOVERNED RECORDS</div></div>)}</div>
  <div className="grid-2 section"><section className="card card-pad"><span className="section-kicker">{t('capabilities')}</span><div className="phase7-capabilities">{Object.entries(platform.capabilities).map(([stage,name])=><div key={stage}><span>{stage}</span><b>{name.replaceAll('_',' ')}</b><i>ACTIVE</i></div>)}</div></section><section className="card card-pad"><span className="section-kicker">{t('identity')}</span><h3>{identity.organization_id}</h3><div className="kv"><span className="k">Subject</span><span className="mono">{identity.subject}</span></div><div className="kv"><span className="k">Mode</span><span>{identity.auth_mode}</span></div><div className="capability-cloud">{identity.roles.map(role=><span key={role}>{role}</span>)}</div></section></div>
  <section className="section card"><div className="section-title"><h3>{t('quality')}</h3><span>{quality.length}</span></div>{quality.length?<div className="integration-list">{quality.map(run=><div key={run.id}><span className={`badge ${run.status==='PASSED'?'ok':'critical'}`}>{run.status}</span><b>{run.suite} · {run.model_name}</b><small>{Math.round(run.score*100)}% · {run.dataset_version} · {run.status==='PASSED'?t('passed'):t('blocked')}</small></div>)}</div>:<div className="empty-state">{t('noRuns')}</div>}</section></>;
}
