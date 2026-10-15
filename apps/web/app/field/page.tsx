import { getTranslations } from 'next-intl/server';
import { api } from '@/lib/api';
import { FieldCapture } from '@/components/FieldCapture';
import { FieldReports } from '@/components/FieldReports';

type Project={id:number;code:string;name:string;latitude?:number;longitude?:number};

export default async function FieldPage(){
  const t=await getTranslations('Field'); const projects=await api<Project[]>('/projects');
  const labels=['captureKicker','captureTitle','project','eventType','severity','twinId','description','descriptionHint','media','mediaHint','files','captureLocation','noLocation','locationCaptured','locationUnavailable','save','savedOffline','queueKicker','queueTitle','queueHint','syncNow','syncing','synced','offlineQueued','working','connectivity','twinNone','scan','scanning','scanMatched','scanUnknown','scanTimeout','scanUnavailable','nearestProject'].reduce<Record<string,string>>((all,key)=>({...all,[key]:t.raw(key) as string}),{});
  return <><div className="header-row"><div><div className="eyebrow">{t('eyebrow')}</div><h2 className="page-title">{t('title')}</h2><p className="page-subtitle">{t('subtitle')}</p></div><span className="badge ok">{t('badge')}</span></div><FieldCapture projects={projects} labels={labels} eventLabels={t.raw('eventTypes') as Record<string,string>} severityLabels={t.raw('severities') as Record<string,string>}/><FieldReports/></>;
}
