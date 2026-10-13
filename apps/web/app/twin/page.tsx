import { getTranslations } from 'next-intl/server';
import { api } from '@/lib/api';
import { Metric } from '@/components/Metric';
import { TwinWorkspace, TwinObject, TwinEvent, Control, Commissioning, Operations, Scenario, TwinAgent } from '@/components/TwinWorkspace';
import Link from 'next/link';
import { TwinOperationsPanel } from '@/components/TwinOperationsPanel';

type Summary={maturity:string;sync_status:string;model_version:string;objects:number;mapped_objects:number;average_health:number;active_events:number;critical_events:number;online_sensors:number;schedule_variance_days:number;cost_exposure_m:number;commissioning_readiness:number;handover_completeness:number;layers:string[]};
type Scene={objects:TwinObject[];events:TwinEvent[];geometry_protocols:string[]};
type TwinSource={id:string;source_type:string;name:string;version:string;status:string;coordinate_reference_system:string|null;uri:string;checksum:string|null;metadata:Record<string,string|number|boolean>};
type Project={id:number;code:string;name:string;country_code:string;domain:string};
type Manifest={project_id:number;project_code:string;version:string;provenance:string;disclaimer:string;coverage:string;twin_ids:string[];artifacts:{type:string;url:string;sha256:string|null;bytes:number|null}[]};
type ModelPlane={versions:{id:string;version:string;status:string;object_count:number;change_summary:Record<string,number>}[];jobs:{id:string;status:string;progress:number;adapter:string}[];external_adapters:Record<string,string>};

export default async function DigitalTwinPage({searchParams}:{searchParams:Promise<{project_id?:string}>}){
  const t=await getTranslations('Twin');
  const [params,projects]=await Promise.all([searchParams,api<Project[]>('/projects')]);
  const requested=Number(params.project_id||1);
  const projectId=projects.some(project=>project.id===requested)?requested:projects[0]?.id||1;
  const currentProject=projects.find(project=>project.id===projectId)!;
  const [summary,scene,controls,commissioning,operations,scenarios,agents,sources,manifest,models]=await Promise.all([
    api<Summary>(`/twin/summary?project_id=${projectId}`),api<Scene>(`/twin/scene?project_id=${projectId}`),api<Control[]>(`/twin/controls?project_id=${projectId}`),
    api<Commissioning[]>(`/twin/commissioning?project_id=${projectId}`),api<Operations>(`/twin/operations?project_id=${projectId}`),
    api<Scenario[]>(`/twin/scenarios?project_id=${projectId}`),api<TwinAgent[]>('/twin/agents'),api<TwinSource[]>(`/twin/sources?project_id=${projectId}`),api<Manifest>(`/twin/demo-pack/${projectId}/manifest`),api<ModelPlane>(`/twin/model-versions?project_id=${projectId}`)
  ]);
  return <><div className="command-hero twin-hero"><div><div className="eyebrow">{t('eyebrow')}</div><h2 className="page-title">{t('title')}</h2><p className="page-subtitle">{t('subtitle')}</p></div><div className="twin-sync"><span className="pulse-ring">DT</span><div><small>{summary.maturity}</small><b>{summary.sync_status}</b><i>{manifest.version} · {manifest.coverage}</i></div></div></div>
  <section className="twin-project-deck"><div><span className="section-kicker">{t('projectTwin')}</span><h3>{currentProject.code} · {currentProject.name}</h3><p>{t('syntheticNotice')}</p></div><nav aria-label={t('selectProject')}>{projects.map(project=><Link className={project.id===projectId?'active':''} href={`/twin?project_id=${project.id}`} key={project.id}><span>{project.country_code}</span><b>{project.code}</b><small>{project.domain}</small></Link>)}</nav><div className="twin-pack-proof"><b>{manifest.coverage}</b><span>{t('formatCoverage')}</span><i>{manifest.twin_ids.length} Twin IDs</i></div></section>
  <div className="grid-4 command-metrics"><Metric label={t('metricObjects')} value={summary.objects} delta={t('metricObjectsDelta',{mapped:summary.mapped_objects})}/><Metric label={t('metricHealth')} value={summary.average_health} delta={t('metricHealthDelta',{events:summary.active_events})}/><Metric label={t('metricSchedule')} value={`${summary.schedule_variance_days}d`} delta={t('metricScheduleDelta',{cost:summary.cost_exposure_m})}/><Metric label={t('metricHandover')} value={`${summary.commissioning_readiness}%`} delta={t('metricHandoverDelta',{docs:summary.handover_completeness})}/></div>
  <div className="twin-layer-rail">{summary.layers.map((layer,index)=><div key={layer}><span>{String(index+1).padStart(2,'0')}</span><b>{layer}</b></div>)}</div>
  <div className="twin-source-strip">{sources.map(source=><a href={source.uri} target="_blank" rel="noreferrer" key={source.id}><span className="live-dot"/><b>{source.source_type}</b><span>{source.name}</span><i>{source.version} · {source.status} · {source.coordinate_reference_system||'SOURCE CRS'}</i><em>{t('openArtifact')} ↗</em></a>)}</div>
  <div className="phase8-ribbon"><div><span>8.1</span><b>Native WebGL</b><small>GLTF · picking</small></div><div><span>8.2</span><b>Model lineage</b><small>{models.versions.length} versions</small></div><Link href="/twin/generate"><span>8.3</span><b>Twin generator</b><small>6-format pack ↗</small></Link><div><span>8.4</span><b>Live IoT</b><small>SSE stream</small></div><div><span>8.5</span><b>4D / 5D</b><small>time · cost</small></div><div><span>8.6</span><b>Grounded AI</b><small>citations</small></div><Link href={`/showcase?project_id=${projectId}`}><span>8.7</span><b>Demo mode</b><small>180 seconds ↗</small></Link></div>
  <TwinWorkspace key={projectId} objects={scene.objects} events={scene.events} controls={controls} commissioning={commissioning} operations={operations} scenarios={scenarios} agents={agents} labels={t.raw('workspace')} gltfUrl={manifest.artifacts.find(a=>a.type==='GLTF')?.url||`/backend/twin/demo-pack/${projectId}/model.gltf`}/>
  <TwinOperationsPanel projectId={projectId} initial={operations.sensors.map(sensor=>({sensor_id:sensor.id,twin_id:sensor.twin_id,type:sensor.type,value:sensor.value,unit:sensor.unit,status:sensor.status,sampled_at:new Date().toISOString()}))}/>
  </>;
}
