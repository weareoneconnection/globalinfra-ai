'use client';

import Link from 'next/link';
import { ChangeEvent, FormEvent, KeyboardEvent, useCallback, useEffect, useId, useRef, useState } from 'react';
import { useLocale, useTranslations } from 'next-intl';
import { RiskBadge } from './RiskBadge';

export type AssistantProject = {
  id: number; code: string; name: string; country_name: string; phase?: string; progress?: number;
  schedule_variance?: number; next_gate?: string; gate_date?: string; risk_level: string;
};

type Mode = 'auto' | 'incident' | 'knowledge' | 'progress' | 'approvals';
type Intent = Exclude<Mode, 'auto'> | 'help' | 'caseStatus';
type Method = 'llm' | 'rules' | 'user';
type Tool = 'report_incident' | 'search_knowledge' | 'case_status' | 'project_progress' | 'pending_approvals' | 'answer_directly';
type Plan = { tool: Tool; method: Method; reply: string | null; case_id: string | null; project_id: number | null; query: string | null; hits: KnowledgeHit[] | null };

type CaseSummary = {
  caseId: string; typeLabel: string; risk: string; riskLabel: string; country: string; stage: string;
  deadline: string; issues: string[]; team: string[]; method: string;
  // Absent on conversations saved before routing was recorded.
  route?: string; classification?: string;
};
type KnowledgeHit = { id: number; title: string; source_ref: string; jurisdiction: string; version: string; summary: string; relevance: number };

type Reply =
  | { kind: 'case'; data: CaseSummary }
  | { kind: 'ocr'; message: string; filename: string }
  | { kind: 'knowledge'; query: string; hits: KnowledgeHit[]; answer?: string | null }
  | { kind: 'caseStatus'; caseId: string }
  | { kind: 'answer'; text: string }
  | { kind: 'progress'; projectId: number | null }
  | { kind: 'approvals' }
  | { kind: 'help' }
  | { kind: 'error'; message: string };

type Message =
  | { id: string; role: 'user'; text: string; fileName?: string }
  | { id: string; role: 'assistant'; intent: Intent | null; method?: Method; reply: Reply | null };

const STORAGE_KEY = 'globalinfra-assistant-v1';
// Matches workflow.CONFIDENT_RELEVANCE: below it a hit is not evidence.
const CONFIDENT_RELEVANCE = 0.22;

const HELP_RE = /^(你好|您好|嗨|hi|hello|hey)[!！。,， ]*$|你能做什么|你会做什么|你会什么|你是谁|能帮我做什么|怎么用|使用说明|^帮助$|^help$|what can you do|who are you|how do i use/i;
const INCIDENT_RE = /通知|整改|事故|隐患|损坏|破损|延误|索赔|违规|泄漏|坍塌|受伤|缺陷|notice|incident|damage|delay|claim|injur|defect|rectif|hazard|unsafe|leak/i;
const APPROVAL_RE = /审批|待我|批准|approval|approve|sign[- ]?off/i;
const PROGRESS_RE = /进度|进展|状态|概况|progress|status|schedule|overview/i;
const KNOWLEDGE_RE = /法规|法律|规定|规范|标准|条款|条例|要求|依据|哪一条|regulation|law|clause|requirement|standard|permit/i;

const INTENT_BY_TOOL: Record<Tool, Intent> = {
  report_incident: 'incident', search_knowledge: 'knowledge', case_status: 'caseStatus',
  project_progress: 'progress', pending_approvals: 'approvals', answer_directly: 'help',
};
const TOOL_BY_MODE: Partial<Record<Intent, Tool>> = {
  incident: 'report_incident', knowledge: 'search_knowledge', progress: 'project_progress', approvals: 'pending_approvals',
};

// One line per turn, so the planner can resolve "that work order" etc.
function historyLine(message: Message): string {
  if (message.role === 'user') return message.fileName ? `[file] ${message.fileName} ${message.text}` : message.text;
  const reply = message.reply;
  if (!reply) return '';
  switch (reply.kind) {
    case 'case': return `Created work order ${reply.data.caseId} (${reply.data.typeLabel}, ${reply.data.risk}).`;
    case 'caseStatus': return `Showed the status of work order ${reply.caseId}.`;
    case 'knowledge': return reply.answer ?? `Listed ${reply.hits.length} knowledge sources: ${reply.hits.map(hit => hit.source_ref).join(', ') || 'none'}.`;
    case 'progress': return 'Showed project progress.';
    case 'approvals': return 'Listed pending approvals.';
    case 'answer': return reply.text;
    case 'help': return 'Explained what the assistant can do.';
    case 'ocr': return `Received ${reply.filename}; OCR is required.`;
    case 'error': return 'The request failed.';
  }
}

function detectIntent(text: string, hasFile: boolean): Intent {
  if (hasFile) return 'incident';
  if (text.length <= 30 && HELP_RE.test(text.trim())) return 'help';
  const incident = INCIDENT_RE.test(text);
  if (!incident && APPROVAL_RE.test(text) && text.length <= 40) return 'approvals';
  if (!incident && PROGRESS_RE.test(text) && text.length <= 60) return 'progress';
  if (!incident && (KNOWLEDGE_RE.test(text) || /[?？]\s*$/.test(text))) return 'knowledge';
  if (text.trim().length < 8) return 'help';
  return 'incident';
}

function newId() {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

async function readJson(response: Response) {
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = body?.detail;
    const message = typeof detail === 'string' ? detail : detail?.message ?? `HTTP ${response.status}`;
    throw new Error(message);
  }
  return body;
}

export function AssistantChat({ projects, pendingApprovals, planningAgent }: { projects: AssistantProject[]; pendingApprovals: number; planningAgent: string }) {
  const t = useTranslations('Assistant');
  const locale = useLocale();
  const [messages, setMessages] = useState<Message[]>([]);
  const [text, setText] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [mode, setMode] = useState<Mode>('auto');
  const [projectId, setProjectId] = useState('auto');
  const [route, setRoute] = useState<'auto' | 'local' | 'openai'>('auto');
  const [restricted, setRestricted] = useState(false);
  const [busy, setBusy] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const textInput = useRef<HTMLTextAreaElement>(null);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    try {
      const saved = sessionStorage.getItem(STORAGE_KEY);
      if (saved) setMessages((JSON.parse(saved) as Message[]).filter(m => m.role === 'user' || m.reply));
    } catch { /* storage unavailable: start empty */ }
  }, []);

  useEffect(() => {
    try { sessionStorage.setItem(STORAGE_KEY, JSON.stringify(messages.filter(m => m.role === 'user' || m.reply))); } catch { /* ignore */ }
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages]);

  // The composer remounts when the empty state switches to the thread layout;
  // keep the caret in it so the next message can be typed straight away.
  const hasMessages = messages.length > 0;
  useEffect(() => {
    if (hasMessages && !busy) textInput.current?.focus();
  }, [hasMessages, busy]);

  const effectiveRoute = restricted ? 'local' : route;
  const classification = restricted ? 'restricted' : 'internal';

  const headers = { 'accept-language': locale };

  async function runIntake(input: string, upload: File | null, plannedProject: number | null): Promise<Reply> {
    const lang = `lang=${locale}`;
    // A project code the user typed explicitly counts as their confirmation.
    const named = projects.find(project => input.toUpperCase().includes(project.code.toUpperCase()));
    const chosenProject = projectId !== 'auto' ? Number(projectId) : plannedProject ?? named?.id ?? null;
    let body;
    if (upload) {
      const form = new FormData();
      form.append('file', upload);
      // The user's words travel as a note (lineage), never as document text.
      const note = input && input !== upload.name ? `&note=${encodeURIComponent(input.slice(0, 1000))}` : '';
      body = await readJson(await fetch(`/backend/intake/document?${lang}&model_route=${effectiveRoute}&data_classification=${classification}${note}`, { method: 'POST', headers, body: form }));
    } else {
      body = await readJson(await fetch(`/backend/intake/text?${lang}`, {
        method: 'POST',
        headers: { ...headers, 'content-type': 'application/json' },
        body: JSON.stringify({ text: input, project_id: chosenProject, model_route: effectiveRoute, data_classification: classification }),
      }));
    }
    if (!body.case_id) return { kind: 'ocr', message: body.intake?.message ?? '', filename: body.document?.filename ?? upload?.name ?? '' };
    const intake = body.intake;
    return {
      kind: 'case',
      data: {
        caseId: body.case_id, typeLabel: intake.case_type_label, risk: intake.risk, riskLabel: intake.risk_label,
        country: intake.country_label ?? '', stage: intake.lifecycle_stage?.name ?? '', deadline: intake.deadline ?? '',
        issues: intake.issues ?? [], team: (body.specialist_team ?? []).map((agent: { name: string }) => agent.name),
        method: intake.classification_method, route: effectiveRoute, classification,
      },
    };
  }

  // Server-side planner (LLM when configured, deterministic rules otherwise).
  async function plan(input: string, tool: Tool | undefined, history: Message[]): Promise<Plan> {
    return readJson(await fetch(`/backend/assistant/chat?lang=${locale}`, {
      method: 'POST',
      headers: { ...headers, 'content-type': 'application/json' },
      body: JSON.stringify({
        message: input,
        history: history.map(m => ({ role: m.role, content: historyLine(m).slice(0, 1900) })).filter(turn => turn.content).slice(-8),
        project_id: projectId === 'auto' ? null : Number(projectId),
        model_route: effectiveRoute,
        data_classification: classification,
        tool,
      }),
    }));
  }

  // Used only when the planner endpoint itself is unreachable.
  async function fallbackPlan(input: string, intent: Intent): Promise<Plan> {
    const base: Plan = { tool: 'answer_directly', method: 'rules', reply: null, case_id: null, project_id: null, query: null, hits: null };
    if (intent !== 'knowledge') return { ...base, tool: (Object.keys(INTENT_BY_TOOL) as Tool[]).find(tool => INTENT_BY_TOOL[tool] === intent) ?? 'answer_directly' };
    const body = await readJson(await fetch(`/backend/knowledge/search?q=${encodeURIComponent(input)}&limit=5&lang=${locale}`, { headers }));
    return { ...base, tool: 'search_knowledge', query: input, hits: body.results as KnowledgeHit[] };
  }

  function replyFor(planned: Plan, input: string): Reply | null {
    switch (planned.tool) {
      case 'search_knowledge': return { kind: 'knowledge', query: input, hits: planned.hits ?? [], answer: planned.reply };
      case 'case_status': return planned.case_id ? { kind: 'caseStatus', caseId: planned.case_id } : { kind: 'help' };
      case 'project_progress': return { kind: 'progress', projectId: planned.project_id };
      case 'pending_approvals': return { kind: 'approvals' };
      case 'answer_directly': return planned.reply ? { kind: 'answer', text: planned.reply } : { kind: 'help' };
      case 'report_incident': return null;
    }
  }

  async function send(forced?: { intent: Intent; text: string }) {
    const input = (forced?.text ?? text).trim();
    const upload = forced ? null : file;
    if (busy || (!input && !upload)) return;
    const chosen: Intent | undefined = forced?.intent ?? (mode === 'auto' ? undefined : mode);
    const history = messages;
    const assistantId = newId();
    const update = (patch: Partial<Extract<Message, { role: 'assistant' }>>) =>
      setMessages(prev => prev.map(m => m.id === assistantId ? { ...m, ...patch } as Message : m));
    setMessages(prev => [
      ...prev,
      { id: newId(), role: 'user', text: input, fileName: upload?.name },
      { id: assistantId, role: 'assistant', intent: upload ? 'incident' : chosen ?? null, reply: null },
    ]);
    setText(''); setFile(null); setMode('auto'); setBusy(true);
    try {
      if (upload) {
        update({ method: 'user', reply: await runIntake(input || upload.name, upload, null) });
      } else {
        let planned: Plan;
        try {
          planned = await plan(input, chosen ? TOOL_BY_MODE[chosen] : undefined, history);
        } catch {
          planned = await fallbackPlan(input, chosen ?? detectIntent(input, false));
        }
        const intent = INTENT_BY_TOOL[planned.tool];
        update({ intent, method: planned.method });
        const reply = replyFor(planned, input) ?? await runIntake(input, null, planned.project_id);
        update({ reply });
      }
    } catch (error) {
      update({ reply: { kind: 'error', message: error instanceof Error ? error.message : t('failed') } });
    }
    setBusy(false);
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    send();
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      send();
    }
  }

  function onFile(event: ChangeEvent<HTMLInputElement>) {
    const picked = event.target.files?.[0] ?? null;
    setFile(picked);
    if (picked) setMode('incident');
    event.target.value = '';
  }

  function chooseMode(next: Mode) {
    setMode(next);
    textInput.current?.focus();
  }

  const empty = messages.length === 0;
  const placeholder = mode === 'knowledge' ? t('placeholderKnowledge') : mode === 'incident' ? t('placeholderIncident') : t('placeholder');

  const composer = <form className="assistant-composer" onSubmit={submit}>
    {(mode !== 'auto' || file) && <div className="assistant-composer-tags">
      {mode !== 'auto' && <button type="button" className="assistant-tag" onClick={() => setMode('auto')}>{t(`modes.${mode}`)} ×</button>}
      {file && <button type="button" className="assistant-tag file" onClick={() => setFile(null)}>📎 {file.name} ×</button>}
    </div>}
    <textarea ref={textInput} value={text} onChange={event => setText(event.target.value)} onKeyDown={onKeyDown} placeholder={placeholder} rows={empty ? 3 : 2} maxLength={20000} aria-label={t('placeholder')} />
    <div className="assistant-composer-bar">
      <div className="assistant-controls">
        <select value={projectId} onChange={event => setProjectId(event.target.value)} aria-label={t('project')}>
          <option value="auto">{t('projectAuto')}</option>
          {projects.map(project => <option key={project.id} value={project.id}>{project.code}</option>)}
        </select>
        <button type="button" className="assistant-icon-button" onClick={() => fileInput.current?.click()} aria-label={t('attach')}>📎<span className="assistant-label"> {t('attach')}</span></button>
        <input ref={fileInput} type="file" accept=".pdf,.docx,.txt" hidden onChange={onFile} />
      </div>
      <div className="assistant-controls">
        <label className={`assistant-restricted ${restricted ? 'on' : ''}`} title={t('restrictedHint')}>
          <input type="checkbox" checked={restricted} onChange={event => setRestricted(event.target.checked)} />🔒<span className="assistant-label"> {t('restricted')}</span>
        </label>
        <select value={effectiveRoute} disabled={restricted} onChange={event => setRoute(event.target.value as typeof route)} aria-label={t('model')}>
          <option value="auto">{t('routes.auto')}</option>
          <option value="local">{t('routes.local')}</option>
          <option value="openai">{t('routes.openai')}</option>
        </select>
        <button className="assistant-send" type="submit" disabled={busy || (!text.trim() && !file)} aria-label={t('send')}>↑</button>
      </div>
    </div>
  </form>;

  const chips = <div className="assistant-chips">
    <button type="button" onClick={() => chooseMode('incident')}>⚠ {t('chips.report')}</button>
    <button type="button" onClick={() => { setMode('incident'); fileInput.current?.click(); }}>✉ {t('chips.letter')}</button>
    <button type="button" onClick={() => chooseMode('knowledge')}>⚖ {t('chips.regulation')}</button>
    <button type="button" onClick={() => send({ intent: 'progress', text: t('chips.progress') })}>📊 {t('chips.progress')}</button>
    <button type="button" onClick={() => send({ intent: 'approvals', text: t('chips.approvals') })}>✔ {t('chips.approvals')}{pendingApprovals > 0 && <span className="assistant-count">{pendingApprovals}</span>}</button>
  </div>;

  if (empty) {
    return <div className="assistant assistant-empty">
      <div className="assistant-hero">
        <div className="brand-mark assistant-mark"><span>GI</span></div>
        <h2>{t('greeting')}</h2>
        <p>{t('intro')}</p>
      </div>
      {composer}
      {chips}
      <p className="assistant-boundary">{t('boundary')}</p>
    </div>;
  }

  return <div className="assistant">
    <div className="assistant-thread-head">
      <span>{t('threadTitle')}</span>
      <button type="button" className="button secondary" onClick={() => setMessages([])} disabled={busy}>＋ {t('newChat')}</button>
    </div>
    <div className="assistant-thread">
      {messages.map(message => message.role === 'user'
        ? <div key={message.id} className="assistant-msg user"><div className="assistant-bubble">{message.fileName && <div className="assistant-file">📎 {message.fileName}</div>}{message.text && message.text !== message.fileName && <div>{message.text}</div>}</div></div>
        : <div key={message.id} className="assistant-msg bot">
          <div className="brand-mark assistant-avatar"><span>GI</span></div>
          <div className="assistant-reply">
            <div className="assistant-intent">
              {message.intent ? t(`intents.${message.intent}`) : t('understanding')}
              {message.intent && message.method && <span className={`assistant-method ${message.method}`}>{t(`methods.${message.method}`)}</span>}
            </div>
            {message.reply ? <ReplyView reply={message.reply} projects={projects} planningAgent={planningAgent} /> : <Thinking intent={message.intent ?? 'help'} />}
          </div>
        </div>)}
      <div ref={endRef} />
    </div>
    <div className="assistant-dock">{composer}{chips}</div>
  </div>;
}

function Thinking({ intent }: { intent: Intent }) {
  const t = useTranslations('Assistant');
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    const timer = setInterval(() => setSeconds(value => value + 1), 1000);
    return () => clearInterval(timer);
  }, []);
  return <div className="assistant-thinking"><span className="assistant-dots"><i /><i /><i /></span>{intent === 'incident' ? t('thinkingIncident') : t('thinking')}{seconds > 2 && <small>{seconds}s</small>}</div>;
}

function ReplyView({ reply, projects, planningAgent }: { reply: Reply; projects: AssistantProject[]; planningAgent: string }) {
  const t = useTranslations('Assistant');
  switch (reply.kind) {
    case 'case': return <CaseReply caseId={reply.data.caseId} summary={reply.data} projects={projects} planningAgent={planningAgent} />;
    case 'caseStatus': return <CaseReply caseId={reply.caseId} projects={projects} planningAgent={planningAgent} />;
    case 'answer': return <div className="assistant-text assistant-prose">{reply.text}</div>;
    case 'ocr': return <div className="assistant-card"><p><b>{reply.filename}</b></p><p className="muted">{reply.message}</p></div>;
    case 'knowledge': return <KnowledgeReply query={reply.query} hits={reply.hits} answer={reply.answer ?? null} />;
    case 'progress': return <ProgressReply projects={reply.projectId ? projects.filter(p => p.id === reply.projectId) : projects} />;
    case 'approvals': return <ApprovalsReply />;
    case 'help': return <div className="assistant-text">{t('help')}</div>;
    case 'error': return <div className="assistant-error" role="alert">{t('failed')} · {reply.message}</div>;
  }
}

type CaseDetail = {
  id: string; title: string; type: string; risk: string; status: string; deadline: string; project_name: string | null; routing_status: string;
  detected_issues: string[];
  evidence: { id: number; title: string; source_ref: string; excerpt: string; confidence: number; verified: boolean }[];
  agent_runs: { id: number; agent: string; status: string; summary: string }[];
  action: { id: string; status: string } | null;
  execution_receipt: { id: string; status: string; output_digest: string } | null;
  verification_receipt: { id: string; status: string; checks: Record<string, boolean> } | null;
  artifact: { id: string } | null;
};
type ApprovalRow = { id: number; case_id: string; title: string; approver_role: string; status: string; risk: string };

function planSteps(summary: string): string[] {
  const body = summary.split(/[：:]/).slice(1).join(':');
  const steps = body.split(/[；;]/).map(step => step.trim().replace(/[。.]$/, '')).filter(Boolean);
  return steps.length >= 2 ? steps : [];
}

function CaseReply({ caseId, summary, projects, planningAgent }: { caseId: string; summary?: CaseSummary; projects: AssistantProject[]; planningAgent: string }) {
  const t = useTranslations('Assistant');
  const locale = useLocale();
  const [detail, setDetail] = useState<CaseDetail | null>(null);
  const [approvals, setApprovals] = useState<ApprovalRow[]>([]);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    try {
      const [caseBody, approvalBody] = await Promise.all([
        readJson(await fetch(`/backend/cases/${caseId}?lang=${locale}`)),
        readJson(await fetch(`/backend/approvals?lang=${locale}`)),
      ]);
      setDetail(caseBody);
      setApprovals((approvalBody as ApprovalRow[]).filter(row => row.case_id === caseId));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t('failed'));
    }
  }, [caseId, locale, t]);

  useEffect(() => { load(); }, [load]);

  async function post(key: string, path: string, payload?: object) {
    setBusy(key); setError('');
    try {
      await readJson(await fetch(`/backend${path}`, payload
        ? { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(payload) }
        : { method: 'POST' }));
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t('failed'));
    } finally { setBusy(''); }
  }

  const planRun = detail?.agent_runs.find(run => run.agent === planningAgent);
  const steps = planRun ? planSteps(planRun.summary) : [];
  const status = detail?.action?.status ?? '';
  const checks = detail?.verification_receipt ? Object.values(detail.verification_receipt.checks) : [];
  const statusLabel = (code: string) => t.has(`statuses.${code}`) ? t(`statuses.${code}`) : code;
  const typeLabel = summary?.typeLabel ?? detail?.type ?? '';
  const risk = summary?.risk ?? detail?.risk ?? '';
  const deadline = summary?.deadline || detail?.deadline || '';
  const issues = summary?.issues ?? detail?.detected_issues ?? [];
  if (!summary && !detail) return error ? <div className="assistant-error" role="alert">{t('failed')} · {error}</div> : <Thinking intent="help" />;

  return <div className="assistant-case">
    <p className="assistant-text">{summary
      ? t('caseIntro', { id: caseId, type: summary.typeLabel, risk: summary.riskLabel })
      : t('caseStatusIntro', { id: caseId, status: statusLabel(detail?.action?.status ?? detail?.status ?? '') })}</p>
    <div className="assistant-card">
      <div className="assistant-card-head">
        {risk && <RiskBadge risk={risk} />}
        <b>{typeLabel}</b>
        <span className="muted">{[detail?.project_name, summary?.country, summary?.stage].filter(Boolean).join(' · ')}</span>
      </div>
      <div className="assistant-facts">
        <div><span>{t('deadline')}</span><b>{deadline || '—'}</b></div>
        {summary && <div><span>{t('team')}</span><b>{summary.team.join('、') || '—'}</b></div>}
        {summary && <div><span>{t('method')}</span><b>{summary.method === 'llm' ? t('methodLlm') : t('methodRules')}</b></div>}
      </div>
      {issues.length > 0 && <div className="assistant-issues">{issues.map(issue => <span key={issue}>{issue}</span>)}</div>}
      {!detail && !error && <Thinking intent="help" />}
      {detail && <>
        <div className="assistant-section-label">{t('plan')}</div>
        {steps.length ? <ol className="assistant-plan">{steps.map(step => <li key={step}>{step}</li>)}</ol> : <p className="muted">{planRun?.summary ?? '—'}</p>}
        {(() => {
          // Only verified evidence (above the confident relevance threshold)
          // is shown as a basis; the rest is folded and carries no score.
          const strong = detail.evidence.filter(item => item.verified);
          const weak = detail.evidence.filter(item => !item.verified);
          return <details className="assistant-details">
            <summary>{t('evidence', { count: strong.length })}</summary>
            {strong.length === 0 ? <p className="muted">{t('noEvidence')}</p> : strong.map(item => <div key={item.id} className="assistant-evidence">
              <div><b>{item.title}</b><code>{item.source_ref}</code><span className="badge info">{Math.round(item.confidence * 100)}%</span></div>
              <p>{item.excerpt}</p>
            </div>)}
            {weak.length > 0 && <p className="muted small">{t('weakEvidence', { refs: weak.map(item => item.source_ref).join('、') })}</p>}
          </details>;
        })()}
        <details className="assistant-details">
          <summary>{t('process', { count: detail.agent_runs.length })}</summary>
          <ul className="assistant-runs">{detail.agent_runs.map(run => <li key={run.id}><span className={run.status === 'COMPLETED' ? 'ok' : ''}>{run.status === 'COMPLETED' ? '✓' : '•'}</span><div><b>{run.agent}</b><p>{run.summary}</p></div></li>)}</ul>
        </details>
      </>}
    </div>

    {detail?.routing_status === 'NEEDS_PROJECT_CONFIRMATION' && <div className="assistant-card governance">
      <div className="assistant-card-head"><b>{t('confirmTitle')}</b><span className="badge medium">{t('confirmBadge')}</span></div>
      <p className="muted">{t('confirmHint')}</p>
      <div className="assistant-actions">
        {projects.map(project => <button key={project.id} className="button secondary" disabled={!!busy}
          onClick={() => post(`p${project.id}`, `/cases/${caseId}/confirm-project?model_route=${summary?.route ?? 'auto'}&data_classification=${summary?.classification ?? 'internal'}`, { project_id: project.id })}>
          {busy === `p${project.id}` ? t('working') : `${project.code} · ${project.country_name}`}
        </button>)}
      </div>
    </div>}

    {detail && detail.routing_status !== 'NEEDS_PROJECT_CONFIRMATION' && <div className="assistant-card governance">
      <div className="assistant-card-head"><b>{t('governanceTitle')}</b><span className="badge info">{statusLabel(status || detail.status)}</span></div>
      <p className="muted">{t('governanceHint')}</p>
      <div className="assistant-approvals">
        {approvals.map(row => <div key={row.id} className="assistant-approval">
          <span>{row.approver_role}</span>
          {row.status === 'PENDING'
            ? <div className="assistant-actions">
              <button className="button" disabled={!!busy} onClick={() => post(`a${row.id}`, `/approvals/${row.id}/approve`)}>{busy === `a${row.id}` ? t('working') : t('approve')}</button>
              <button className="button danger" disabled={!!busy} onClick={() => post(`r${row.id}`, `/approvals/${row.id}/reject`)}>{t('reject')}</button>
            </div>
            : <span className={`badge ${row.status === 'APPROVED' ? 'ok' : 'high'}`}>{row.status === 'APPROVED' ? t('approved') : t('rejected')}</span>}
        </div>)}
      </div>
      {detail.action && <div className="assistant-actions">
        {(status === 'APPROVED' || status === 'EXECUTION_FAILED') && <button className="button" disabled={!!busy} onClick={() => post('execute', `/actions/${detail.action!.id}/execute`)}>{busy === 'execute' ? t('working') : t('execute')}</button>}
        {(status === 'EXECUTED' || status === 'VERIFICATION_FAILED') && <button className="button" disabled={!!busy} onClick={() => post('verify', `/actions/${detail.action!.id}/verify`)}>{busy === 'verify' ? t('working') : t('verify')}</button>}
        {status === 'VERIFIED' && <button className="button" disabled={!!busy} onClick={() => post('close', `/actions/${detail.action!.id}/close`)}>{busy === 'close' ? t('working') : t('close')}</button>}
      </div>}
      {detail.execution_receipt && <p className="assistant-receipt">✓ {t('executed', { digest: detail.execution_receipt.output_digest?.slice(0, 12) ?? '' })}</p>}
      {detail.artifact && <DraftView artifactId={detail.artifact.id} />}
      {detail.verification_receipt && <p className="assistant-receipt">✓ {t('verified', { passed: checks.filter(Boolean).length, total: checks.length })}</p>}
      {status === 'CLOSED' && <p className="assistant-receipt">✓ {t('closed')}</p>}
      {status === 'REJECTED' && <p className="assistant-error">{t('rejectedHint')}</p>}
      <p className="assistant-boundary small">{t('draftBoundary')}</p>
    </div>}
    {error && <div className="assistant-error" role="alert">{t('failed')} · {error}</div>}
    <Link className="assistant-link" href={`/cases/${caseId}`}>{t('openCase')} →</Link>
  </div>;
}

function KnowledgeReply({ query, hits, answer }: { query: string; hits: KnowledgeHit[]; answer: string | null }) {
  const t = useTranslations('Assistant');
  const anchor = useId();
  const [open, setOpen] = useState<number | null>(null);
  // Below the confident threshold a hit is not evidence, so it is not shown.
  const strong = hits.filter(hit => hit.relevance >= CONFIDENT_RELEVANCE);
  if (strong.length === 0) return <div className="assistant-text">{t('knowledgeNone', { query })}</div>;
  const byRef = new Map(strong.map(hit => [hit.source_ref, hit]));
  // With a model answer, "sources cited" lists only what the answer cites.
  const cited = answer ? strong.filter(hit => answer.includes(`[${hit.source_ref}]`)) : strong;
  const uncited = strong.filter(hit => !cited.includes(hit));
  const card = (hit: KnowledgeHit) => <KnowledgeCard key={hit.id} hit={hit} domId={`${anchor}-${hit.id}`} open={open === hit.id} onToggle={() => setOpen(open === hit.id ? null : hit.id)} />;
  function reveal(hit: KnowledgeHit) {
    setOpen(hit.id);
    document.getElementById(`${anchor}-${hit.id}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }
  // Turn "[REF]" citations into buttons that open the matching source card.
  const answerParts = answer?.split(/(\[[^\[\]]+\])/g).map((part, index) => {
    const hit = byRef.get(part.slice(1, -1).trim());
    return hit && part.startsWith('[')
      ? <button key={index} type="button" className="assistant-cite" onClick={() => reveal(hit)}>{hit.source_ref}</button>
      : part;
  });
  return <div>
    {answer
      ? <><div className="assistant-text assistant-prose">{answerParts}</div><p className="assistant-section-label">{t('knowledgeSources', { count: cited.length })}</p></>
      : <p className="assistant-text">{t('knowledgeFound', { count: strong.length })}</p>}
    {cited.map(card)}
    {uncited.length > 0 && <details className="assistant-details" open={uncited.some(hit => hit.id === open)}>
      <summary>{t('sourcesUncited', { count: uncited.length })}</summary>
      {uncited.map(card)}
    </details>}
    <p className="assistant-boundary small">{t('knowledgeBoundary')}</p>
  </div>;
}

type KnowledgeDetail = {
  content: string; authority: string | null; document_type: string; version: string; status: string;
  effective_date: string | null; review_due: string | null; source_url: string | null; content_hash: string;
  tags: string[]; lifecycle_stages: string[]; category: string;
};

function KnowledgeCard({ hit, domId, open, onToggle }: { hit: KnowledgeHit; domId: string; open: boolean; onToggle: () => void }) {
  const t = useTranslations('Assistant');
  const locale = useLocale();
  const [detail, setDetail] = useState<KnowledgeDetail | null>(null);
  const [error, setError] = useState(false);
  const label = (group: string, code: string) => t.has(`${group}.${code}`) ? t(`${group}.${code}`) : code;
  useEffect(() => {
    if (!open || detail) return;
    fetch(`/backend/knowledge/${hit.id}?lang=${locale}`).then(readJson).then(setDetail).catch(() => setError(true));
  }, [open, detail, hit.id, locale]);
  return <div id={domId} className={`assistant-card compact assistant-source ${open ? 'open' : ''}`}>
    <button type="button" className="assistant-source-toggle" onClick={onToggle} aria-expanded={open}>
      <div className="assistant-card-head"><b>{hit.title}</b><span className="badge ok">{t('relevance', { value: hit.relevance.toFixed(2) })}</span></div>
      <p>{hit.summary}</p>
      <p className="muted small"><code>{hit.source_ref}</code> · {hit.jurisdiction} · v{hit.version} <span className="assistant-source-more">{open ? t('sourceLess') : t('sourceMore')}</span></p>
    </button>
    {open && <div className="assistant-source-detail">
      {error && <p className="assistant-error">{t('failed')}</p>}
      {!detail && !error && <Thinking intent="help" />}
      {detail && <>
        <div className="assistant-section-label">{t('sourceContent')}</div>
        <p className="assistant-prose">{detail.content}</p>
        <dl className="assistant-meta">
          {detail.authority && <><dt>{t('sourceAuthority')}</dt><dd>{detail.authority}</dd></>}
          <dt>{t('sourceType')}</dt><dd>{detail.category} · {label('docTypes', detail.document_type)}</dd>
          <dt>{t('sourceVersion')}</dt><dd>{detail.version} · {label('docStatuses', detail.status)}</dd>
          {detail.effective_date && <><dt>{t('sourceEffective')}</dt><dd>{detail.effective_date}</dd></>}
          {detail.review_due && <><dt>{t('sourceReview')}</dt><dd>{detail.review_due}</dd></>}
          {detail.lifecycle_stages.length > 0 && <><dt>{t('sourceStages')}</dt><dd>{detail.lifecycle_stages.map(stage => t.has(`stages.${stage}`) ? t(`stages.${stage}`) : stage).join(' / ')}</dd></>}
          {detail.tags.length > 0 && <><dt>{t('sourceTags')}</dt><dd>{detail.tags.join('、')}</dd></>}
          <dt>{t('sourceHash')}</dt><dd><code title={detail.content_hash}>{detail.content_hash.slice(0, 16)}…</code></dd>
        </dl>
        {detail.source_url
          ? <a className="button assistant-source-link" href={detail.source_url} target="_blank" rel="noopener noreferrer">{t('sourceOpen')} ↗</a>
          : <p className="muted small">{t('sourceInternal')}</p>}
      </>}
    </div>}
  </div>;
}

function ProgressReply({ projects }: { projects: AssistantProject[] }) {
  const t = useTranslations('Assistant');
  return <div>
    <p className="assistant-text">{t('progressIntro', { count: projects.length })}</p>
    <div className="assistant-progress">
      {projects.map(project => <Link key={project.id} href={`/projects/${project.id}`} className="assistant-card compact">
        <div className="assistant-card-head"><b>{project.code}</b><RiskBadge risk={project.risk_level} /></div>
        <p>{project.name} · {project.country_name}</p>
        {typeof project.progress === 'number' && <div className="assistant-bar"><i style={{ width: `${Math.min(100, project.progress)}%` }} /></div>}
        <p className="muted small">
          {typeof project.progress === 'number' && t('progressValue', { value: project.progress })}
          {typeof project.schedule_variance === 'number' && ` · ${t('variance', { days: project.schedule_variance })}`}
          {project.next_gate && ` · ${t('nextGate', { gate: project.next_gate, date: project.gate_date ?? '' })}`}
        </p>
      </Link>)}
    </div>
  </div>;
}

function ApprovalsReply() {
  const t = useTranslations('Assistant');
  const locale = useLocale();
  const [rows, setRows] = useState<ApprovalRow[] | null>(null);
  const [busy, setBusy] = useState(0);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    try {
      const body = await readJson(await fetch(`/backend/approvals?lang=${locale}`));
      setRows((body as ApprovalRow[]).filter(row => row.status === 'PENDING').slice(0, 8));
    } catch (reason) { setError(reason instanceof Error ? reason.message : t('failed')); }
  }, [locale, t]);

  useEffect(() => { load(); }, [load]);

  async function decide(id: number, decision: 'approve' | 'reject') {
    setBusy(id); setError('');
    try {
      await readJson(await fetch(`/backend/approvals/${id}/${decision}`, { method: 'POST' }));
      await load();
    } catch (reason) { setError(reason instanceof Error ? reason.message : t('failed')); }
    finally { setBusy(0); }
  }

  if (!rows) return error ? <div className="assistant-error">{error}</div> : <Thinking intent="approvals" />;
  return <div>
    <p className="assistant-text">{rows.length ? t('approvalsIntro', { count: rows.length }) : t('approvalsNone')}</p>
    {rows.map(row => <div key={row.id} className="assistant-card compact">
      <div className="assistant-card-head"><RiskBadge risk={row.risk} /><b>{row.title}</b></div>
      <p className="muted small">{row.approver_role} · <Link href={`/cases/${row.case_id}`}>{row.case_id}</Link></p>
      <div className="assistant-actions">
        <button className="button" disabled={!!busy} onClick={() => decide(row.id, 'approve')}>{busy === row.id ? t('working') : t('approve')}</button>
        <button className="button danger" disabled={!!busy} onClick={() => decide(row.id, 'reject')}>{t('reject')}</button>
      </div>
    </div>)}
    {error && <div className="assistant-error" role="alert">{error}</div>}
  </div>;
}

type DraftDocument = { body: Record<string, string>; composition?: string };

function DraftView({ artifactId }: { artifactId: string }) {
  const t = useTranslations('Assistant');
  const locale = useLocale();
  const [draft, setDraft] = useState<DraftDocument | null>(null);
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    let alive = true;
    fetch(`/backend/artifacts/${artifactId}`)
      .then(readJson)
      .then(body => { if (alive) setDraft(JSON.parse(body.content) as DraftDocument); })
      .catch(() => { /* the receipt line above still proves the draft exists */ });
    return () => { alive = false; };
  }, [artifactId]);
  if (!draft) return null;
  const text = draft.body[locale] ?? draft.body.en ?? '';
  async function copy() {
    try { await navigator.clipboard.writeText(text); setCopied(true); } catch { /* clipboard unavailable */ }
  }
  return <details className="assistant-details assistant-draft" open>
    <summary>{t('draftTitle')} · {draft.composition === 'llm' ? t('draftLlm') : t('draftTemplate')}</summary>
    <pre>{text}</pre>
    <button type="button" className="button secondary" onClick={copy}>{copied ? t('copied') : t('copy')}</button>
  </details>;
}
