import { getTranslations } from 'next-intl/server';
import { DataIngestionCenter, type IngestionCatalog, type IngestionSummary } from '@/components/DataIngestionCenter';
import { api } from '@/lib/api';

type Project = { id: number; code: string; name: string };

export default async function DataIngestionPage() {
  const t = await getTranslations('DataIngestion');
  const [projects, catalog, summary] = await Promise.all([
    api<Project[]>('/projects'),
    api<IngestionCatalog>('/ingestion/catalog'),
    api<IngestionSummary>('/ingestion/summary'),
  ]);

  return <>
    <div className="header-row ingestion-page-head">
      <div>
        <div className="eyebrow">{t('eyebrow')}</div>
        <h2 className="page-title">{t('title')}</h2>
        <p className="page-subtitle">{t('subtitle')}</p>
      </div>
      <span className="badge ok">6 {t('channelsOnline')}</span>
    </div>
    <DataIngestionCenter projects={projects} catalog={catalog} initialSummary={summary} />
  </>;
}
