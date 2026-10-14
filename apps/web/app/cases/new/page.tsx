import Link from 'next/link';
import { getTranslations } from 'next-intl/server';
import { CaseCreateForm } from '@/components/CaseCreateForm';
import { api } from '@/lib/api';

type Project = { id: number; code: string; name: string; country_code: string; domain: string };

export default async function NewCasePage() {
  const [t, projects] = await Promise.all([
    getTranslations('CaseCreate'),
    api<Project[]>('/projects'),
  ]);

  return <>
    <div className="header-row case-create-head">
      <div>
        <div className="eyebrow">{t('eyebrow')}</div>
        <h2 className="page-title">{t('title')}</h2>
        <p className="page-subtitle">{t('subtitle')}</p>
      </div>
      <Link className="button secondary" href="/cases">← {t('back')}</Link>
    </div>
    <CaseCreateForm projects={projects} />
  </>;
}
