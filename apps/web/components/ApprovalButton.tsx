'use client';
import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { useTranslations } from 'next-intl';

export function ApprovalButton({ id, action }: { id: number; action: 'approve' | 'reject' }) {
  const [busy, setBusy] = useState(false);
  const router = useRouter();
  const t = useTranslations('Components');
  async function submit() {
    setBusy(true);
    await fetch(`/backend/approvals/${id}/${action}`, { method: 'POST' });
    router.refresh();
    setBusy(false);
  }
  return <button className={`button ${action === 'reject' ? 'danger' : ''}`} onClick={submit} disabled={busy}>{busy ? t('saving') : action === 'approve' ? t('approve') : t('reject')}</button>;
}
