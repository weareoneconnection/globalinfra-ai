'use client';
import { useState } from 'react';
import { useRouter } from 'next/navigation';

export function RunAnalysisButton({ caseId }: { caseId: string }) {
  const [running, setRunning] = useState(false);
  const [error, setError] = useState('');
  const router = useRouter();
  async function run() {
    setRunning(true); setError('');
    try {
      const res = await fetch(`/backend/cases/${caseId}/analyze`, { method: 'POST' });
      if (!res.ok) throw new Error(await res.text());
      router.refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Analysis failed');
    } finally { setRunning(false); }
  }
  return <div style={{display:'flex',gap:10,alignItems:'center'}}><button className="button" onClick={run} disabled={running}>{running ? 'Running specialist agents…' : 'Run AI Analysis'}</button>{error && <span style={{color:'#ff9e9e',fontSize:11}}>{error}</span>}</div>;
}
