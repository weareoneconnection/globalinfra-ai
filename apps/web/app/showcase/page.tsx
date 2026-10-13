import { api } from '@/lib/api';
import { ShowcasePlayer } from '@/components/ShowcasePlayer';

type Showcase={project:{id:number;code:string;name:Record<string,string>};duration_seconds:number;steps:{id:string;title:string;seconds:number;action:string}[]};
export default async function ShowcasePage({searchParams}:{searchParams:Promise<{project_id?:string}>}){const projectId=Number((await searchParams).project_id||1);const data=await api<Showcase>(`/twin/showcase/${projectId}`);return <ShowcasePlayer projectId={projectId} projectCode={data.project.code} steps={data.steps}/>}
