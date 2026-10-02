'use client';
import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { useTranslations } from 'next-intl';

export function RunAnalysisButton({ caseId }: { caseId: string }) {
  const [running, setRunning] = useState(false);
  const [error, setError] = useState('');
  const router = useRouter();
  const t = useTranslations('Components');
  async function run() {
    setRunning(true); setError('');
    try {
      const res = await fetch(`/backend/cases/${caseId}/analyze`, { method: 'POST' });
      if (!res.ok) throw new Error(await res.text());
      router.refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : t('analysisFailed'));
    } finally { setRunning(false); }
  }
  return <div style={{display:'flex',gap:10,alignItems:'center'}}><button className="button" onClick={run} disabled={running}>{running ? t('running') : t('runAnalysis')}</button>{error && <span style={{color:'#ff9e9e',fontSize:11}}>{error}</span>}</div>;
}
