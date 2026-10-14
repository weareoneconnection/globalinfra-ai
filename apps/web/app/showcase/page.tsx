import { api } from '@/lib/api';
import { ShowcasePlayer, type ShowcaseManifest, type ShowcaseModels, type ShowcaseStep, type ShowcaseSummary } from '@/components/ShowcasePlayer';
import type { Control, Operations, TwinEvent, TwinObject } from '@/components/TwinWorkspace';

type Project={id:number;code:string;name:string};
type Showcase={project:{id:number;code:string;name:string|Record<string,string>};duration_seconds:number;steps:ShowcaseStep[]};
type Scene={objects:TwinObject[];events:TwinEvent[]};

export default async function ShowcasePage({searchParams}:{searchParams:Promise<{project_id?:string}>}){
  const [params,projects]=await Promise.all([searchParams,api<Project[]>('/projects')]);
  const requested=Number(params.project_id||1);const projectId=projects.some(project=>project.id===requested)?requested:projects[0]?.id||1;
  const [showcase,scene,controls,operations,manifest,models,summary]=await Promise.all([
    api<Showcase>(`/twin/showcase/${projectId}`),api<Scene>(`/twin/scene?project_id=${projectId}`),api<Control[]>(`/twin/controls?project_id=${projectId}`),api<Operations>(`/twin/operations?project_id=${projectId}`),api<ShowcaseManifest>(`/twin/demo-pack/${projectId}/manifest`),api<ShowcaseModels>(`/twin/model-versions?project_id=${projectId}`),api<ShowcaseSummary>(`/twin/summary?project_id=${projectId}`)
  ]);
  const fallbackProject=projects.find(project=>project.id===projectId);const rawName=showcase.project.name;const projectName=typeof rawName==='string'?rawName:rawName.en||rawName.zh||fallbackProject?.name||'';
  return <ShowcasePlayer projectId={projectId} projectCode={showcase.project.code} projectName={projectName} steps={showcase.steps} objects={scene.objects} events={scene.events} controls={controls} operations={operations} manifest={manifest} models={models} summary={summary}/>;
}
