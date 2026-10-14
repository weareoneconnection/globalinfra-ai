'use client';

import { FormEvent, useState } from 'react';
import { useLocale, useTranslations } from 'next-intl';
import { useRouter } from 'next/navigation';

type Project = { id: number; code: string; name: string; country_code: string; domain: string };
type Props = { projects: Project[] };

const CASE_TYPES = ['HSE', 'Quality', 'Engineering / RFI', 'Contract / Commercial', 'Progress / Schedule', 'Procurement', 'Change', 'Commissioning'];
const RISK_LEVELS = ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL'];

function errorMessage(detail: unknown, fallback: string): string {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) return detail.map(item => typeof item === 'object' && item && 'msg' in item ? String(item.msg) : String(item)).join(' · ');
  return fallback;
}

export function CaseCreateForm({ projects }: Props) {
  const t = useTranslations('CaseCreate');
  const locale = useLocale();
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError('');
    const data = new FormData(event.currentTarget);
    const language = String(data.get('language') ?? '');
    const text = [
      String(data.get('title')),
      `Work order type: ${data.get('case_type')}`,
      `Declared risk: ${data.get('risk')}`,
      `Required response: ${data.get('deadline')}`,
      `Description: ${data.get('description')}`,
    ].join('\n');

    try {
      const response = await fetch(`/backend/intake/text?lang=${locale}`, {
        method: 'POST',
        headers: { 'content-type': 'application/json', 'accept-language': locale },
        body: JSON.stringify({
          text,
          project_id: Number(data.get('project_id')),
          entry_type: 'work_order',
          language: language || null,
          model_route: data.get('model_route'),
          data_classification: data.get('classification'),
        }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(errorMessage(body.detail, t('failed')));
      if (typeof body.case_id !== 'string') throw new Error(t('missingCase'));
      router.push(`/cases/${body.case_id}`);
      router.refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t('failed'));
      setBusy(false);
    }
  }

  return <div className="case-create-layout">
    <form className="card case-create-form" onSubmit={submit}>
      <div className="section-title"><div><span className="section-kicker">01 · {t('detailsKicker')}</span><h3>{t('detailsTitle')}</h3></div><span className="badge info">WORK ORDER</span></div>
      <div className="case-create-fields">
        <label className="wide"><span>{t('fields.project')}</span><select name="project_id" required defaultValue={String(projects[0]?.id ?? '')}>{projects.map(project => <option key={project.id} value={project.id}>{project.code} · {project.name}</option>)}</select><small>{t('fields.projectHint')}</small></label>
        <label><span>{t('fields.type')}</span><select name="case_type" defaultValue="Engineering / RFI">{CASE_TYPES.map(value => <option key={value}>{value}</option>)}</select></label>
        <label><span>{t('fields.risk')}</span><select name="risk" defaultValue="HIGH">{RISK_LEVELS.map(value => <option key={value}>{value}</option>)}</select></label>
        <label className="wide"><span>{t('fields.workTitle')}</span><input name="title" minLength={4} maxLength={118} placeholder={t('fields.titlePlaceholder')} required /></label>
        <label className="wide"><span>{t('fields.description')}</span><textarea name="description" minLength={10} maxLength={10000} rows={7} placeholder={t('fields.descriptionPlaceholder')} required /></label>
        <label><span>{t('fields.deadline')}</span><select name="deadline" defaultValue="24 hours"><option>Immediate</option><option>24 hours</option><option>48 hours</option><option>72 hours</option><option>7 days</option></select></label>
        <label><span>{t('fields.language')}</span><select name="language" defaultValue=""><option value="">{t('fields.autoDetect')}</option><option value="zh">中文</option><option value="en">English</option><option value="ms">Bahasa Melayu</option><option value="id">Bahasa Indonesia</option><option value="ar">العربية</option></select></label>
      </div>
      <div className="case-create-governance">
        <label><span>{t('fields.classification')}</span><select name="classification" defaultValue="internal"><option value="public">Public</option><option value="internal">Internal</option><option value="restricted">Restricted</option></select></label>
        <label><span>{t('fields.modelRoute')}</span><select name="model_route" defaultValue="auto"><option value="auto">Auto</option><option value="local">Local</option><option value="openai">OpenAI</option></select></label>
      </div>
      {error ? <p className="case-create-error" role="alert">{error}</p> : null}
      <footer><div><span className="status-dot" />{t('governance')}</div><button className="button" disabled={busy} type="submit">{busy ? t('creating') : t('create')}</button></footer>
    </form>

    <aside className="card case-create-guide">
      <div className="section-title"><div><span className="section-kicker">02 · {t('routeKicker')}</span><h3>{t('routeTitle')}</h3></div></div>
      <ol>
        <li><span>01</span><div><b>{t('steps.intake')}</b><p>{t('steps.intakeDesc')}</p></div></li>
        <li><span>02</span><div><b>{t('steps.classify')}</b><p>{t('steps.classifyDesc')}</p></div></li>
        <li><span>03</span><div><b>{t('steps.evidence')}</b><p>{t('steps.evidenceDesc')}</p></div></li>
        <li><span>04</span><div><b>{t('steps.receipt')}</b><p>{t('steps.receiptDesc')}</p></div></li>
      </ol>
      <div className="case-create-boundary"><span>{t('boundaryKicker')}</span><p>{t('boundary')}</p></div>
    </aside>
  </div>;
}
