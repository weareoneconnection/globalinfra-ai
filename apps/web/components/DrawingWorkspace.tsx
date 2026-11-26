'use client';

import { FormEvent, useEffect, useMemo, useState } from 'react';
import Image from 'next/image';
import dynamic from 'next/dynamic';
import { useLocale, useTranslations } from 'next-intl';
import type { TwinObject } from './TwinWorkspace';

const Twin3DViewer = dynamic(
  () => import('./Twin3DViewer').then(module => module.Twin3DViewer),
  { ssr: false },
);

type Project = { id: number; code: string; name: string };
type BBox = [number, number, number, number];
type Scalar = string | number | boolean | null;

type Sheet = {
  id?: string | number;
  page?: number;
  page_number?: number;
  name?: string;
  width?: number;
  height?: number;
  preview_url?: string;
  image_url?: string;
};

type Evidence = {
  page?: number;
  page_number?: number;
  bbox?: BBox | number[];
  text?: string;
  source_text?: string;
};

type DrawingElement = {
  id?: string | number;
  element_id?: string;
  type?: string;
  category?: string;
  name?: string;
  label?: string;
  value?: Scalar;
  unit?: string;
  confidence?: number;
  status?: string;
  state?: string;
  extraction_method?: string;
  page?: number;
  page_number?: number;
  bbox?: BBox | number[];
  evidence?: Evidence;
  properties?: Record<string, unknown>;
};

type ModelGate = {
  ready?: boolean;
  model_ready?: boolean;
  missing?: string[];
  missing_fields?: string[];
  blockers?: string[];
  reasons?: string[];
};

type DrawingDetail = {
  id: string;
  status: string;
  document: Record<string, unknown>;
  sheets: Sheet[];
  elements: DrawingElement[];
  analysis: Record<string, unknown>;
  modelGate: ModelGate;
};

type Citation = Evidence & { id?: string | number; element_id?: string; label?: string };
type AskResult = { answer: string; citations: Citation[]; confidence?: number };
type Artifact = { type: string; url: string; sha256?: string; bytes?: number };
export type DrawingModelSnapshot = {
  status: string;
  version?: string;
  gltfUrl?: string;
  artifacts: Artifact[];
  validation: Record<string, unknown>;
  objects: TwinObject[];
};

export type DrawingReviewUpdate = {
  drawingId: string;
  action: 'refreshed' | 'confirmed' | 'model_generated';
  detail?: unknown;
  model?: DrawingModelSnapshot;
};

type DraftModel = DrawingModelSnapshot;

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function list<T>(value: unknown): T[] {
  return Array.isArray(value) ? value as T[] : [];
}

function text(value: unknown, fallback = ''): string {
  return typeof value === 'string' || typeof value === 'number' ? String(value) : fallback;
}

function isFootprintElement(item: DrawingElement): boolean {
  return ['RECTANGLE_FOOTPRINT', 'POLYGON_FOOTPRINT']
    .includes(text(item.properties?.geometry_type).toUpperCase());
}

function reviewPriority(item: DrawingElement): number {
  if (isFootprintElement(item)) return 3;
  if (text(item.label).endsWith('_schedule_row')) return 2;
  return 1;
}

function normalizeDrawing(payload: unknown): DrawingDetail {
  const body = record(payload);
  const raw = record(body.drawing ?? body.result ?? body);
  const document = record(raw.document ?? raw.source_document ?? raw);
  const analysis = record(raw.analysis ?? body.analysis);
  const modelGate = record(raw.model_gate ?? analysis.model_gate ?? body.model_gate) as ModelGate;
  const sheets = list<Sheet>(raw.sheets ?? analysis.sheets);
  const elements = list<DrawingElement>(raw.elements ?? analysis.elements ?? analysis.entities);
  return {
    id: text(raw.id ?? raw.drawing_id ?? document.id),
    status: text(raw.status ?? analysis.status, 'ANALYZED'),
    document,
    sheets: sheets.length ? sheets : [{ page: 1, name: text(document.filename, 'Sheet 1') }],
    elements,
    analysis,
    modelGate,
  };
}

function normalizeAsk(payload: unknown): AskResult {
  const body = record(payload);
  const raw = record(body.result ?? body);
  return {
    answer: text(raw.answer ?? raw.response ?? raw.text),
    citations: list<Citation>(raw.citations ?? raw.evidence),
    confidence: typeof raw.confidence === 'number' ? raw.confidence : undefined,
  };
}

function artifactType(value: unknown): string {
  return text(record(value).type ?? record(value).format ?? record(value).artifact_type).toUpperCase();
}

function normalizeModel(payload: unknown, drawingId: string): DraftModel {
  const body = record(payload);
  const raw = record(body.model ?? body.result ?? body);
  const manifest = record(raw.manifest);
  const artifacts = list<Record<string, unknown>>(raw.artifacts ?? manifest.artifacts).map(item => ({
    type: artifactType(item),
    url: text(item.url ?? item.href ?? item.download_url),
    sha256: text(item.sha256) || undefined,
    bytes: typeof item.bytes === 'number' ? item.bytes : undefined,
  })).filter(item => item.url);
  const gltf = artifacts.find(item => item.type === 'GLTF' || item.type === 'GLB');
  const rawObjects = list<Record<string, unknown>>(raw.objects ?? manifest.objects);
  const objects: TwinObject[] = rawObjects.map((item, index) => ({
    id: text(item.twin_id ?? item.id, `DRAWING-${drawingId}-${index + 1}`),
    parent_id: text(item.parent_id) || null,
    object_type: text(item.object_type ?? item.type, 'DRAFT_ELEMENT'),
    name: text(item.name ?? item.label, `Draft element ${index + 1}`),
    lifecycle_stage: 'design',
    status: text(item.status, 'AI_GENERATED_DRAFT'),
    health_score: 100,
    progress: 0,
    geometry_ref: text(item.geometry_ref) || null,
    location: record(item.location) as Record<string, string | number>,
    properties: record(item.properties) as Record<string, string | number>,
  }));
  return {
    status: text(raw.status, 'DRAFT_GENERATED'),
    version: text(raw.version ?? manifest.version) || undefined,
    gltfUrl: text(raw.gltf_url ?? gltf?.url) || undefined,
    artifacts,
    validation: record(raw.validation ?? manifest.validation),
    objects,
  };
}

function pageOf(value: DrawingElement | Citation): number {
  if (typeof value.page === 'number') return Math.max(1, value.page);
  if (typeof value.page_number === 'number') return Math.max(1, value.page_number);
  if ('evidence' in value && value.evidence) {
    if (typeof value.evidence.page === 'number') return Math.max(1, value.evidence.page);
    if (typeof value.evidence.page_number === 'number') return Math.max(1, value.evidence.page_number);
  }
  return 1;
}

function bboxOf(value: DrawingElement | Citation): number[] | undefined {
  const raw = value.bbox ?? ('evidence' in value ? value.evidence?.bbox : undefined);
  return Array.isArray(raw) && raw.length === 4 && raw.every(number => typeof number === 'number') ? raw : undefined;
}

function normalizedBox(value: DrawingElement | Citation, sheet: Sheet): BBox | null {
  const box = bboxOf(value);
  if (!box) return null;
  const max = Math.max(...box.map(Math.abs));
  const width = max <= 1 ? 1 : Math.max(1, Number(sheet.width ?? max));
  const height = max <= 1 ? 1 : Math.max(1, Number(sheet.height ?? max));
  const clamp = (number: number) => Math.max(0, Math.min(1, number));
  const x0 = clamp(box[0] / width);
  const y0 = clamp(box[1] / height);
  const x1 = clamp(box[2] / width);
  const y1 = clamp(box[3] / height);
  if (x1 <= x0 || y1 <= y0) return null;
  return [x0, y0, x1, y1];
}

function confidenceOf(value: DrawingElement): number {
  const raw = typeof value.confidence === 'number' ? value.confidence : 0;
  return Math.max(0, Math.min(100, raw <= 1 ? raw * 100 : raw));
}

function confirmedParameterValue(detail: DrawingDetail, label: string): string {
  const parameter = detail.elements.find(item =>
    text(item.type ?? item.category).toUpperCase() === 'PARAMETER'
    && text(item.label).toLowerCase() === label
    && text(item.state ?? item.status).toUpperCase() === 'USER_CONFIRMED'
  );
  return text(parameter?.value);
}

function fieldRows(detail: DrawingDetail): [string, Scalar][] {
  const metadata = record(detail.analysis.metadata ?? detail.analysis.fields ?? detail.document.metadata);
  const preferred = ['drawing_number', 'title', 'discipline', 'revision', 'date', 'scale', 'unit', 'project'];
  const entries = Object.entries(metadata).filter(([, value]) => ['string', 'number', 'boolean'].includes(typeof value)) as [string, Scalar][];
  return entries.sort(([a], [b]) => {
    const ai = preferred.indexOf(a);
    const bi = preferred.indexOf(b);
    return (ai < 0 ? 99 : ai) - (bi < 0 ? 99 : bi);
  }).slice(0, 12);
}

function errorMessage(payload: unknown, fallback: string): string {
  const body = record(payload);
  const detail = body.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) return detail.map(item => text(record(item).msg)).filter(Boolean).join(' · ') || fallback;
  if (detail && typeof detail === 'object') return text(record(detail).message ?? record(detail).code, fallback);
  return fallback;
}

async function jsonResponse(response: Response): Promise<unknown> {
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(errorMessage(body, `Request failed (${response.status})`));
  return body;
}

function EvidenceStage({ detail, activePage, selected, onSelect, localPreview, previewIsImage }: {
  detail: DrawingDetail;
  activePage: number;
  selected: string;
  onSelect: (id: string) => void;
  localPreview: string;
  previewIsImage: boolean;
}) {
  const t = useTranslations('Drawings');
  const [overlayMode, setOverlayMode] = useState<'review' | 'selected' | 'all'>('review');
  const sheet = detail.sheets.find(item => (item.page ?? item.page_number ?? 1) === activePage) ?? detail.sheets[activePage - 1] ?? detail.sheets[0];
  const sheetWidth = Math.max(1, Number(sheet?.width ?? 1));
  const sheetHeight = Math.max(1, Number(sheet?.height ?? 1));
  const remotePreview = sheet?.preview_url ?? sheet?.image_url ?? '';
  const preview = remotePreview || (previewIsImage ? localPreview : '');
  const allPageElements = detail.elements.filter(item => pageOf(item) === activePage && normalizedBox(item, sheet));
  const filteredElements = overlayMode === 'selected'
    ? allPageElements.filter((item, index) => text(item.id ?? item.element_id, `element-${index}`) === selected)
    : overlayMode === 'review'
      ? allPageElements.filter(item => text(item.id ?? item.element_id) === selected || confidenceOf(item) < 80 || text(item.state ?? item.status).toUpperCase() === 'INFERRED')
      : allPageElements;
  const pageElements = [...filteredElements]
    .sort((a, b) => Number(text(b.id ?? b.element_id) === selected) - Number(text(a.id ?? a.element_id) === selected))
    .slice(0, overlayMode === 'all' ? 500 : 120);
  return <div className="drawing-sheet-stage">
    <div className="drawing-sheet-toolbar">
      <span>{t('sheet')} {activePage}</span>
      <div className="drawing-overlay-controls" role="group" aria-label={t('anchors')}>
        {(['review', 'selected', 'all'] as const).map(mode => <button type="button" className={overlayMode === mode ? 'active' : ''} onClick={() => setOverlayMode(mode)} key={mode}>{t(`overlay.${mode}`)}</button>)}
      </div>
      <small>{t('overlay.shown', { shown: pageElements.length, total: allPageElements.length })}</small>
    </div>
    <div className={`drawing-sheet ${preview ? 'has-preview' : ''}`} style={{ aspectRatio: `${sheetWidth} / ${sheetHeight}` }}>
      {preview ? <Image src={preview} alt={t('previewAlt', { page: activePage })} fill sizes="(max-width: 900px) 100vw, 55vw" unoptimized /> : <div className="drawing-sheet-placeholder" aria-label={t('previewAlt', { page: activePage })}>
        <span>DRAWING · {activePage.toString().padStart(2, '0')}</span>
        <i /><i /><i /><b>{text(sheet?.name, t('sheetFallback'))}</b>
      </div>}
      <div className="drawing-evidence-layer">
        {pageElements.map((element, index) => {
          const id = text(element.id ?? element.element_id, `element-${index}`);
          const box = normalizedBox(element, sheet)!;
          return <button
            type="button"
            key={id}
            className={`drawing-anchor ${selected === id ? 'active' : ''} ${confidenceOf(element) < 70 ? 'uncertain' : ''}`}
            style={{ left: `${box[0] * 100}%`, top: `${box[1] * 100}%`, width: `${(box[2] - box[0]) * 100}%`, height: `${(box[3] - box[1]) * 100}%` }}
            aria-label={`${text(element.label ?? element.name ?? element.type, t('unnamedElement'))}, ${Math.round(confidenceOf(element))}%`}
            onClick={() => onSelect(id)}
          ><span>{text(element.type ?? element.category, 'E')}</span></button>;
        })}
      </div>
    </div>
  </div>;
}

function GatePanel({ gate }: { gate: ModelGate }) {
  const t = useTranslations('Drawings');
  const ready = Boolean(gate.ready ?? gate.model_ready);
  const missing = gate.blockers ?? gate.missing ?? gate.missing_fields ?? gate.reasons ?? [];
  return <div className={`drawing-gate ${ready ? 'ready' : 'blocked'}`}>
    <span>{ready ? '✓' : '!'}</span>
    <div><b>{ready ? t('gateReady') : t('gateBlocked')}</b><p>{ready ? t('gateReadyHint') : missing.length ? missing.join(' · ') : t('gateBlockedHint')}</p></div>
  </div>;
}

export function DrawingWorkspace({ projects, initialDrawingId = '', initialPage = 1, initialElementId = '', reviewMode = false, onUpdate }: {
  projects: Project[];
  initialDrawingId?: string;
  initialPage?: number;
  initialElementId?: string;
  reviewMode?: boolean;
  onUpdate?: (update: DrawingReviewUpdate) => void;
}) {
  const t = useTranslations('Drawings');
  const locale = useLocale();
  const [detail, setDetail] = useState<DrawingDetail | null>(null);
  const [activePage, setActivePage] = useState(1);
  const [selected, setSelected] = useState('');
  const [localPreview, setLocalPreview] = useState('');
  const [previewIsImage, setPreviewIsImage] = useState(false);
  const [phase, setPhase] = useState<'idle' | 'uploading' | 'analyzing' | 'ready' | 'error'>('idle');
  const [error, setError] = useState('');
  const [question, setQuestion] = useState('');
  const [asking, setAsking] = useState(false);
  const [answer, setAnswer] = useState<AskResult | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [model, setModel] = useState<DraftModel | null>(null);

  useEffect(() => () => { if (localPreview) URL.revokeObjectURL(localPreview); }, [localPreview]);

  useEffect(() => {
    if (!initialDrawingId) return;
    let cancelled = false;
    setPhase('analyzing');
    setError('');
    fetch(`/backend/drawings/${encodeURIComponent(initialDrawingId)}?lang=${locale}`, { cache: 'no-store' })
      .then(jsonResponse)
      .then(payload => {
        if (cancelled) return;
        setDetail(normalizeDrawing(payload));
        setActivePage(Math.max(1, initialPage));
        setSelected(initialElementId);
        setPhase('ready');
      })
      .catch(reason => {
        if (cancelled) return;
        setError(reason instanceof Error ? reason.message : 'Drawing operation failed.');
        setPhase('error');
      });
    return () => { cancelled = true; };
  }, [initialDrawingId, initialElementId, initialPage, locale]);

  const rows = useMemo(() => detail ? fieldRows(detail) : [], [detail]);
  const geometryCandidates = useMemo(() => {
    const candidates = detail?.elements.filter(item => {
      const type = text(item.type ?? item.category).toUpperCase();
      const geometryType = text(item.properties?.geometry_type).toUpperCase();
      return ['WALL', 'DOOR', 'SPACE', 'EQUIPMENT'].includes(type)
        && ['LINE', 'RECTANGLE_FOOTPRINT', 'POLYGON_FOOTPRINT'].includes(geometryType);
    }) ?? [];
    return [...candidates].sort((left, right) =>
      Number(isFootprintElement(right)) - Number(isFootprintElement(left))
    );
  }, [detail]);
  const reviewElements = useMemo(() => {
    if (!detail) return [];
    return [...detail.elements]
      .sort((left, right) => reviewPriority(right) - reviewPriority(left))
      .slice(0, 18);
  }, [detail]);
  const gateReady = Boolean(detail?.modelGate.ready ?? detail?.modelGate.model_ready);
  const selectedElement = detail?.elements.find((item, index) => text(item.id ?? item.element_id, `element-${index}`) === selected);
  const sourceUnit = text(detail?.document.unit).trim().toLowerCase();
  const sourceScale = text(detail?.document.scale).trim();
  const unitOptions = ['m', 'mm', 'cm'];
  const confirmedStoreyHeight = detail ? confirmedParameterValue(detail, 'height') : '';
  const confirmedWallThickness = detail ? confirmedParameterValue(detail, 'wall_thickness') : '';
  const workflowActive = [
    true,
    Boolean(detail),
    gateReady,
    Boolean(model),
    Boolean(model) && text(model?.validation.status).toUpperCase() === 'PASSED',
  ];

  async function pollDrawing(id: string) {
    for (let attempt = 0; attempt < 20; attempt += 1) {
      const response = await fetch(`/backend/drawings/${encodeURIComponent(id)}?lang=${locale}`, { cache: 'no-store' });
      const payload = await jsonResponse(response);
      const next = normalizeDrawing(payload);
      setDetail(next);
      if (!['QUEUED', 'PROCESSING', 'ANALYZING'].includes(next.status.toUpperCase())) return next;
      await new Promise(resolve => setTimeout(resolve, 1200));
    }
    throw new Error(t('analysisTimeout'));
  }

  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPhase('uploading');
    setError('');
    setAnswer(null);
    setModel(null);
    const data = new FormData(event.currentTarget);
    const file = data.get('file');
    if (!(file instanceof File) || !file.size) {
      setError(t('fileRequired'));
      setPhase('error');
      return;
    }
    if (localPreview) URL.revokeObjectURL(localPreview);
    setLocalPreview(URL.createObjectURL(file));
    setPreviewIsImage(file.type.startsWith('image/'));
    try {
      const response = await fetch(`/backend/drawings/analyze?lang=${locale}`, {
        method: 'POST', headers: { 'accept-language': locale }, body: data,
      });
      const payload = await jsonResponse(response);
      let next = normalizeDrawing(payload);
      setDetail(next);
      setPhase('analyzing');
      if (['QUEUED', 'PROCESSING', 'ANALYZING'].includes(next.status.toUpperCase()) && next.id) next = await pollDrawing(next.id);
      setDetail(next);
      setActivePage(1);
      setSelected('');
      setPhase('ready');
      if (next.id && typeof window !== 'undefined') {
        const url = new URL(window.location.href);
        url.searchParams.set('drawing_id', next.id);
        url.searchParams.set('from', 'workbench');
        window.history.replaceState(null, '', url);
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t('unknownError'));
      setPhase('error');
    }
  }

  async function ask(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!detail?.id || !question.trim()) return;
    setAsking(true);
    setError('');
    try {
      const response = await fetch(`/backend/drawings/${encodeURIComponent(detail.id)}/ask?lang=${locale}`, {
        method: 'POST', headers: { 'content-type': 'application/json', 'accept-language': locale }, body: JSON.stringify({ question: question.trim() }),
      });
      setAnswer(normalizeAsk(await jsonResponse(response)));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t('unknownError'));
    } finally { setAsking(false); }
  }

  async function confirm(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!detail?.id) return;
    setConfirming(true);
    setError('');
    const data = new FormData(event.currentTarget);
    const value = (name: string) => String(data.get(name) ?? '').trim();
    try {
      const geometryId = value('geometry_element_id');
      const geometry = detail.elements.find(item => text(item.id ?? item.element_id) === geometryId);
      const sourceCalibration = value('source_calibration_m_per_pixel');
      const response = await fetch(`/backend/drawings/${encodeURIComponent(detail.id)}/confirm?lang=${locale}`, {
        method: 'POST', headers: { 'content-type': 'application/json', 'accept-language': locale },
        body: JSON.stringify({
          field: geometryId || undefined,
          value: geometry ? text(geometry.value ?? geometry.label ?? geometry.name, geometryId) : undefined,
          unit: value('unit'), scale: value('scale'),
          storey_height_m: Number(value('storey_height_m')),
          wall_thickness_m: Number(value('wall_thickness_m')),
          ...(sourceCalibration ? { source_calibration_m_per_pixel: Number(sourceCalibration) } : {}),
        }),
      });
      const payload = await jsonResponse(response);
      const next = normalizeDrawing(payload);
      setDetail(next);
      onUpdate?.({ drawingId: next.id, action: 'confirmed', detail: payload });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t('unknownError'));
    } finally { setConfirming(false); }
  }

  async function generateModel() {
    if (!detail?.id || !gateReady) return;
    setGenerating(true);
    setError('');
    try {
      const response = await fetch(`/backend/drawings/${encodeURIComponent(detail.id)}/model?lang=${locale}`, {
        method: 'POST', headers: { 'content-type': 'application/json', 'accept-language': locale },
        body: JSON.stringify({ formats: ['GLTF', 'IFC'], publish: false }),
      });
      const next = normalizeModel(await jsonResponse(response), detail.id);
      setModel(next);
      onUpdate?.({ drawingId: detail.id, action: 'model_generated', model: next });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t('unknownError'));
    } finally { setGenerating(false); }
  }

  function selectCitation(citation: Citation) {
    const page = pageOf(citation);
    setActivePage(page);
    const id = text(citation.element_id ?? citation.id);
    if (id) setSelected(id);
  }

  function selectModelObject(twinId: string) {
    const object = model?.objects.find(item => item.id === twinId);
    const sourceId = text(object?.properties?.source_element_id);
    setSelected(sourceId);
    const source = detail?.elements.find(item => text(item.id ?? item.element_id) === sourceId);
    if (source) setActivePage(pageOf(source));
  }

  return <div className={`drawing-console ${reviewMode ? 'assistant-review' : ''}`}>
    <section className="drawing-trust-strip">
      <span>DRAWING → EVIDENCE → TWIN</span><b>{t('trustStatement')}</b><small>AI_GENERATED_DRAFT · NOT_FOR_CONSTRUCTION</small>
    </section>

    <section className="drawing-steps" aria-label={t('workflow')}>
      {['upload', 'understand', 'confirm', 'generate', 'verify'].map((key, index) => <div className={workflowActive[index] ? 'active' : ''} key={key}><span>0{index + 1}</span><b>{t(`steps.${key}`)}</b></div>)}
    </section>

    <div className="drawing-layout">
      {!reviewMode ? <section className="card drawing-source-panel">
        <header><div><span className="section-kicker">P0 · {t('sourceKicker')}</span><h3>{t('sourceTitle')}</h3></div><span className={`badge ${phase === 'error' ? 'high' : phase === 'ready' ? 'ok' : 'info'}`}>{t(`phase.${phase}`)}</span></header>
        <form onSubmit={upload}>
          <label><span>{t('project')}</span><select name="project_id" defaultValue={String(projects[0]?.id ?? '')} required>{projects.map(project => <option value={project.id} key={project.id}>{project.code} · {project.name}</option>)}</select></label>
          <label><span>{t('drawingFile')}</span><input name="file" type="file" accept=".pdf,.png,.jpg,.jpeg,.tif,.tiff,application/pdf,image/png,image/jpeg,image/tiff" required /></label>
          <label><span>{t('classification')}</span><select name="data_classification" defaultValue="internal"><option value="internal">{t('classificationOptions.internal')}</option><option value="restricted">{t('classificationOptions.restricted')}</option><option value="public">{t('classificationOptions.public')}</option></select></label>
          <button className="button" type="submit" disabled={phase === 'uploading' || phase === 'analyzing'}>{phase === 'uploading' || phase === 'analyzing' ? t('processing') : t('analyze')}</button>
        </form>
        <p className="drawing-boundary">{t('uploadBoundary')}</p>
        {detail ? <div className="drawing-document-receipt"><span>SHA-256</span><code>{text(detail.document.sha256 ?? detail.document.checksum ?? detail.document.storage_ref, '—')}</code><small>{text(detail.document.filename, t('uploadedDrawing'))} · {detail.status}</small></div> : null}
      </section> : null}

      <section className="card drawing-canvas-panel">
        <header><div><span className="section-kicker">P0 · {t('evidenceKicker')}</span><h3>{t('evidenceTitle')}</h3></div>{detail && <div className="drawing-page-tabs">{detail.sheets.map((sheet, index) => { const page = sheet.page ?? sheet.page_number ?? index + 1; return <button type="button" className={activePage === page ? 'active' : ''} onClick={() => setActivePage(page)} key={String(sheet.id ?? page)}>{page}</button>; })}</div>}</header>
        {detail ? <EvidenceStage detail={detail} activePage={activePage} selected={selected} onSelect={setSelected} localPreview={localPreview} previewIsImage={previewIsImage} /> : <div className="drawing-empty"><span>⌁</span><b>{phase === 'analyzing' && initialDrawingId ? t('loadingDrawing') : t('emptyTitle')}</b><p>{t('emptyHint')}</p></div>}
      </section>

      <aside className="card drawing-analysis-panel">
        <header><div><span className="section-kicker">P0 · {t('analysisKicker')}</span><h3>{t('analysisTitle')}</h3></div><span className="badge info">{detail?.elements.length ?? 0}</span></header>
        {detail ? <>
          <div className="drawing-metadata">{rows.length ? rows.map(([key, value]) => <div key={key}><span>{key.replaceAll('_', ' ')}</span><b>{String(value)}</b></div>) : <p>{t('noMetadata')}</p>}</div>
          {selectedElement ? <div className="drawing-selected"><span>{text(selectedElement.type ?? selectedElement.category, 'ELEMENT')}</span><b>{text(selectedElement.label ?? selectedElement.name ?? selectedElement.value, t('unnamedElement'))}</b><small>{t('confidence')} {Math.round(confidenceOf(selectedElement))}% · {t('sheet')} {pageOf(selectedElement)}</small><p>{text(selectedElement.evidence?.source_text ?? selectedElement.evidence?.text, t('noSourceText'))}</p></div> : null}
          <div className="drawing-element-list">{reviewElements.map((element, index) => { const id = text(element.id ?? element.element_id, `element-${index}`); return <button type="button" className={selected === id ? 'active' : ''} onClick={() => { setSelected(id); setActivePage(pageOf(element)); }} key={id}><span>{text(element.type ?? element.category, 'ITEM')}</span><div><b>{text(element.label ?? element.name ?? element.value, t('unnamedElement'))}</b><small>{t('sheet')} {pageOf(element)}</small></div><strong className={confidenceOf(element) < 70 ? 'low' : ''}>{Math.round(confidenceOf(element))}%</strong></button>; })}</div>
        </> : <div className="drawing-empty compact"><b>{t('analysisEmpty')}</b></div>}
      </aside>
    </div>

    {detail ? <div className="drawing-lower-grid">
      <section className="card drawing-ask-panel">
        <header><div><span className="section-kicker">COPILOT · {t('askKicker')}</span><h3>{t('askTitle')}</h3></div></header>
        <form onSubmit={ask}><input value={question} onChange={event => setQuestion(event.target.value)} placeholder={t('questionPlaceholder')} /><button className="button" disabled={asking || !question.trim()}>{asking ? t('asking') : t('ask')}</button></form>
        {answer ? <div className="drawing-answer"><p>{answer.answer}</p>{typeof answer.confidence === 'number' && <span>{t('confidence')} {Math.round((answer.confidence <= 1 ? answer.confidence * 100 : answer.confidence))}%</span>}<div>{answer.citations.map((citation, index) => <button type="button" onClick={() => selectCitation(citation)} key={`${citation.element_id ?? citation.id ?? index}`}>{t('sheet')} {pageOf(citation)} · {text(citation.label ?? citation.source_text ?? citation.text, `E${index + 1}`)}</button>)}</div></div> : <p className="drawing-ask-hint">{t('askHint')}</p>}
      </section>

      <section className="card drawing-confirm-panel">
        <header><div><span className="section-kicker">P1 · {t('confirmKicker')}</span><h3>{t('confirmTitle')}</h3></div></header>
        <GatePanel gate={detail.modelGate} />
        <form key={`confirmation-${detail.id}`} onSubmit={confirm}>
          <p className="drawing-boundary">{t('parametersRequireReview')}</p>
          <label><span>{t('unit')}</span><select name="unit" defaultValue={sourceUnit} required><option value="" disabled>{t('requiredValue')}</option>{unitOptions.map(unit => <option value={unit} key={unit}>{unit}</option>)}{sourceUnit && !unitOptions.includes(sourceUnit) ? <option value={sourceUnit}>{sourceUnit}</option> : null}</select></label>
          <label><span>{t('scale')}</span><input name="scale" defaultValue={sourceScale} placeholder="1:100" required /></label>
          <label><span>{t('storeyHeight')}</span><input name="storey_height_m" type="number" min="1" max="12" step="0.01" defaultValue={confirmedStoreyHeight} required /></label>
          <label><span>{t('wallThickness')}</span><input name="wall_thickness_m" type="number" min="0.05" max="1.5" step="0.01" defaultValue={confirmedWallThickness} required /></label>
          {text(detail.document.file_type).toLowerCase() !== 'pdf' ? <label><span>{t('sourceCalibration')}</span><input name="source_calibration_m_per_pixel" type="number" min="0.000001" max="100" step="any" required /><small>{t('sourceCalibrationHint')}</small></label> : null}
          <label className="drawing-confirm-geometry"><span>{t('geometryElement')}</span><select name="geometry_element_id" defaultValue={text(geometryCandidates[0]?.id ?? geometryCandidates[0]?.element_id)} disabled={!geometryCandidates.length}>{geometryCandidates.length ? geometryCandidates.map((element, index) => <option value={text(element.id ?? element.element_id)} key={text(element.id ?? element.element_id, String(index))}>{text(element.type ?? element.category)} · {text(element.label ?? element.name ?? element.value, t('unnamedElement'))}</option>) : <option value="">{t('noGeometry')}</option>}</select><small>{t('geometryElementHint')}</small></label>
          <button className="button secondary" disabled={confirming}>{confirming ? t('confirming') : t('confirm')}</button>
        </form>
      </section>

      <section className="card drawing-model-panel">
        <header><div><span className="section-kicker">P2 · {t('modelKicker')}</span><h3>{t('modelTitle')}</h3></div><span className="badge medium">DRAFT BIM</span></header>
        {!model ? <div className="drawing-model-cta"><div><span>IFC 4.3</span><span>glTF 2.0</span><span>TWIN ID</span></div><p>{t('modelHint')}</p><button type="button" className="button" disabled={!gateReady || generating} onClick={generateModel}>{generating ? t('generating') : t('generate')}</button></div> : <div className="drawing-model-result">
          <div className="drawing-model-status"><span>✓</span><div><b>{model.status}</b><small>{model.version ?? t('draftVersion')}</small></div></div>
          {model.gltfUrl && model.objects.length ? <Twin3DViewer url={model.gltfUrl} objects={model.objects} onSelect={selectModelObject} draftMode /> : null}
          <div className="drawing-artifacts">{model.artifacts.map(artifact => <a href={artifact.url} target="_blank" rel="noreferrer" key={`${artifact.type}-${artifact.url}`}><span>{artifact.type}</span><b>{t('download')} ↗</b><small>{artifact.sha256 ? artifact.sha256.slice(0, 12) : t('contentAddressed')}</small></a>)}</div>
          <div className="drawing-validation"><span>{t('validation')} · {text(model.validation.status, 'UNKNOWN')}</span>{Object.entries(record(model.validation.checks)).map(([key, value]) => <b key={key}>{value === true ? '✓' : '✕'} {key}</b>)}</div>
        </div>}
        <p className="drawing-not-for-construction">{t('notForConstruction')}</p>
      </section>
    </div> : null}

    {error ? <p className="drawing-error" role="alert">{error}</p> : null}
  </div>;
}
