'use client';

import Link from 'next/link';
import { useCallback, useEffect, useState } from 'react';
import { useLocale, useTranslations } from 'next-intl';

type Step = { id: string; text: string; owner_role: string; due: string; source: string };
type Question = { id: number; question: string; status: string; answer: string | null };
type Report = {
  id: string; event_type: string; description: string; captured_at: string; analysis_status: string; case_id: string | null;
  attachments: { name: string; media_type: string; sha256: string; url: string | null }[];
  risk_review: { reported: string; ai: string | null; final: string; raised: boolean };
  case: { status: string; type: string; deadline: string } | null; plan: Step[]; questions: Question[];
};

export const FIELD_SYNCED_EVENT = 'globalinfra-field-synced';

export function FieldReports() {
  const t = useTranslations('Field');
  const ta = useTranslations('Assistant');
  const locale = useLocale();
  const [reports, setReports] = useState<Report[] | null>(null);
  const [answers, setAnswers] = useState<Record<number, string>>({});
  const [busy, setBusy] = useState(0);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    try {
      const response = await fetch(`/backend/field/reports?limit=10&lang=${locale}`);
      if (!response.ok) throw new Error(String(response.status));
      setReports(await response.json());
    } catch {
      setReports(previous => previous ?? []);
    }
  }, [locale]);

  useEffect(() => {
    load();
    const refresh = () => load();
    window.addEventListener(FIELD_SYNCED_EVENT, refresh);
    return () => window.removeEventListener(FIELD_SYNCED_EVENT, refresh);
  }, [load]);

  // Analysis runs in the background after sync; poll until it settles.
  useEffect(() => {
    if (!reports?.some(r => r.analysis_status === 'PENDING')) return;
    const timer = setTimeout(load, 4000);
    return () => clearTimeout(timer);
  }, [reports, load]);

  async function answer(report: Report, question: Question) {
    const text = (answers[question.id] ?? '').trim();
    if (!text || !report.case_id) return;
    setBusy(question.id); setError('');
    try {
      const response = await fetch(`/backend/cases/${report.case_id}/inputs`, {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ input_id: question.id, answer: text }),
      });
      if (!response.ok) throw new Error(String(response.status));
      await load();
    } catch {
      setError(t('answerFailed'));
    } finally { setBusy(0); }
  }

  const label = (group: string, code: string, scope = t) => scope.has(`${group}.${code}`) ? scope(`${group}.${code}`) : code;

  return <section className="card card-pad field-reports">
    <div className="section-kicker">{t('reportsKicker')}</div>
    <h3>{t('reportsTitle')}</h3>
    {reports === null && <p className="muted">{t('loading')}</p>}
    {reports?.length === 0 && <p className="muted">{t('reportsEmpty')}</p>}
    {error && <p className="field-status" role="alert">{error}</p>}
    <div className="field-report-list">{reports?.map(report => {
      const actions = report.plan.filter(step => !step.source.startsWith('governance')).slice(0, 3);
      const open = report.questions.filter(q => q.status === 'OPEN');
      return <article key={report.id} className={`field-report ${report.analysis_status.toLowerCase()}`}>
        <header>
          <span className="badge info">{label('eventTypes', report.event_type)}</span>
          <span className={`badge ${report.risk_review.final.toLowerCase()}`}>{report.risk_review.final}</span>
          <span className="field-report-state">{label('analysis', report.analysis_status)}</span>
          <time>{new Date(report.captured_at).toLocaleString(locale === 'zh' ? 'zh-CN' : 'en-GB', { dateStyle: 'short', timeStyle: 'short' })}</time>
        </header>
        <p className="field-report-text">{report.description}</p>
        {report.attachments.some(a => a.url) && <div className="field-report-media">{report.attachments.filter(a => a.url).map(a =>
          a.media_type.startsWith('image/') ? <a key={a.sha256} href={a.url!} target="_blank" rel="noopener noreferrer"><img src={a.url!} alt={a.name} loading="lazy" /></a>
          : a.media_type.startsWith('audio/') ? <audio key={a.sha256} controls preload="none" src={a.url!} />
          : <a key={a.sha256} href={a.url!} target="_blank" rel="noopener noreferrer">{a.name}</a>)}</div>}
        {report.risk_review.raised && <p className="field-report-raised">{t('riskRaised', { reported: report.risk_review.reported, final: report.risk_review.final })}</p>}
        {report.case && report.analysis_status === 'ANALYZED' && <>
          <p className="muted small">{report.case.type} · {label('statuses', report.case.status, ta)} · {report.case.deadline}</p>
          {actions.length > 0 && <ol className="field-report-plan">{actions.map(step => <li key={step.id}>{step.text}<small> · {step.owner_role}</small></li>)}</ol>}
          {open.map(question => <div key={question.id} className="field-report-question">
            <p><b>{t('agentAsks')}</b>{question.question}</p>
            <div className="assistant-question-row">
              <input value={answers[question.id] ?? ''} placeholder={t('answerPlaceholder')}
                onChange={event => setAnswers(previous => ({ ...previous, [question.id]: event.target.value }))} />
              <button className="button" type="button" disabled={!!busy || !(answers[question.id] ?? '').trim()} onClick={() => answer(report, question)}>
                {busy === question.id ? t('reanalyzing') : t('answer')}
              </button>
            </div>
          </div>)}
        </>}
        {report.case_id && <Link className="field-report-link" href={`/cases/${report.case_id}`}>{t('openCase')} →</Link>}
      </article>;
    })}</div>
  </section>;
}
