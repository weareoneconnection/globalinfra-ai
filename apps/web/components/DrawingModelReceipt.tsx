'use client';

import dynamic from 'next/dynamic';
import { useTranslations } from 'next-intl';
import type { DrawingModelSnapshot } from './DrawingWorkspace';

const Twin3DViewer = dynamic(
  () => import('./Twin3DViewer').then(module => module.Twin3DViewer),
  { loading: () => <div className="assistant-model-loading" aria-live="polite">3D…</div>, ssr: false },
);

const ignoreSelection = () => {};

export function DrawingModelReceipt({ model }: { model: DrawingModelSnapshot }) {
  const t = useTranslations('Drawings');
  const checks = Object.entries(model.validation?.checks && typeof model.validation.checks === 'object'
    ? model.validation.checks as Record<string, unknown>
    : {});
  const validationStatus = typeof model.validation?.status === 'string' ? model.validation.status : 'UNKNOWN';

  return <section className="assistant-model-receipt" aria-label={t('modelTitle')}>
    <header>
      <div><span>{t('modelKicker')}</span><b>{t('modelSynced')}</b></div>
      <strong>{model.version ?? t('draftVersion')}</strong>
    </header>
    {model.gltfUrl && model.objects.length ? <Twin3DViewer url={model.gltfUrl} objects={model.objects} onSelect={ignoreSelection} draftMode /> : null}
    <div className="assistant-model-artifacts">
      {model.artifacts.map(artifact => <a href={artifact.url} target="_blank" rel="noreferrer" key={`${artifact.type}-${artifact.url}`}>
        <span>{artifact.type}</span><b>{t('download')}</b><small>{artifact.sha256 ? artifact.sha256.slice(0, 16) : t('contentAddressed')}</small>
      </a>)}
    </div>
    <footer>
      <span>{t('validation')} · {validationStatus}</span>
      {checks.map(([key, value]) => <b className={value === true ? 'passed' : 'failed'} key={key}>{value === true ? '✓' : '✕'} {key}</b>)}
    </footer>
    <p>{t('modelAutoSynced')}</p>
  </section>;
}
