'use client';
import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { useTranslations } from 'next-intl';

type ActionStatus = 'APPROVED' | 'EXECUTED' | 'VERIFIED' | 'CLOSED' | 'EXECUTION_FAILED' | 'VERIFICATION_FAILED' | string;

export function GovernedActionControls({ actionId, status }: { actionId: string; status: ActionStatus }) {
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const router = useRouter();
  const t = useTranslations('Components');

  async function submit(step: 'execute' | 'verify' | 'close') {
    setBusy(step);
    setError('');
    try {
      const response = await fetch(`/backend/actions/${actionId}/${step}`, { method: 'POST' });
      if (!response.ok) throw new Error(await response.text());
      router.refresh();
    } catch {
      setError(t('governedActionFailed'));
    } finally {
      setBusy('');
    }
  }

  const canExecute = status === 'APPROVED' || status === 'EXECUTION_FAILED';
  const canVerify = status === 'EXECUTED' || status === 'VERIFICATION_FAILED';
  const canClose = status === 'VERIFIED';
  return <div className="card card-pad" style={{marginTop:14}}>
    <div className="section-title" style={{padding:0, border:0}}>
      <div><span className="section-kicker">{t('governedActionKicker')}</span><h3>{t('governedActionTitle')}</h3></div>
      <span className={`badge ${status === 'VERIFIED' || status === 'CLOSED' ? 'ok' : 'info'}`}>{status}</span>
    </div>
    <p className="muted" style={{marginBottom:12}}>{t('governedActionHint')}</p>
    <div style={{display:'flex', gap:8, flexWrap:'wrap'}}>
      {canExecute && <button className="button" onClick={() => submit('execute')} disabled={!!busy}>{busy === 'execute' ? t('executing') : t('execute')}</button>}
      {canVerify && <button className="button" onClick={() => submit('verify')} disabled={!!busy}>{busy === 'verify' ? t('verifying') : t('verify')}</button>}
      {canClose && <button className="button" onClick={() => submit('close')} disabled={!!busy}>{busy === 'close' ? t('closing') : t('close')}</button>}
      {!canExecute && !canVerify && !canClose && <span className="muted">{status === 'CLOSED' ? t('closed') : t('awaitingAction')}</span>}
    </div>
    {error && <div role="alert" style={{color:'#ff9e9e',fontSize:11,marginTop:8}}>{error}</div>}
  </div>;
}
