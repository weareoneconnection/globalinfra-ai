import { getLocale, getTranslations } from 'next-intl/server';
import { api } from '@/lib/api';
import { KnowledgeCenter, type KnowledgeSearch, type KnowledgeStats, type PackSummary } from '@/components/KnowledgeCenter';

export default async function KnowledgePage({searchParams}:{searchParams:Promise<{country?:string}>}){
  const statsPromise=api<KnowledgeStats>('/knowledge/stats');const packsPromise=api<PackSummary[]>('/country-packs');
  const [t,locale,params]=await Promise.all([getTranslations('Knowledge'),getLocale(),searchParams]);const initialCountry=(params.country||'').toUpperCase();
  const [initial,stats,packs]=await Promise.all([api<KnowledgeSearch>(`/knowledge/search?limit=20${initialCountry?`&country_code=${encodeURIComponent(initialCountry)}`:''}`),statsPromise,packsPromise]);
  return <><div className="command-hero knowledge-hero"><div><div className="eyebrow">{t('eyebrow')}</div><h2 className="page-title">{t('title')}</h2><p className="page-subtitle">{t('subtitle')}</p></div><div className="knowledge-trust"><span>KG</span><div><b>{stats.traceability_percent}%</b><small>{t('traceability')}</small></div></div></div><KnowledgeCenter initial={initial} initialCountry={initialCountry} locale={locale} stats={stats} packs={packs} labels={t.raw('labels')}/></>;
}
