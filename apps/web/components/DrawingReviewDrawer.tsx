'use client';

import dynamic from 'next/dynamic';
import Link from 'next/link';
import { useEffect, useRef } from 'react';
import { useTranslations } from 'next-intl';

function DrawingReviewLoading() {
  const t = useTranslations('Drawings');
  return <div className="drawing-review-loading" aria-live="polite">{t('loadingReview')}</div>;
}

const DrawingWorkspace = dynamic(
  () => import('./DrawingWorkspace').then(module => module.DrawingWorkspace),
  { loading: DrawingReviewLoading, ssr: false },
);

type Project = { id: number; code: string; name: string };

export type DrawingReviewTarget = {
  drawingId: string;
  page: number;
  elementId: string;
};

export function DrawingReviewDrawer({ projects, target, onClose }: {
  projects: Project[];
  target: DrawingReviewTarget;
  onClose: () => void;
}) {
  const t = useTranslations('Drawings');
  const closeRef = useRef<HTMLButtonElement>(null);
  const fullPageUrl = `/drawings?drawing_id=${encodeURIComponent(target.drawingId)}&page=${target.page}&element_id=${encodeURIComponent(target.elementId)}&from=assistant`;

  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    document.body.style.overflow = 'hidden';
    window.addEventListener('keydown', onKeyDown);
    closeRef.current?.focus();
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener('keydown', onKeyDown);
      previousFocus?.focus();
    };
  }, [onClose]);

  return <div className="drawing-review-backdrop" onMouseDown={event => {
    if (event.target === event.currentTarget) onClose();
  }}>
    <section className="drawing-review-drawer" role="dialog" aria-modal="true" aria-labelledby="drawing-review-title">
      <header className="drawing-review-header">
        <div>
          <span>{t('assistantReviewMode')}</span>
          <h2 id="drawing-review-title">{t('title')}</h2>
          <p>{t('reviewContext')}</p>
        </div>
        <code>{target.drawingId}</code>
        <div className="drawing-review-actions">
          <Link className="button secondary" href={fullPageUrl} target="_blank" rel="noreferrer">{t('openFullPage')}</Link>
          <button ref={closeRef} className="drawing-review-close" type="button" onClick={onClose} aria-label={t('closeReview')}>×</button>
        </div>
      </header>
      <div className="drawing-review-body">
        <DrawingWorkspace
          projects={projects}
          initialDrawingId={target.drawingId}
          initialPage={target.page}
          initialElementId={target.elementId}
          reviewMode
        />
      </div>
    </section>
  </div>;
}
