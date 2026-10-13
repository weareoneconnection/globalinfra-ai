import { getTranslations } from 'next-intl/server';
import { api } from '@/lib/api';
import { FieldCapture } from '@/components/FieldCapture';

type Project={id:number;code:string;name:string};

export default async function FieldPage(){
  const t=await getTranslations('Field'); const projects=await api<Project[]>('/projects');
  const labels=['captureKicker','captureTitle','project','eventType','severity','twinId','description','descriptionHint','media','mediaHint','files','captureLocation','noLocation','locationCaptured','locationUnavailable','save','savedOffline','queueKicker','queueTitle','queueHint','syncNow','syncing','synced','offlineQueued','working','connectivity'].reduce<Record<string,string>>((all,key)=>({...all,[key]:t(key)}),{});
  return <><div className="header-row"><div><div className="eyebrow">{t('eyebrow')}</div><h2 className="page-title">{t('title')}</h2><p className="page-subtitle">{t('subtitle')}</p></div><span className="badge ok">{t('badge')}</span></div><FieldCapture projects={projects} labels={labels}/></>;
}
