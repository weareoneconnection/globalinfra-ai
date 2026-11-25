import { getTranslations } from 'next-intl/server';
import Link from 'next/link';
import { DrawingWorkspace } from '@/components/DrawingWorkspace';
import { api } from '@/lib/api';

type Project = { id: number; code: string; name: string };

type SearchParams = { drawing_id?: string | string[]; page?: string | string[]; element_id?: string | string[]; from?: string | string[] };

function first(value: string | string[] | undefined): string {
  return Array.isArray(value) ? value[0] ?? '' : value ?? '';
}

export default async function DrawingsPage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const t = await getTranslations('Drawings');
  const params = await searchParams;
  const projects = await api<Project[]>('/projects');
  const drawingId = first(params.drawing_id);
  const requestedPage = Number(first(params.page));
  const initialPage = Number.isInteger(requestedPage) && requestedPage > 0 ? requestedPage : 1;
  const fromAssistant = first(params.from) === 'assistant';

  return <>
    <div className="header-row drawing-page-head">
      <div>
        <div className="eyebrow">DRAWING-TO-TWIN COPILOT · P0—P2</div>
        <h2 className="page-title">{t('title')}</h2>
        <p className="page-subtitle">{t('subtitle')}</p>
      </div>
      <div className="drawing-head-actions">
        <span className="badge info">{fromAssistant ? t('openedFromAssistant') : t('standaloneWorkbench')}</span>
        <Link className="button secondary" href="/">{t('backToAssistant')}</Link>
      </div>
    </div>
    <DrawingWorkspace projects={projects} initialDrawingId={drawingId} initialPage={initialPage} initialElementId={first(params.element_id)} />
  </>;
}
