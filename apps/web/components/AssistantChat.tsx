'use client';

import Link from 'next/link';
import { ChangeEvent, FormEvent, KeyboardEvent, ReactNode, useCallback, useEffect, useId, useRef, useState } from 'react';
import { useLocale, useTranslations } from 'next-intl';
import { RiskBadge } from './RiskBadge';
import { DrawingReviewDrawer, type DrawingReviewTarget } from './DrawingReviewDrawer';
import { DrawingModelReceipt } from './DrawingModelReceipt';
import type { DrawingModelSnapshot, DrawingReviewUpdate } from './DrawingWorkspace';

export type AssistantProject = {
  id: number; code: string; name: string; country_name: string; phase?: string; progress?: number;
  schedule_variance?: number; next_gate?: string; gate_date?: string; risk_level: string;
};

type Mode = 'auto' | 'drawing' | 'incident' | 'knowledge' | 'progress' | 'approvals';
type Intent = Exclude<Mode, 'auto'> | 'help' | 'caseStatus' | 'dispatch';
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
type DrawingCitation = {
  element_id?: string; page?: number; bbox?: number[]; source_text?: string;
  confidence?: number; state?: string;
};
type DrawingReply = {
  kind: 'drawing'; drawingId: string; filename: string; status: string; sha256: string;
  projectId: number | null; pages: number; elementCount: number; uncertainCount: number;
  geometryCount: number; confirmedGeometryCount: number;
  footprintCount: number; confirmedFootprintCount: number;
  fields: { drawingNumber: string; revision: string; scale: string; unit: string; title: string };
  categories: Record<string, number>; modelReady: boolean; blockers: string[];
  question?: string; answer?: string; grounded?: boolean; citations?: DrawingCitation[];
  model?: DrawingModelSnapshot;
};

type StepStatus = 'waiting' | 'running' | 'ok' | 'error';
type IntakeData = { case_id: string; case_type_label: string; risk: string; risk_label: string; country_label: string | null; stage: string | null; deadline: string | null; issues: string[]; team: string[]; method: string };
type StepData = Partial<IntakeData> & {
  query?: string; hits?: KnowledgeHit[]; answer?: string | null; question?: string; reanalyzed?: boolean;
  project_ids?: number[]; count?: number;
  reports?: { id: string; description: string; status: string; risk: string; case_id: string | null; open_questions: number }[];
  countries?: string[]; retried?: boolean; clarify?: Clarify | null;
  table?: { country: string; country_name: string; clauses: KnowledgeHit[] }[];
  terms?: { country: string; id: string; en: string; zh: string; local: string; local_lang: string; attested: boolean }[];
  gates?: { country: string; stage: string; gates: { code: string; name: string; authority: string; gate: string }[] }[];
  points?: { text: string; refs: string[] }[]; status?: string; clauses?: KnowledgeHit[];
  drawings?: { id: string; drawing_number: string | null; title: string | null; status: string }[];
  drawing_id?: string; drawing_number?: string | null;
  coverage_gaps?: string[];
  assets?: { id: string; name: string; status: string; stage: string; health: number; progress: number;
    sensors: SensorView[]; maintenance: { id: string; type: string; status: string; priority: string; due_at: string; description: string }[] }[];
  alerts?: SensorView[];
  items?: { id?: string; system?: string; asset?: string; test_pack?: string; stage?: string; punch_open?: number; documents?: number;
    readiness?: number; ready?: boolean; kind?: string; ref?: string; risk?: string; text?: string }[];
  precedents?: { case_id: string; title: string; type: string; risk: string; status: string; resolved: boolean; similarity: number }[];
  counts?: Record<string, number>;
  findings?: { category: string; name: string; risk: 'high' | 'medium' | 'low'; finding: string; excerpt: string; basis: string[] }[];
  related?: (KnowledgeHit & { category: string })[];
  country?: string | null;
  agents?: { id: string; name: string; role: string; authority: string }[];
  coverage?: CoverageRow[]; focus_domains?: string[]; boundaries?: string[];
  stats?: { clauses: number; countries: number; instruments: number; glossary_terms: number };
};
type SensorView = { id: string; twin_id: string; type: string; unit: string; value: number; warning: number; critical: number; level: string };
type CoverageLevel = 'covered' | 'thin' | 'none' | 'legal_only';
type CoverageRow = { id: string; name: string; note: string; agents: string[]; project_data?: boolean; countries: Record<string, { clauses: number; level: CoverageLevel }> };
type Clarify = { question: string; options: string[] };
type TraceStep = { index: number; agent: string; status: string; depends_on: number[]; duration_ms: number; refs: number };
type Trace = {
  plan_method: string; summary_method: string | null; dropped_sentences: number; duration_ms: number;
  steps: TraceStep[]; refs: string[]; model_calls: number; focus_countries: string[];
};
type DispatchStep = { index: number; agent: string; name: string; authority: string; query: string; case_id: string | null; depends_on?: number[]; status: StepStatus; summary?: string; data?: StepData; duration_ms?: number };
type Dispatch = {
  kind: 'dispatch'; method: Method | null; steps: DispatchStep[]; summary: { text: string; method: 'llm' | 'rules' } | null;
  reply: string | null; contextCase: string | null; error: string | null; done: boolean; route: string; classification: string;
  clarify?: Clarify[]; trace?: Trace | null;
};
type DispatchEvent =
  | { type: 'session'; session_id: string; context_case_id: string | null }
  | { type: 'plan'; method: Method; steps: Omit<DispatchStep, 'status'>[] }
  | { type: 'step_start'; index: number }
  | { type: 'step_done'; index: number; status: 'ok' | 'error'; summary: string; data?: StepData; duration_ms?: number }
  | { type: 'summary'; text: string; method: 'llm' | 'rules'; dropped_sentences?: number }
  | ({ type: 'clarify'; step: string } & Clarify)
  | ({ type: 'trace' } & Trace)
  | { type: 'reply'; text: string | null }
  | { type: 'error'; message: string }
  | { type: 'done' };

type Reply =
  | Dispatch
  | { kind: 'case'; data: CaseSummary }
  | { kind: 'ocr'; message: string; filename: string }
  | { kind: 'knowledge'; query: string; hits: KnowledgeHit[]; answer?: string | null }
  | { kind: 'caseStatus'; caseId: string }
  | { kind: 'answer'; text: string }
  | { kind: 'progress'; projectId: number | null }
  | { kind: 'approvals' }
  | DrawingReply
  | { kind: 'help' }
  | { kind: 'error'; message: string };

type Message =
  | { id: string; role: 'user'; text: string; fileName?: string }
  | { id: string; role: 'assistant'; intent: Intent | null; method?: Method; reply: Reply | null };

const STORAGE_KEY = 'globalinfra-assistant-v1';
const SESSION_KEY = 'globalinfra-assistant-session';
// Matches workflow.CONFIDENT_RELEVANCE: below it a hit is not evidence.
const CONFIDENT_RELEVANCE = 0.22;

const HELP_RE = /^(你好|您好|嗨|hi|hello|hey)[!！。,， ]*$|你能做什么|你会做什么|你会什么|你是谁|能帮我做什么|怎么用|使用说明|^帮助$|^help$|what can you do|who are you|how do i use/i;
const INCIDENT_RE = /通知|整改|事故|隐患|损坏|破损|延误|索赔|违规|泄漏|坍塌|受伤|缺陷|notice|incident|damage|delay|claim|injur|defect|rectif|hazard|unsafe|leak/i;
const APPROVAL_RE = /审批|待我|批准|approval|approve|sign[- ]?off/i;
const PROGRESS_RE = /进度|进展|状态|概况|progress|status|schedule|overview/i;
const KNOWLEDGE_RE = /法规|法律|规定|规范|标准|条款|条例|要求|依据|哪一条|regulation|law|clause|requirement|standard|permit/i;
const DRAWING_RE = /图纸|图号|版次|墙体|门窗|构件|bim|ifc|drawing|blueprint|floor\s*plan/i;
const DRAWING_EXT_RE = /\.(pdf|png|jpe?g|tiff?)$/i;
const DRAWING_WORKBENCH_RE = /工作台|打开图纸|看看图纸|workbench/i;

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
    case 'drawing': return reply.answer
      ? `Analyzed drawing ${reply.filename}: ${reply.answer}`
      : `Analyzed drawing ${reply.filename} with ${reply.elementCount} evidence-linked elements.`;
    case 'error': return 'The request failed.';
    case 'dispatch': return reply.summary?.text ?? reply.reply ?? reply.steps.map(step => `${step.name}: ${step.summary ?? ''}`).join(' ');
  }
}

function applyEvent(state: Dispatch, event: DispatchEvent): Dispatch {
  switch (event.type) {
    case 'session': return { ...state, contextCase: event.context_case_id };
    case 'plan': return { ...state, method: event.method, steps: event.steps.map(step => ({ ...step, status: 'waiting' })) };
    case 'step_start': return { ...state, steps: state.steps.map(step => step.index === event.index ? { ...step, status: 'running' } : step) };
    case 'step_done': return { ...state, steps: state.steps.map(step => step.index === event.index ? { ...step, status: event.status, summary: event.summary, data: event.data, duration_ms: event.duration_ms } : step) };
    case 'clarify': return { ...state, clarify: [...(state.clarify ?? []), { question: event.question, options: event.options }] };
    case 'trace': return { ...state, trace: event };
    case 'summary': return { ...state, summary: { text: event.text, method: event.method } };
    case 'reply': return { ...state, reply: event.text };
    case 'error': return { ...state, error: event.message };
    case 'done': return { ...state, done: true };
  }
}

function detectIntent(text: string, hasFile: boolean): Intent {
  if (hasFile) return 'incident';
  if (text.length <= 30 && HELP_RE.test(text.trim())) return 'help';
  if (DRAWING_RE.test(text)) return 'drawing';
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

function object(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function array<T>(value: unknown): T[] {
  return Array.isArray(value) ? value as T[] : [];
}

function valueText(value: unknown): string {
  return typeof value === 'string' || typeof value === 'number' ? String(value) : '';
}

function normalizeDrawingReply(payload: unknown, previous?: DrawingReply): DrawingReply {
  const body = object(payload);
  const document = object(body.document ?? body.drawing ?? body);
  const elements = array<Record<string, unknown>>(body.elements ?? object(body.analysis).elements);
  const gate = object(body.model_gate ?? body.modelGate);
  const categories = elements.reduce<Record<string, number>>((counts, item) => {
    const category = valueText(item.type ?? item.category).toUpperCase() || 'OTHER';
    counts[category] = (counts[category] ?? 0) + 1;
    return counts;
  }, {});
  const confidence = (item: Record<string, unknown>) => {
    const raw = typeof item.confidence === 'number' ? item.confidence : 0;
    return raw <= 1 ? raw * 100 : raw;
  };
  const geometry = elements.filter(item => {
    const category = valueText(item.type ?? item.category).toUpperCase();
    const geometryType = valueText(object(item.properties).geometry_type).toUpperCase();
    return ['WALL', 'DOOR', 'SPACE', 'EQUIPMENT'].includes(category)
      && ['LINE', 'RECTANGLE_FOOTPRINT', 'POLYGON_FOOTPRINT'].includes(geometryType);
  });
  const footprints = geometry.filter(item => ['RECTANGLE_FOOTPRINT', 'POLYGON_FOOTPRINT']
    .includes(valueText(object(item.properties).geometry_type).toUpperCase()));
  return {
    kind: 'drawing',
    drawingId: valueText(document.id ?? document.drawing_id) || previous?.drawingId || '',
    filename: valueText(document.filename) || previous?.filename || '',
    status: valueText(document.status ?? body.status) || previous?.status || 'ANALYZED',
    sha256: valueText(document.sha256 ?? document.checksum) || previous?.sha256 || '',
    projectId: typeof document.project_id === 'number' ? document.project_id : previous?.projectId ?? null,
    pages: Number(document.page_count ?? array(body.sheets).length ?? previous?.pages ?? 0),
    elementCount: elements.length || previous?.elementCount || 0,
    uncertainCount: elements.length
      ? elements.filter(item => confidence(item) < 80 || valueText(item.state ?? item.status).toUpperCase() === 'INFERRED').length
      : previous?.uncertainCount ?? 0,
    geometryCount: elements.length ? geometry.length : previous?.geometryCount ?? 0,
    confirmedGeometryCount: elements.length
      ? geometry.filter(item => valueText(item.state ?? item.status).toUpperCase() === 'USER_CONFIRMED').length
      : previous?.confirmedGeometryCount ?? 0,
    footprintCount: elements.length ? footprints.length : previous?.footprintCount ?? 0,
    confirmedFootprintCount: elements.length
      ? footprints.filter(item => valueText(item.state ?? item.status).toUpperCase() === 'USER_CONFIRMED').length
      : previous?.confirmedFootprintCount ?? 0,
    fields: {
      drawingNumber: valueText(document.drawing_number ?? object(document.metadata).drawing_number) || previous?.fields.drawingNumber || '',
      revision: valueText(document.revision ?? object(document.metadata).revision) || previous?.fields.revision || '',
      scale: valueText(document.scale ?? object(document.metadata).scale) || previous?.fields.scale || '',
      unit: valueText(document.unit ?? object(document.metadata).unit) || previous?.fields.unit || '',
      title: valueText(document.title ?? object(document.metadata).title) || previous?.fields.title || '',
    },
    categories: Object.keys(categories).length ? categories : previous?.categories ?? {},
    modelReady: Boolean(gate.ready ?? gate.model_ready ?? previous?.modelReady),
    blockers: array<string>(gate.blockers ?? gate.missing ?? previous?.blockers),
    question: previous?.question,
    answer: previous?.answer,
    grounded: previous?.grounded,
    citations: previous?.citations,
    model: previous?.model,
  };
}

function isDrawingFile(file: File): boolean {
  return DRAWING_EXT_RE.test(file.name) || ['application/pdf', 'image/png', 'image/jpeg', 'image/tiff'].includes(file.type);
}

function latestDrawing(messages: Message[]): DrawingReply | null {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (message.role === 'assistant' && message.reply?.kind === 'drawing') return message.reply;
  }
  return null;
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
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [drawingReview, setDrawingReview] = useState<DrawingReviewTarget | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const textInput = useRef<HTMLTextAreaElement>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const closeDrawingReview = useCallback(() => setDrawingReview(null), []);
  const applyDrawingUpdate = useCallback((update: DrawingReviewUpdate) => {
    setMessages(current => current.map(message => {
      if (message.role !== 'assistant' || message.reply?.kind !== 'drawing' || message.reply.drawingId !== update.drawingId) return message;
      const refreshed = update.detail ? normalizeDrawingReply(update.detail, message.reply) : message.reply;
      return {
        ...message,
        reply: {
          ...refreshed,
          model: update.model ?? refreshed.model,
        },
      };
    }));
  }, []);

  useEffect(() => {
    try {
      const saved = sessionStorage.getItem(STORAGE_KEY);
      if (saved) setMessages((JSON.parse(saved) as Message[]).filter(m => m.role === 'user' || m.reply));
      setSessionId(sessionStorage.getItem(SESSION_KEY));
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

  async function askDrawing(drawing: DrawingReply, question: string): Promise<DrawingReply> {
    const detail = await readJson(await fetch(
      `/backend/drawings/${encodeURIComponent(drawing.drawingId)}?lang=${locale}`,
      { headers, cache: 'no-store' },
    ));
    const current = normalizeDrawingReply(detail, drawing);
    if (DRAWING_WORKBENCH_RE.test(question)) {
      return {
        ...current,
        question,
        answer: t('drawingWorkspaceSummary', {
          elements: current.elementCount,
          confirmed: current.confirmedGeometryCount,
          geometry: current.geometryCount,
        }),
        grounded: true,
        citations: [],
      };
    }
    const body = await readJson(await fetch(`/backend/drawings/${encodeURIComponent(drawing.drawingId)}/ask?lang=${locale}`, {
      method: 'POST',
      headers: { ...headers, 'content-type': 'application/json' },
      body: JSON.stringify({ question }),
    }));
    return {
      ...current,
      question,
      answer: valueText(body.answer),
      grounded: Boolean(body.grounded),
      citations: array<DrawingCitation>(body.citations),
    };
  }

  async function runDrawingAnalysis(input: string, upload: File): Promise<DrawingReply> {
    const chosenProject = projectId !== 'auto' ? Number(projectId) : projects[0]?.id ?? null;
    if (!chosenProject) throw new Error(t('drawingProjectRequired'));
    const form = new FormData();
    form.append('file', upload);
    form.append('project_id', String(chosenProject));
    form.append('data_classification', restricted ? 'restricted' : 'internal');
    const body = await readJson(await fetch(`/backend/drawings/analyze?lang=${locale}`, {
      method: 'POST', headers, body: form,
    }));
    let drawing = normalizeDrawingReply(body);
    drawing = { ...drawing, projectId: chosenProject };
    const generic = /^(请)?(帮我)?(分析|读取|查看)(一下)?(这张|这个)?(工程)?图纸[。.!！]?$/i;
    const prompt = input && input !== upload.name && !generic.test(input)
      ? input
      : t('drawingDefaultQuestion');
    if (prompt.trim().length >= 2) drawing = await askDrawing(drawing, prompt.trim());
    return drawing;
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

  // The dispatcher plans several steps and streams their progress. Returns
  // false when the stream could not start, so the caller can fall back.
  async function dispatch(input: string, history: Message[], show: (reply: Dispatch, method: Method | null) => void): Promise<boolean> {
    let response: Response;
    try {
      response = await fetch(`/backend/assistant/dispatch?lang=${locale}`, {
        method: 'POST',
        headers: { ...headers, 'content-type': 'application/json' },
        body: JSON.stringify({
          message: input, session_id: sessionId,
          history: history.map(m => ({ role: m.role, content: historyLine(m).slice(0, 1900) })).filter(turn => turn.content).slice(-8),
          project_id: projectId === 'auto' ? null : Number(projectId),
          model_route: effectiveRoute, data_classification: classification,
        }),
      });
    } catch { return false; }
    if (!response.ok || !response.body) return false;
    let state: Dispatch = { kind: 'dispatch', method: null, steps: [], summary: null, reply: null, contextCase: null, error: null, done: false, route: effectiveRoute, classification };
    show(state, null);
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    try {
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let cut;
        while ((cut = buffer.indexOf('\n\n')) >= 0) {
          const chunk = buffer.slice(0, cut);
          buffer = buffer.slice(cut + 2);
          for (const line of chunk.split('\n')) {
            if (!line.startsWith('data: ')) continue;
            const event = JSON.parse(line.slice(6)) as DispatchEvent;
            if (event.type === 'session') {
              setSessionId(event.session_id);
              try { sessionStorage.setItem(SESSION_KEY, event.session_id); } catch { /* ignore */ }
            }
            state = applyEvent(state, event);
            show(state, state.method);
          }
        }
      }
    } catch (reason) {
      state = { ...state, error: reason instanceof Error ? reason.message : t('failed') };
    }
    if (!state.done) state = { ...state, done: true, error: state.error ?? t('failed') };
    show(state, state.method);
    return true;
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
    const drawingUpload = Boolean(upload && (mode === 'drawing' || (mode === 'auto' && isDrawingFile(upload))));
    const drawingContext = latestDrawing(messages);
    const history = messages;
    const assistantId = newId();
    const update = (patch: Partial<Extract<Message, { role: 'assistant' }>>) =>
      setMessages(prev => prev.map(m => m.id === assistantId ? { ...m, ...patch } as Message : m));
    setMessages(prev => [
      ...prev,
      { id: newId(), role: 'user', text: input, fileName: upload?.name },
      { id: assistantId, role: 'assistant', intent: drawingUpload ? 'drawing' : upload ? 'incident' : chosen ?? null, reply: null },
    ]);
    setText(''); setFile(null); setMode('auto'); setBusy(true);
    try {
      if (upload) {
        update({
          intent: drawingUpload ? 'drawing' : 'incident',
          method: 'user',
          reply: drawingUpload
            ? await runDrawingAnalysis(input || upload.name, upload)
            : await runIntake(input || upload.name, upload, null),
        });
      } else if ((chosen === 'drawing' || (!chosen && drawingContext)) && drawingContext) {
        update({ intent: 'drawing', method: 'user', reply: await askDrawing(drawingContext, input) });
      } else if (chosen === 'drawing') {
        update({ intent: 'drawing', method: 'user', reply: { kind: 'error', message: t('drawingAttachRequired') } });
      } else if (!chosen && await dispatch(input, history, (reply, method) => update({ intent: 'dispatch', method: method ?? undefined, reply }))) {
        // streamed by the dispatcher
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
    if (picked) setMode(mode === 'incident' ? 'incident' : isDrawingFile(picked) ? 'drawing' : 'incident');
    event.target.value = '';
  }

  function chooseMode(next: Mode) {
    setMode(next);
    textInput.current?.focus();
  }

  const empty = messages.length === 0;
  const placeholder = mode === 'drawing' ? t('placeholderDrawing') : mode === 'knowledge' ? t('placeholderKnowledge') : mode === 'incident' ? t('placeholderIncident') : t('placeholder');

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
        <input ref={fileInput} type="file" accept=".pdf,.docx,.txt,.png,.jpg,.jpeg,.tif,.tiff" hidden onChange={onFile} />
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
    <button type="button" onClick={() => { setMode('drawing'); fileInput.current?.click(); }}>▧ {t('chips.drawing')}</button>
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

  return <>
    <div className="assistant">
      <div className="assistant-thread-head">
      <span>{t('threadTitle')}</span>
      <button type="button" className="button secondary" onClick={() => {
        setMessages([]); setSessionId(null);
        try { sessionStorage.removeItem(SESSION_KEY); } catch { /* ignore */ }
      }} disabled={busy}>＋ {t('newChat')}</button>
      </div>
      <div className="assistant-thread">
        {messages.map(message => message.role === 'user'
          ? <div key={message.id} className="assistant-msg user"><div className="assistant-bubble">{message.fileName && <div className="assistant-file">📎 {message.fileName}</div>}{message.text && message.text !== message.fileName && <div>{message.text}</div>}</div></div>
          : <div key={message.id} className="assistant-msg bot">
            <div className="brand-mark assistant-avatar"><span>GI</span></div>
            <div className="assistant-reply">
              <div className="assistant-intent">
                {message.intent === 'dispatch' ? t('dispatch') : message.intent ? t(`intents.${message.intent}`) : t('understanding')}
                {message.intent && message.method && <span className={`assistant-method ${message.method}`}>{t(`methods.${message.method}`)}</span>}
              </div>
              {message.reply ? <ReplyView reply={message.reply} projects={projects} planningAgent={planningAgent} onOpenDrawing={setDrawingReview} onDrawingUpdate={applyDrawingUpdate} /> : <Thinking intent={message.intent ?? 'help'} />}
            </div>
          </div>)}
        <div ref={endRef} />
      </div>
      <div className="assistant-dock">{composer}{chips}</div>
    </div>
    {drawingReview ? <DrawingReviewDrawer projects={projects} target={drawingReview} onClose={closeDrawingReview} onUpdate={applyDrawingUpdate} /> : null}
  </>;
}

function Thinking({ intent }: { intent: Intent }) {
  const t = useTranslations('Assistant');
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    const timer = setInterval(() => setSeconds(value => value + 1), 1000);
    return () => clearInterval(timer);
  }, []);
  return <div className="assistant-thinking"><span className="assistant-dots"><i /><i /><i /></span>{intent === 'drawing' ? t('thinkingDrawing') : intent === 'incident' ? t('thinkingIncident') : t('thinking')}{seconds > 2 && <small>{seconds}s</small>}</div>;
}

function ReplyView({ reply, projects, planningAgent, onOpenDrawing, onDrawingUpdate }: {
  reply: Reply;
  projects: AssistantProject[];
  planningAgent: string;
  onOpenDrawing: (target: DrawingReviewTarget) => void;
  onDrawingUpdate: (update: DrawingReviewUpdate) => void;
}) {
  const t = useTranslations('Assistant');
  switch (reply.kind) {
    case 'case': return <CaseReply caseId={reply.data.caseId} summary={reply.data} projects={projects} planningAgent={planningAgent} />;
    case 'caseStatus': return <CaseReply caseId={reply.caseId} projects={projects} planningAgent={planningAgent} />;
    case 'answer': return <div className="assistant-text assistant-prose">{reply.text}</div>;
    case 'ocr': return <div className="assistant-card"><p><b>{reply.filename}</b></p><p className="muted">{reply.message}</p></div>;
    case 'knowledge': return <KnowledgeReply query={reply.query} hits={reply.hits} answer={reply.answer ?? null} />;
    case 'progress': return <ProgressReply projects={reply.projectId ? projects.filter(p => p.id === reply.projectId) : projects} />;
    case 'approvals': return <ApprovalsReply />;
    case 'drawing': return <DrawingReplyCard reply={reply} onOpenDrawing={onOpenDrawing} onDrawingUpdate={onDrawingUpdate} />;
    case 'help': return <div className="assistant-text">{t('help')}</div>;
    case 'error': return <div className="assistant-error" role="alert">{t('failed')} · {reply.message}</div>;
    case 'dispatch': return <DispatchReply reply={reply} projects={projects} planningAgent={planningAgent} />;
  }
}

function DrawingReplyCard({ reply, onOpenDrawing, onDrawingUpdate }: {
  reply: DrawingReply;
  onOpenDrawing: (target: DrawingReviewTarget) => void;
  onDrawingUpdate: (update: DrawingReviewUpdate) => void;
}) {
  const t = useTranslations('Assistant');
  const locale = useLocale();
  const [current, setCurrent] = useState(reply);
  const [refreshing, setRefreshing] = useState(false);

  useEffect(() => { setCurrent(reply); }, [reply]);

  async function refresh() {
    setRefreshing(true);
    try {
      const response = await fetch(`/backend/drawings/${encodeURIComponent(current.drawingId)}?lang=${locale}`, { cache: 'no-store' });
      const payload = await readJson(response);
      setCurrent(normalizeDrawingReply(payload, current));
      onDrawingUpdate({ drawingId: current.drawingId, action: 'refreshed', detail: payload });
    } finally { setRefreshing(false); }
  }

  const categories = Object.entries(current.categories).sort((a, b) => b[1] - a[1]).slice(0, 8);
  const partialModel = current.modelReady && current.geometryCount > current.confirmedGeometryCount;
  const firstCitation = current.citations?.[0];
  const reviewTarget = (citation?: DrawingCitation): DrawingReviewTarget => ({
    drawingId: current.drawingId,
    page: citation?.page ?? 1,
    elementId: citation?.element_id ?? '',
  });
  const facts = [
    [t('drawingFields.number'), current.fields.drawingNumber],
    [t('drawingFields.revision'), current.fields.revision],
    [t('drawingFields.scale'), current.fields.scale],
    [t('drawingFields.unit'), current.fields.unit],
  ].filter(([, value]) => value);

  return <div className="assistant-card assistant-drawing-card">
    <div className="assistant-card-head">
      <span className="badge info">DRAWING INTELLIGENCE</span>
      <b>{current.filename || current.drawingId}</b>
      <span className={`badge ${current.modelReady ? 'ok' : 'medium'}`}>{current.modelReady ? t(partialModel ? 'drawingPartialModelReady' : 'drawingModelReady') : t('drawingNeedsReview')}</span>
    </div>
    <div className="assistant-drawing-lineage">
      <span>{current.pages} {t('drawingPages')}</span>
      <span>{current.elementCount} {t('drawingElements')}</span>
      <span>{current.uncertainCount} {t('drawingUncertain')}</span>
      {current.geometryCount > 0 && <span>{t('drawingGeometryConfirmed', { confirmed: current.confirmedGeometryCount, geometry: current.geometryCount })}</span>}
      {current.footprintCount > 0 && <span>{t('drawingFootprintsConfirmed', { confirmed: current.confirmedFootprintCount, footprints: current.footprintCount })}</span>}
      <code>{current.drawingId}</code>
    </div>
    {facts.length ? <div className="assistant-facts drawing-facts">{facts.map(([label, value]) => <div key={label}><span>{label}</span><b>{value}</b></div>)}</div> : null}
    {categories.length ? <div className="assistant-drawing-categories">{categories.map(([category, count]) => <span key={category}><b>{category}</b> {count}</span>)}</div> : null}
    {current.answer ? <div className={`assistant-drawing-answer ${current.grounded ? 'grounded' : 'unsupported'}`}>
      <div><b>{current.grounded ? t('drawingGrounded') : t('drawingUnsupported')}</b>{current.question && <small>{current.question}</small>}</div>
      <p>{current.answer}</p>
      {current.citations?.length ? <div className="assistant-drawing-citations">{current.citations.slice(0, 6).map((citation, index) => <button type="button" onClick={() => onOpenDrawing(reviewTarget(citation))} key={`${citation.element_id ?? index}`}><span>S{citation.page ?? 1}</span>{citation.source_text || `E${index + 1}`}</button>)}</div> : null}
    </div> : null}
    {!current.modelReady && current.blockers.length ? <p className="assistant-boundary small">{t('drawingBlockers', { count: current.blockers.length })} · {current.blockers.slice(0, 4).join(' · ')}</p> : null}
    {current.model ? <DrawingModelReceipt model={current.model} /> : null}
    <div className="assistant-actions">
      <button className="button" type="button" onClick={() => onOpenDrawing(reviewTarget(firstCitation))}>{t('drawingOpenWorkbench')}</button>
      <button className="button secondary" type="button" onClick={refresh} disabled={refreshing}>{refreshing ? t('drawingRefreshing') : t('drawingRefresh')}</button>
    </div>
    <p className="assistant-boundary small">AI_GENERATED_DRAFT · NOT_FOR_CONSTRUCTION</p>
  </div>;
}

const STEP_ICON: Record<StepStatus, string> = { waiting: '○', running: '◌', ok: '✓', error: '✕' };

function clip(text: string, length: number) {
  const plain = text.replace(/\s+/g, ' ').trim();
  return plain.length > length ? `${plain.slice(0, length)}…` : plain;
}

function Elapsed() {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    const timer = setInterval(() => setSeconds(value => value + 1), 1000);
    return () => clearInterval(timer);
  }, []);
  return seconds > 1 ? <small className="dispatch-elapsed">{seconds}s</small> : null;
}

function DispatchReply({ reply, projects, planningAgent }: { reply: Dispatch; projects: AssistantProject[]; planningAgent: string }) {
  const t = useTranslations('Assistant');
  const anchor = useId();
  if (!reply.method && !reply.error) return <div className="assistant-thinking"><span className="assistant-dots"><i /><i /><i /></span>{t('dispatchPlanning')}<Elapsed /></div>;
  if (reply.steps.length === 0) {
    if (reply.error) return <div className="assistant-error" role="alert">{t('failed')} · {reply.error}</div>;
    return reply.reply ? <div className="assistant-text assistant-prose">{reply.reply}</div> : <div className="assistant-text">{t('help')}</div>;
  }
  const sectionId = (index: number) => `${anchor}-s${index + 1}`;
  // Turn "[S2]" tags in the summary into links to that step's result.
  const summary = reply.summary?.text.split(/(\[[^\[\]]+\])/g).map((part, index) => {
    const match = /^\[S(\d)\]$/.exec(part);
    if (match && Number(match[1]) <= reply.steps.length) return <a key={index} className="assistant-cite" href={`#${sectionId(Number(match[1]) - 1)}`}>S{match[1]}</a>;
    return /^\[[^\[\]]+\]$/.test(part) ? <span key={index} className="assistant-cite">{part.slice(1, -1)}</span> : part;
  });
  // One work-order card per case, at the first step that produced it.
  const shownCases = new Set<string>();
  return <div className="assistant-dispatch">
    {reply.contextCase && <p className="muted small">{t('dispatchContext', { id: reply.contextCase })}</p>}
    <div className="dispatch-timeline">
      <div className="dispatch-head">{t('dispatchPlan', { count: reply.steps.length })}</div>
      <ol>{reply.steps.map((step, index) => <li key={step.index} className={`dispatch-step ${step.status}`}>
        <span className="dispatch-dot" aria-hidden>{STEP_ICON[step.status]}</span>
        <div>
          <div className="dispatch-step-head">
            <b>S{index + 1} · {step.name}</b>
            {(step.depends_on ?? []).length > 0 && <span className="muted small">{t('dispatchAfter', { steps: (step.depends_on ?? []).map(d => `S${d + 1}`).join(', ') })}</span>}
            <span className={`dispatch-authority ${step.authority}`}>{t(`authority.${step.authority}`)}</span>
            <span className="dispatch-status">{t(`dispatchStatus.${step.status}`)}</span>
            {step.status === 'running' && <Elapsed />}
          </div>
          {step.summary && <p>{clip(step.summary, 140)}</p>}
        </div>
      </li>)}</ol>
    </div>
    {/* A rules summary repeats the timeline line by line; only a model summary adds to it. */}
    {summary && reply.summary?.method === 'llm' && <div className="assistant-card dispatch-summary">
      <div className="assistant-section-label">{t('dispatchSummary')} · {t(`summaryMethods.${reply.summary!.method}`)}</div>
      <div className="assistant-prose">{summary}</div>
    </div>}
    {reply.error && <div className="assistant-error" role="alert">{t('failed')} · {reply.error}</div>}
    {(reply.clarify ?? []).map((item, index) => <div key={index} className="assistant-card compact dispatch-clarify">
      <b>{item.question}</b>
      <div className="dispatch-chips">{item.options.map(code => <span key={code} className="assistant-cite">{code}</span>)}</div>
    </div>)}
    {reply.steps.map((step, index) => {
      if (step.status !== 'ok' || !step.data) return null;
      const data = step.data;
      let body: ReactNode = null;
      const caseId = data.case_id;
      if (caseId && !shownCases.has(caseId)) {
        shownCases.add(caseId);
        const intake = step.agent === 'intake' ? {
          caseId, typeLabel: data.case_type_label ?? '', risk: data.risk ?? '', riskLabel: data.risk_label ?? data.risk ?? '',
          country: data.country_label ?? '', stage: data.stage ?? '', deadline: data.deadline ?? '', issues: data.issues ?? [],
          team: data.team ?? [], method: data.method ?? 'rules', route: reply.route, classification: reply.classification,
        } : undefined;
        body = <>
          {step.agent === 'answer' && <p className="assistant-text">{t('answerRecorded', { answer: clip(String(data.answer ?? ''), 80) })}</p>}
          <CaseReply caseId={caseId} summary={intake} projects={projects} planningAgent={planningAgent} />
        </>;
      } else if (step.agent === 'knowledge') {
        body = <>
          {(data.coverage_gaps ?? []).map((gap, i) => <p key={i} className="assistant-text coverage-gap">{gap}</p>)}
          <KnowledgeReply query={data.query ?? step.query} hits={data.hits ?? []} answer={data.answer ?? null} />
        </>;
      } else if (step.agent === 'progress') {
        body = <>
          {step.summary && <p className="assistant-text">{step.summary}</p>}
          <ProgressReply projects={projects.filter(p => (data.project_ids ?? []).includes(p.id))} />
        </>;
      } else if (step.agent === 'twin') {
        body = <TwinReply summary={step.summary ?? ''} data={data} />;
      } else if (step.agent === 'commissioning') {
        body = <CommissioningReply summary={step.summary ?? ''} items={data.items ?? []} />;
      } else if (step.agent === 'precedents') {
        body = <PrecedentsReply summary={step.summary ?? ''} rows={data.precedents ?? []} />;
      } else if (step.agent === 'briefing') {
        body = <BriefingReply summary={step.summary ?? ''} items={data.items ?? []} />;
      } else if (step.agent === 'contract_review') {
        body = <ContractReviewReply summary={step.summary ?? ''} data={data} />;
      } else if (step.agent === 'approvals') {
        body = <ApprovalsReply />;
      } else if (step.agent === 'field') {
        body = <FieldDispatchReply reports={data.reports ?? []} />;
      } else if (step.agent === 'compare') {
        body = <CompareReply table={data.table ?? []} answer={data.answer ?? null} />;
      } else if (step.agent === 'glossary') {
        body = <GlossaryReply terms={data.terms ?? []} />;
      } else if (step.agent === 'gates') {
        body = <>
          <GatesReply rows={data.gates ?? []} />
          {(data.hits ?? []).length > 0 && <KnowledgeReply query={step.query} hits={data.hits ?? []} answer={null} />}
        </>;
      } else if (step.agent === 'drawing') {
        body = <p className="assistant-text assistant-prose">{step.summary}</p>;
      } else if (step.agent === 'self') {
        body = <SelfReply summary={step.summary ?? ''} data={data} />;
      } else if (step.agent === 'draft') {
        body = <DraftPointsReply points={data.points ?? []} caseId={data.case_id ?? null} />;
      }
      if (!body) return null;
      return <section key={step.index} id={sectionId(index)} className="dispatch-section">
        {reply.steps.length > 1 && <div className="assistant-section-label">S{index + 1} · {step.name}</div>}
        {body}
      </section>;
    })}
    {reply.trace && <TraceView trace={reply.trace} steps={reply.steps} />}
  </div>;
}

const LEVEL_ICON: Record<CoverageLevel, string> = { covered: '●', thin: '◐', none: '○', legal_only: '◔' };

function SelfReply({ summary, data }: { summary: string; data: StepData }) {
  const t = useTranslations('Assistant');
  const focus = new Set(data.focus_domains ?? []);
  const rows = (data.coverage ?? []).filter(row => focus.size === 0 || focus.has(row.id));
  const countries = Object.keys(rows[0]?.countries ?? {});
  return <div>
    <p className="assistant-text assistant-prose">{summary}</p>
    {rows.length > 0 && <table className="dispatch-table">
      <thead><tr><th>{t('selfDomain')}</th>{countries.map(code => <th key={code}>{code}</th>)}</tr></thead>
      <tbody>{rows.map(row => <tr key={row.id}>
        <td><b>{row.name}</b>{focus.size > 0 && <div className="muted small">{row.note}</div>}</td>
        {countries.map(code => {
          const cell = row.countries[code];
          return <td key={code} title={t(`selfLevel.${cell.level}`)} className={`coverage-${cell.level}`}>
            {LEVEL_ICON[cell.level]} {cell.clauses}
          </td>;
        })}
      </tr>)}</tbody>
    </table>}
    <p className="muted small">{(['covered', 'thin', 'legal_only', 'none'] as CoverageLevel[]).map(level => `${LEVEL_ICON[level]} ${t(`selfLevel.${level}`)}`).join(' · ')} · {t('selfCount')}</p>
    {focus.size === 0 && (data.agents ?? []).length > 0 && <details className="dispatch-trace">
      <summary>{t('selfAgents', { count: data.agents!.length })}</summary>
      <ul className="small">{data.agents!.map(agent => <li key={agent.id}><b>{agent.name}</b> · {t(`authority.${agent.authority}`)} — {agent.role}</li>)}</ul>
    </details>}
    {(data.boundaries ?? []).length > 0 && <ul className="muted small">{data.boundaries!.map((line, index) => <li key={index}>{line}</li>)}</ul>}
  </div>;
}

function TwinReply({ summary, data }: { summary: string; data: StepData }) {
  const t = useTranslations('Assistant');
  return <div>
    <p className="assistant-text">{summary}</p>
    {(data.assets ?? []).length > 0 && <table className="dispatch-table">
      <thead><tr><th>{t('twinAsset')}</th><th>{t('twinStatus')}</th><th>{t('twinHealth')}</th><th>{t('twinMaintenance')}</th></tr></thead>
      <tbody>{data.assets!.map(asset => <tr key={asset.id}>
        <td><b>{asset.name}</b><div className="muted small">{asset.id}</div></td>
        <td>{asset.status}<div className="muted small">{asset.stage} · {asset.progress.toFixed(0)}%</div></td>
        <td className={asset.health < 70 ? 'coverage-legal_only' : asset.health < 85 ? 'coverage-thin' : 'coverage-covered'}>{asset.health.toFixed(0)}
          {asset.sensors.filter(s => s.level !== 'NORMAL').map(s => <div key={s.id} className="small">⚠ {s.type} {s.value}{s.unit}</div>)}</td>
        <td className="small">{asset.maintenance.map(m => <div key={m.id}>{m.id} · {m.priority} · {m.due_at}</div>)}</td>
      </tr>)}</tbody>
    </table>}
    <Link className="assistant-link" href="/twin">{t('twinOpen')} →</Link>
  </div>;
}

function CommissioningReply({ summary, items }: { summary: string; items: NonNullable<StepData['items']> }) {
  const t = useTranslations('Assistant');
  return <div>
    <p className="assistant-text">{summary}</p>
    {items.length > 0 && <table className="dispatch-table">
      <thead><tr><th>{t('cxSystem')}</th><th>{t('cxStage')}</th><th>{t('cxPunch')}</th><th>{t('cxDocs')}</th><th>{t('cxReadiness')}</th></tr></thead>
      <tbody>{items.map(item => <tr key={item.id}>
        <td><b>{item.system}</b><div className="muted small">{item.test_pack}</div></td>
        <td className="small">{item.stage}</td><td>{item.punch_open}</td><td>{item.documents?.toFixed(0)}%</td>
        <td className={item.ready ? 'coverage-covered' : 'coverage-thin'}>{item.readiness?.toFixed(0)}% {item.ready ? '✓' : ''}</td>
      </tr>)}</tbody>
    </table>}
  </div>;
}

function PrecedentsReply({ summary, rows }: { summary: string; rows: NonNullable<StepData['precedents']> }) {
  const t = useTranslations('Assistant');
  return <div>
    <p className="assistant-text">{summary}</p>
    {rows.map(row => <div key={row.case_id} className="assistant-card compact">
      <div className="assistant-card-head"><RiskBadge risk={row.risk} /><b>{row.title}</b></div>
      <p className="muted small">{row.type} · {row.status} · {row.resolved ? t('precedentClosed') : t('precedentOpen')} · {t('precedentMatch', { pct: Math.round(row.similarity * 100) })} · <Link href={`/cases/${row.case_id}`}>{row.case_id}</Link></p>
    </div>)}
  </div>;
}

function BriefingReply({ summary, items }: { summary: string; items: NonNullable<StepData['items']> }) {
  const t = useTranslations('Assistant');
  const label: Record<string, string> = { case: t('briefCase'), sensor: t('briefSensor'), maintenance: t('briefMaintenance'), schedule: t('briefSchedule') };
  return <div>
    <p className="assistant-text">{summary}</p>
    <ul className="dispatch-brief">{items.map((item, index) => <li key={index}>
      <RiskBadge risk={(item.risk ?? 'MEDIUM').toUpperCase()} /> <span className="muted small">{label[item.kind ?? ''] ?? item.kind}</span> {item.text}
      {item.kind === 'case' && item.ref && <> · <Link href={`/cases/${item.ref}`}>{item.ref}</Link></>}
    </li>)}</ul>
  </div>;
}

function ContractReviewReply({ summary, data }: { summary: string; data: StepData }) {
  const t = useTranslations('Assistant');
  const head = summary.split('\n')[0];
  return <div>
    <p className="assistant-text">{head}</p>
    <table className="dispatch-table">
      <thead><tr><th>{t('crRisk')}</th><th>{t('crTerm')}</th><th>{t('crFinding')}</th></tr></thead>
      <tbody>{(data.findings ?? []).map((finding, index) => <tr key={index}>
        <td className={`cr-${finding.risk}`}><b>{t(`crLevel.${finding.risk}`)}</b></td>
        <td>{finding.name}</td>
        <td>{finding.finding}{finding.basis.map(ref => <span key={ref} className="assistant-cite">{ref}</span>)}
          {finding.excerpt && <div className="muted small">“{finding.excerpt}”</div>}</td>
      </tr>)}</tbody>
    </table>
    {(data.related ?? []).length > 0 && <KnowledgeReply query={t('crRelated')} hits={data.related ?? []} answer={null} />}
    <p className="muted small">{t('crBoundary')}</p>
  </div>;
}

function CompareReply({ table, answer }: { table: NonNullable<StepData['table']>; answer: string | null }) {
  const t = useTranslations('Assistant');
  return <div>
    {answer && <div className="assistant-prose">{answer}</div>}
    <table className="dispatch-table">
      <thead><tr><th>{t('compareCountry')}</th><th>{t('compareClauses')}</th></tr></thead>
      <tbody>{table.map(row => <tr key={row.country}>
        <td><b>{row.country_name}</b></td>
        <td>{row.clauses.length ? row.clauses.map(hit => <div key={hit.source_ref}>
          <span className="assistant-cite">{hit.source_ref}</span> {hit.title}
        </div>) : <span className="muted">{t('compareGap')}</span>}</td>
      </tr>)}</tbody>
    </table>
    <p className="muted small">{t('knowledgeBoundary')}</p>
  </div>;
}

function GlossaryReply({ terms }: { terms: NonNullable<StepData['terms']> }) {
  const t = useTranslations('Assistant');
  if (!terms.length) return <p className="assistant-text">{t('glossaryNone')}</p>;
  return <table className="dispatch-table">
    <thead><tr><th>{t('compareCountry')}</th><th>中文 / English</th><th>{t('glossaryLocal')}</th><th>{t('glossaryBasis')}</th></tr></thead>
    <tbody>{terms.map(term => <tr key={`${term.country}-${term.id}`}>
      <td>{term.country}</td><td>{term.zh} / {term.en}</td>
      <td dir={term.local_lang === 'ar' ? 'rtl' : undefined} lang={term.local_lang}><b>{term.local}</b></td>
      <td className="small">{term.attested ? t('glossaryAttested') : t('glossaryCompiled')}</td>
    </tr>)}</tbody>
  </table>;
}

function GatesReply({ rows }: { rows: NonNullable<StepData['gates']> }) {
  const t = useTranslations('Assistant');
  return <div>{rows.map(row => <div key={row.country} className="assistant-card compact">
    <div className="assistant-section-label">{row.country}</div>
    {row.gates.length ? <ul>{row.gates.map(gate => <li key={gate.code}><b>{gate.code}</b> {gate.name} <span className="muted small">· {gate.authority} · {gate.gate}</span></li>)}</ul>
      : <p className="muted small">{t('gatesNone')}</p>}
  </div>)}</div>;
}

function DraftPointsReply({ points, caseId }: { points: NonNullable<StepData['points']>; caseId: string | null }) {
  const t = useTranslations('Assistant');
  return <div className="assistant-card dispatch-draft">
    <div className="assistant-section-label">{t('draftNotSent')}</div>
    <ol>{points.map((point, index) => <li key={index}>{point.text}{point.refs.map(ref => <span key={ref} className="assistant-cite">{ref}</span>)}</li>)}</ol>
    <p className="muted small">{t('draftBoundary')}{caseId && <> · <Link href={`/cases/${caseId}`}>{caseId}</Link></>}</p>
  </div>;
}

function TraceView({ trace, steps }: { trace: Trace; steps: DispatchStep[] }) {
  const t = useTranslations('Assistant');
  const names = new Map(steps.map(step => [step.index, step.name]));
  return <details className="dispatch-trace">
    <summary>{t('traceTitle', { ms: trace.duration_ms, calls: trace.model_calls, refs: trace.refs.length })}</summary>
    <ul className="small">
      <li>{t('tracePlan', { method: trace.plan_method })}{trace.summary_method ? ` · ${t('traceSummary', { method: trace.summary_method, dropped: trace.dropped_sentences })}` : ''}</li>
      {trace.focus_countries.length > 0 && <li>{t('traceFocus', { countries: trace.focus_countries.join(', ') })}</li>}
      {trace.steps.map(step => <li key={step.index}>
        S{step.index + 1} · {names.get(step.index) ?? step.agent} · {step.status} · {step.duration_ms} ms · {t('traceRefs', { count: step.refs })}
        {step.depends_on.length > 0 && ` · ${t('dispatchAfter', { steps: step.depends_on.map(d => `S${d + 1}`).join(', ') })}`}
      </li>)}
    </ul>
  </details>;
}

function FieldDispatchReply({ reports }: { reports: NonNullable<StepData['reports']> }) {
  const t = useTranslations('Assistant');
  return <div>
    <p className="assistant-text">{t('fieldIntro', { count: reports.length })}</p>
    {reports.map(report => <div key={report.id} className="assistant-card compact">
      <div className="assistant-card-head"><RiskBadge risk={report.risk} /><b>{clip(report.description, 60)}</b></div>
      <p className="muted small">
        {report.status}{report.open_questions > 0 && ` · ${t('fieldQuestions', { count: report.open_questions })}`}
        {report.case_id && <> · <Link href={`/cases/${report.case_id}`}>{report.case_id}</Link></>}
      </p>
    </div>)}
    <Link className="assistant-link" href="/field">{t('fieldOpen')} →</Link>
  </div>;
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
type TeamMember = { agent_id: string; name: string; source: string; rationale: string };
type PlanStep = { id: string; text: string; owner_role: string; due: string; source: string; evidence_refs: string[] };
type AgentFinding = { agent_id: string; name: string; status: string; claim: string; method: string; tool_calls: { tool: string; ok: boolean; summary: string }[] };
type AgentQuestion = { id: number; agent: string; question: string; status: string; answer: string | null };
type AgentRunView = { team: TeamMember[]; findings: AgentFinding[]; plan: PlanStep[]; unresolved: { topic: string; agents: string[] }[]; questions: AgentQuestion[] };
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
  const [agentRun, setAgentRun] = useState<AgentRunView | null>(null);
  const [answers, setAnswers] = useState<Record<number, string>>({});
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    try {
      const [caseBody, approvalBody, runBody] = await Promise.all([
        readJson(await fetch(`/backend/cases/${caseId}?lang=${locale}`)),
        readJson(await fetch(`/backend/approvals?lang=${locale}`)),
        fetch(`/backend/cases/${caseId}/agent-run?lang=${locale}`).then(r => r.ok ? r.json() : null).catch(() => null),
      ]);
      setDetail(caseBody);
      setAgentRun(runBody && runBody.team?.length ? runBody : null);
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
        {(agentRun || summary) && <div><span>{t('team')}</span><b>{(agentRun ? agentRun.team.map(m => m.name) : summary?.team ?? []).join('、') || '—'}</b></div>}
        {summary && <div><span>{t('method')}</span><b>{summary.method === 'llm' ? t('methodLlm') : t('methodRules')}</b></div>}
      </div>
      {issues.length > 0 && <div className="assistant-issues">{issues.map(issue => <span key={issue}>{issue}</span>)}</div>}
      {!detail && !error && <Thinking intent="help" />}
      {detail && <>
        {agentRun && <>
          <div className="assistant-section-label">{t('orgTeam', { count: agentRun.team.length })}</div>
          <div className="assistant-team">{agentRun.team.map(member => {
            const finding = agentRun.findings.find(f => f.agent_id === member.agent_id);
            return <div key={member.agent_id} className={`assistant-member ${finding?.status?.toLowerCase() ?? ''}`} title={member.rationale}>
              <b>{member.name}</b>
              <span className={`assistant-member-source ${member.source}`}>{t(`orgSource.${member.source}`)}</span>
              {finding && <span className="assistant-member-status">{t(`orgStatus.${finding.status}`)}</span>}
              <small>{member.rationale}</small>
            </div>;
          })}</div>
        </>}
        {agentRun && agentRun.questions.some(q => q.status === 'OPEN') && <div className="assistant-questions">
          <div className="assistant-section-label">{t('orgQuestions')}</div>
          {agentRun.questions.filter(q => q.status === 'OPEN').map(q => <div key={q.id} className="assistant-question">
            <p><b>{q.agent}：</b>{q.question}</p>
            <div className="assistant-question-row">
              <input value={answers[q.id] ?? ''} onChange={event => setAnswers(prev => ({ ...prev, [q.id]: event.target.value }))} placeholder={t('orgAnswerPlaceholder')} />
              <button className="button" disabled={!!busy || !(answers[q.id] ?? '').trim()}
                onClick={() => post(`q${q.id}`, `/cases/${caseId}/inputs`, { input_id: q.id, answer: answers[q.id] })}>
                {busy === `q${q.id}` ? t('orgReanalyzing') : t('orgAnswer')}
              </button>
            </div>
          </div>)}
        </div>}
        {agentRun && agentRun.unresolved.length > 0 && <div className="assistant-unresolved">
          <div className="assistant-section-label">{t('orgUnresolved')}</div>
          <ul>{agentRun.unresolved.map(issue => <li key={issue.topic}>{issue.topic}</li>)}</ul>
        </div>}
        <div className="assistant-section-label">{t('plan')}</div>
        {agentRun?.plan.length
          ? <ol className="assistant-plan structured">{agentRun.plan.map(step => <li key={step.id}><span>{step.text}</span><small>{step.owner_role} · {step.due}</small></li>)}</ol>
          : steps.length ? <ol className="assistant-plan">{steps.map(step => <li key={step}>{step}</li>)}</ol> : <p className="muted">{planRun?.summary ?? '—'}</p>}
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
