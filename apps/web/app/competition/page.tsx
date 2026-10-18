import { getLocale, getTranslations } from 'next-intl/server';
import { api } from '@/lib/api';
import {
  CompetitionEvidence,
  type GoldenThread,
  type SubmissionEvidence,
} from '@/components/CompetitionEvidence';

export default async function CompetitionPage(){
  const [locale,t,golden,evidence]=await Promise.all([
    getLocale(),
    getTranslations('Competition'),
    api<GoldenThread>('/competition/golden-thread'),
    api<SubmissionEvidence>('/competition/submission-evidence'),
  ]);
  return <>
    <div className="command-hero competition-hero">
      <div><div className="eyebrow">{t('eyebrow')}</div><h2 className="page-title">{t('title')}</h2><p className="page-subtitle">{t('subtitle')}</p></div>
      <div className="competition-score"><span>{evidence.release.evidence_status}</span><strong>{evidence.release.passed_cases}/{evidence.release.total_cases}</strong><small>{t('verifiedCases')}</small></div>
    </div>
    <CompetitionEvidence initialGolden={golden} evidence={evidence} locale={locale}/>
  </>;
}
