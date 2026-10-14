import { getTranslations } from 'next-intl/server';
import { api } from '@/lib/api';
import { CountryPackExplorer, type CountryPackSummary } from '@/components/CountryPackExplorer';

export default async function CountryPacksPage(){
  const [t,packs]=await Promise.all([getTranslations('CountryPacks'),api<CountryPackSummary[]>('/country-packs')]);
  return <><div className="command-hero country-hero"><div><div className="eyebrow">{t('eyebrow')}</div><h2 className="page-title">{t('title')}</h2><p className="page-subtitle">{t('subtitle')}</p></div><div className="country-coverage"><strong>{packs.length}</strong><span>{t('activePacks')}</span><small>{packs.reduce((sum,pack)=>sum+pack.permit_count,0)} {t('permitGates')}</small></div></div><CountryPackExplorer packs={packs} labels={t.raw('labels')}/></>;
}
