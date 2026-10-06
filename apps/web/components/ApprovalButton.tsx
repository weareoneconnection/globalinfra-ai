'use client';
import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { useTranslations } from 'next-intl';

export function ApprovalButton({ id, action }: { id: number; action: 'approve' | 'reject' }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const router = useRouter();
  const t = useTranslations('Components');
  async function submit() {
    setBusy(true);
    setError('');
    try {
      const response = await fetch(`/backend/approvals/${id}/${action}`, { method: 'POST' });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      router.refresh();
    } catch {
      setError(t('approvalFailed'));
    } finally {
      setBusy(false);
    }
  }
  return <div><button className={`button ${action === 'reject' ? 'danger' : ''}`} onClick={submit} disabled={busy}>{busy ? t('saving') : action === 'approve' ? t('approve') : t('reject')}</button>{error && <div role="alert" style={{color:'#ff9e9e',fontSize:11,marginTop:6}}>{error}</div>}</div>;
}
