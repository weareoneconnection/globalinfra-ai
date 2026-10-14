import { api } from '@/lib/api';
import { AssistantChat, AssistantProject } from '@/components/AssistantChat';

type Summary = { pending_approvals: number };
type Agent = { id: string; name: string };

export default async function Page() {
  const [projects, summary, agents] = await Promise.all([
    api<AssistantProject[]>('/projects'),
    api<Summary>('/dashboard/summary'),
    api<Agent[]>('/agents'),
  ]);
  const planningAgent = agents.find(agent => agent.id === 'planning')?.name ?? '';
  return <AssistantChat projects={projects} pendingApprovals={summary.pending_approvals} planningAgent={planningAgent} />;
}
