import { getTranslations } from 'next-intl/server';
import { DrawingWorkspace } from '@/components/DrawingWorkspace';
import { api } from '@/lib/api';

type Project = { id: number; code: string; name: string };

export default async function DrawingsPage() {
  const t = await getTranslations('Drawings');
  const projects = await api<Project[]>('/projects');

  return <>
    <div className="header-row drawing-page-head">
      <div>
        <div className="eyebrow">DRAWING-TO-TWIN COPILOT · P0—P2</div>
        <h2 className="page-title">{t('title')}</h2>
        <p className="page-subtitle">{t('subtitle')}</p>
      </div>
      <span className="badge info">EVIDENCE-BOUND · DRAFT BIM</span>
    </div>
    <DrawingWorkspace projects={projects} />
  </>;
}
