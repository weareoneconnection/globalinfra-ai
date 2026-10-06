import { getTranslations } from 'next-intl/server';
import { api } from '@/lib/api';
import { Metric } from '@/components/Metric';
import { TwinWorkspace, TwinObject, TwinEvent, Control, Commissioning, Operations, Scenario, TwinAgent } from '@/components/TwinWorkspace';

type Summary={maturity:string;sync_status:string;model_version:string;objects:number;mapped_objects:number;average_health:number;active_events:number;critical_events:number;online_sensors:number;schedule_variance_days:number;cost_exposure_m:number;commissioning_readiness:number;handover_completeness:number;layers:string[]};
type Scene={objects:TwinObject[];events:TwinEvent[];geometry_protocols:string[]};

export default async function DigitalTwinPage(){
  const t=await getTranslations('Twin');
  const [summary,scene,controls,commissioning,operations,scenarios,agents]=await Promise.all([
    api<Summary>('/twin/summary?project_id=1'),api<Scene>('/twin/scene?project_id=1'),api<Control[]>('/twin/controls?project_id=1'),
    api<Commissioning[]>('/twin/commissioning?project_id=1'),api<Operations>('/twin/operations?project_id=1'),
    api<Scenario[]>('/twin/scenarios?project_id=1'),api<TwinAgent[]>('/twin/agents')
  ]);
  return <><div className="command-hero twin-hero"><div><div className="eyebrow">{t('eyebrow')}</div><h2 className="page-title">{t('title')}</h2><p className="page-subtitle">{t('subtitle')}</p></div><div className="twin-sync"><span className="pulse-ring">DT</span><div><small>{summary.maturity}</small><b>{summary.sync_status}</b><i>{summary.model_version}</i></div></div></div>
  <div className="grid-4 command-metrics"><Metric label={t('metricObjects')} value={summary.objects} delta={t('metricObjectsDelta',{mapped:summary.mapped_objects})}/><Metric label={t('metricHealth')} value={summary.average_health} delta={t('metricHealthDelta',{events:summary.active_events})}/><Metric label={t('metricSchedule')} value={`${summary.schedule_variance_days}d`} delta={t('metricScheduleDelta',{cost:summary.cost_exposure_m})}/><Metric label={t('metricHandover')} value={`${summary.commissioning_readiness}%`} delta={t('metricHandoverDelta',{docs:summary.handover_completeness})}/></div>
  <div className="twin-layer-rail">{summary.layers.map((layer,index)=><div key={layer}><span>{String(index+1).padStart(2,'0')}</span><b>{layer}</b></div>)}</div>
  <TwinWorkspace objects={scene.objects} events={scene.events} controls={controls} commissioning={commissioning} operations={operations} scenarios={scenarios} agents={agents} labels={t.raw('workspace')}/>
  </>;
}
