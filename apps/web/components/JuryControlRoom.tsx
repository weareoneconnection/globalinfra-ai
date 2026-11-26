'use client';

import Link from 'next/link';
import { useEffect, useRef, useState } from 'react';
import type {
  GoldenThread,
  SubmissionEvidence,
} from './CompetitionEvidence';

type SandboxRole =
  | 'project_manager'
  | 'hse_manager'
  | 'engineer'
  | 'verifier'
  | 'closer';

type LocalizedText = string | Record<'zh' | 'en', string>;

type SandboxTicket = {
  ticket: string;
  subject: string;
  role: SandboxRole;
  label: string;
  expires_at: string;
};

type SandboxState = {
  session: {
    id: string;
    case_id: string;
    status: string;
    expires_at: string;
    snapshot_digest: string;
    reset_count: number;
    synthetic: boolean;
    shared_history: boolean;
  };
  case: {
    id: string;
    status: string;
    title: LocalizedText;
    description: LocalizedText;
    risk: string;
    deadline: LocalizedText;
    twin_id: string;
  };
  evidence: {
    id: number;
    source_ref: string;
    title: LocalizedText;
    confidence: number;
    verified: boolean;
  }[];
  approvals: {
    id: number;
    required_role: 'project_manager' | 'hse_manager';
    status: string;
    decided_by: string | null;
    decision_digest: string | null;
    decision_signature: string | null;
    key_id: string | null;
  }[];
  action: {
    id: string;
    status: string;
    type: string;
    policy_version: string;
    proposal_digest: string;
    closed_by: string | null;
    closure_digest: string | null;
    closure_signature: string | null;
    closure_key_id: string | null;
  } | null;
  receipts: {
    execution: {
      id: string;
      status: string;
      executor: string;
      executor_role: string;
      output_digest: string;
      receipt_digest: string;
      signature: string;
      key_id: string;
    } | null;
    verification: {
      id: string;
      status: string;
      verified_by: string;
      verifier_role: string;
      checks: Record<string, boolean>;
      verification_digest: string;
      signature: string;
      key_id: string;
    } | null;
    artifact: {
      id: string;
      digest: string;
      delivery_status: string;
    } | null;
  };
  next_steps: string[];
  complete: boolean;
  closure_scope: {
    workflow_type: "DOCUMENT_RESPONSE_DRAFT";
    document_workflow_status: string;
    physical_hazard_status: string;
    physical_remediation_verified: boolean;
    project_hazard_closed: boolean;
    external_delivery_performed: boolean;
    meaning: string;
  };
  governance: {
    policy_version: string;
    separation_of_duties: boolean;
    external_delivery_performed: boolean;
    data_boundary: string;
  };
};

type SandboxCreated = {
  session: SandboxState['session'];
  role_tickets: Record<SandboxRole, SandboxTicket>;
  state: SandboxState;
};

type BoundaryProbe = {
  status: 'NOT_RUN' | 'BLOCKED';
  httpStatus?: number;
  code?: string;
};

type TamperProbe = {
  status: 'NOT_RUN' | 'INVALID_SIGNATURE';
  canonicalStatus?: string;
  canonicalUnchanged?: boolean;
  mutation?: string;
};

type FlowStep =
  | 'session'
  | 'analyze'
  | 'project_manager_approve'
  | 'hse_manager_approve'
  | 'execute'
  | 'verify'
  | 'close';

type DisplayEvidence = {
  source_ref: string;
  title: string;
  verified: boolean;
  status?: string;
};

const FLOW_STEPS: FlowStep[] = [
  'session',
  'analyze',
  'project_manager_approve',
  'hse_manager_approve',
  'execute',
  'verify',
  'close',
];

const ROLE_ORDER: SandboxRole[] = [
  'project_manager',
  'hse_manager',
  'engineer',
  'verifier',
  'closer',
];

const COPY = {
  zh: {
    eyebrow: 'V6.1 · 决赛评委控制室',
    title: '把一条跨国工程风险，变成可核验的行动链。',
    subtitle: 'P47 高处作业重大风险 · 马来西亚 · 24 小时回复期限',
    start: '开始评委验证',
    creating: '正在创建隔离会话…',
    timer: '决赛演示倒计时',
    exit: '返回证据中心',
    fullscreen: '全屏',
    reset: '重置',
    incident: '业主来函与 Twin 上下文',
    liveSession: '隔离评委会话',
    evidence: '实时证据',
    roles: '五个独立责任主体',
    challenge: '负向证明',
    challengeTitle: '项目经理尝试越权执行',
    challengeHint: '预期 HTTP 403，且业务状态必须保持不变。',
    challengeRun: '执行越权挑战',
    challengePassed: 'HTTP 403 · ROLE_SCOPE_REQUIRED · 状态未改变',
    tamperTitle: '签名证据副本篡改挑战',
    tamperHint: '只修改内存副本；正式证据与数据库保持不变。',
    tamperRun: '验证篡改副本',
    tamperPassed: 'INVALID_SIGNATURE · 正式证据未改变',
    finalCard: '函件处理流程核验证据',
    finalSubtitle: '五主体 · 两审批 · 执行 / 核验 / 关闭签名',
    external: '外部发送',
    notSent: '未执行',
    complete: '函件草稿流程已核验',
    pending: '等待明确操作',
    running: '正在提交具名操作…',
    release: '发布证据',
    synthetic: '仅使用参赛合成数据 · 不含客户数据',
    actionRequired: '每一步都需要对应角色显式操作',
    error: '评委流程失败',
  },
  en: {
    eyebrow: 'V6.1 · JURY LIVE CONTROL ROOM',
    title: 'Turn one cross-border risk into a verifiable action chain.',
    subtitle: 'P47 work-at-height critical risk · Malaysia · 24-hour response',
    start: 'START JURY VERIFICATION',
    creating: 'CREATING ISOLATED SESSION…',
    timer: 'FINAL DEMO COUNTDOWN',
    exit: 'BACK TO EVIDENCE',
    fullscreen: 'FULLSCREEN',
    reset: 'RESET',
    incident: 'OWNER NOTICE + TWIN CONTEXT',
    liveSession: 'ISOLATED JURY SESSION',
    evidence: 'LIVE EVIDENCE',
    roles: 'FIVE SEPARATED ACTORS',
    challenge: 'NEGATIVE PROOF',
    challengeTitle: 'Project manager attempts execution',
    challengeHint: 'Expected HTTP 403 with zero business-state change.',
    challengeRun: 'RUN AUTHORITY CHALLENGE',
    challengePassed: 'HTTP 403 · ROLE_SCOPE_REQUIRED · STATE UNCHANGED',
    tamperTitle: 'Signed-evidence copy tamper challenge',
    tamperHint: 'Mutates an in-memory copy only; canonical evidence stays immutable.',
    tamperRun: 'VERIFY TAMPERED COPY',
    tamperPassed: 'INVALID_SIGNATURE · CANONICAL EVIDENCE UNCHANGED',
    finalCard: 'DOCUMENT WORKFLOW RECEIPTS',
    finalSubtitle: 'Five actors · two approvals · execution / verification / closure signatures',
    external: 'EXTERNAL DELIVERY',
    notSent: 'NOT PERFORMED',
    complete: 'DRAFT WORKFLOW VERIFIED',
    pending: 'EXPLICIT ACTION REQUIRED',
    running: 'SUBMITTING NAMED ACTION…',
    release: 'RELEASE EVIDENCE',
    synthetic: 'SYNTHETIC COMPETITION DATA · NO CUSTOMER DATA',
    actionRequired: 'Every hand-off requires an explicit role-bound action',
    error: 'JURY FLOW FAILED',
  },
} as const;

const FLOW_LABELS = {
  zh: {
    session: '创建会话',
    analyze: 'AI 分析',
    project_manager_approve: 'PM 审批',
    hse_manager_approve: 'HSE 会签',
    execute: '文控执行',
    verify: '独立核验',
    close: '函件流程关闭',
  },
  en: {
    session: 'CREATE',
    analyze: 'ANALYZE',
    project_manager_approve: 'PM APPROVE',
    hse_manager_approve: 'HSE APPROVE',
    execute: 'EXECUTE',
    verify: 'VERIFY',
    close: 'DOCUMENT CLOSE',
  },
} satisfies Record<'zh' | 'en', Record<FlowStep, string>>;

const ACTION_LABELS = {
  zh: {
    session: '创建隔离评委会话',
    analyze: '以项目经理身份发起 AI 分析',
    project_manager_approve: '以项目经理身份审批',
    hse_manager_approve: '以 HSE 经理身份会签',
    execute: '以文控执行人身份生成草稿',
    verify: '以独立核验人身份核验',
    close: '以第五主体身份关闭函件处理流程',
  },
  en: {
    session: 'CREATE ISOLATED JURY SESSION',
    analyze: 'ANALYZE AS PROJECT MANAGER',
    project_manager_approve: 'APPROVE AS PROJECT MANAGER',
    hse_manager_approve: 'CO-SIGN AS HSE MANAGER',
    execute: 'GENERATE DRAFT AS DOCUMENT EXECUTOR',
    verify: 'VERIFY AS INDEPENDENT VERIFIER',
    close: 'CLOSE DOCUMENT WORKFLOW',
  },
} satisfies Record<'zh' | 'en', Record<FlowStep, string>>;

const ROLE_LABELS = {
  zh: {
    project_manager: '项目经理',
    hse_manager: 'HSE 经理',
    engineer: '文控执行人',
    verifier: '独立核验人',
    closer: '关闭责任人',
  },
  en: {
    project_manager: 'PROJECT MANAGER',
    hse_manager: 'HSE MANAGER',
    engineer: 'DOCUMENT EXECUTOR',
    verifier: 'INDEPENDENT VERIFIER',
    closer: 'SEPARATE CLOSER',
  },
} satisfies Record<'zh' | 'en', Record<SandboxRole, string>>;

function compact(value?: string | null) {
  return value ? `${value.slice(0, 9)}…${value.slice(-7)}` : '—';
}

function formatCountdown(elapsed: number) {
  const remaining = Math.max(0, 300 - elapsed);
  return `${String(Math.floor(remaining / 60)).padStart(2, '0')}:${String(remaining % 60).padStart(2, '0')}`;
}

function formatElapsed(elapsed: number) {
  return `${String(Math.floor(elapsed / 60)).padStart(2, '0')}:${String(elapsed % 60).padStart(2, '0')}`;
}

function localizedText(
  value: LocalizedText,
  locale: 'zh' | 'en',
) {
  return typeof value === 'string' ? value : value[locale] ?? value.en;
}

function completedFlow(state: SandboxState | null) {
  const completed = new Set<FlowStep>();
  if (!state) return completed;
  completed.add('session');
  if (state.action) completed.add('analyze');
  if (state.approvals.some(row => row.required_role === 'project_manager' && row.status === 'APPROVED')) {
    completed.add('project_manager_approve');
  }
  if (state.approvals.some(row => row.required_role === 'hse_manager' && row.status === 'APPROVED')) {
    completed.add('hse_manager_approve');
  }
  if (state.receipts.execution) completed.add('execute');
  if (state.receipts.verification?.status === 'VERIFIED') completed.add('verify');
  if (state.complete) completed.add('close');
  return completed;
}

function currentRoleStatus(role: SandboxRole, state: SandboxState | null) {
  if (!state) return 'WAITING';
  if (role === 'project_manager') {
    return state.approvals.find(row => row.required_role === role)?.status ?? 'WAITING';
  }
  if (role === 'hse_manager') {
    return state.approvals.find(row => row.required_role === role)?.status ?? 'WAITING';
  }
  if (role === 'engineer') return state.receipts.execution?.status ?? 'WAITING';
  if (role === 'verifier') return state.receipts.verification?.status ?? 'WAITING';
  return state.complete ? 'CLOSED' : 'WAITING';
}

function nextRole(step?: string): SandboxRole {
  if (step === 'hse_manager_approve') return 'hse_manager';
  if (step === 'execute') return 'engineer';
  if (step === 'verify') return 'verifier';
  if (step === 'close') return 'closer';
  return 'project_manager';
}

function businessStateFingerprint(state: SandboxState) {
  return JSON.stringify({
    session: { id: state.session.id, status: state.session.status },
    approvals: state.approvals.map(row => ({
      id: row.id,
      status: row.status,
      decidedBy: row.decided_by,
      digest: row.decision_digest,
    })),
    action: state.action ? {
      id: state.action.id,
      status: state.action.status,
      proposalDigest: state.action.proposal_digest,
      closureDigest: state.action.closure_digest,
    } : null,
    execution: state.receipts.execution?.receipt_digest ?? null,
    verification: state.receipts.verification?.verification_digest ?? null,
    artifact: state.receipts.artifact?.digest ?? null,
    evidence: state.evidence.map(row => ({
      id: row.id,
      sourceRef: row.source_ref,
      verified: row.verified,
    })),
    complete: state.complete,
  });
}

function JuryFlowRail({
  state,
  locale,
}: {
  state: SandboxState | null;
  locale: 'zh' | 'en';
}) {
  const completed = completedFlow(state);
  const nextStep = (state?.next_steps[0] ?? 'session') as FlowStep;
  return (
    <ol className="jury-flow" aria-label="Jury workflow">
      {FLOW_STEPS.map((step, index) => (
        <li
          className={completed.has(step) ? 'done' : nextStep === step ? 'active' : ''}
          aria-current={nextStep === step ? 'step' : undefined}
          key={step}
        >
          <span>{String(index + 1).padStart(2, '0')}</span>
          <b>{FLOW_LABELS[locale][step]}</b>
          <i>{completed.has(step) ? '✓' : index < FLOW_STEPS.length - 1 ? '→' : '○'}</i>
        </li>
      ))}
    </ol>
  );
}

function JuryRoleRail({
  sandbox,
  state,
  locale,
}: {
  sandbox: SandboxCreated | null;
  state: SandboxState | null;
  locale: 'zh' | 'en';
}) {
  const activeRole = nextRole(state?.next_steps[0]);
  return (
    <section className="jury-role-panel" aria-labelledby="jury-role-title">
      <header>
        <span>AUTHORITY</span>
        <h2 id="jury-role-title">{COPY[locale].roles}</h2>
      </header>
      <div className="jury-role-list">
        {ROLE_ORDER.map((role, index) => {
          const ticket = sandbox?.role_tickets[role];
          const status = currentRoleStatus(role, state);
          const active = Boolean(state && !state.complete && activeRole === role);
          return (
            <article className={`${status !== 'WAITING' ? 'done' : ''} ${active ? 'active' : ''}`} key={role}>
              <span>{String(index + 1).padStart(2, '0')}</span>
              <div>
                <b>{ROLE_LABELS[locale][role]}</b>
                <small>{ticket?.subject ?? 'IDENTITY ISSUED PER SESSION'}</small>
              </div>
              <i>{status}</i>
            </article>
          );
        })}
      </div>
      <footer>{COPY[locale].actionRequired}</footer>
    </section>
  );
}

function JuryClosureCard({
  state,
  elapsed,
  locale,
  boundary,
  tamper,
}: {
  state: SandboxState;
  elapsed: number;
  locale: 'zh' | 'en';
  boundary: BoundaryProbe;
  tamper: TamperProbe;
}) {
  const execution = state.receipts.execution;
  const verification = state.receipts.verification;
  return (
    <section className="jury-closure-card" aria-labelledby="jury-closure-title">
      <header>
        <div>
          <span>{COPY[locale].complete}</span>
          <h2 id="jury-closure-title">{COPY[locale].finalCard}</h2>
          <p>{COPY[locale].finalSubtitle}</p>
        </div>
        <strong>✓</strong>
      </header>
      <p role="status" style={{padding: 12, border: "1px solid var(--line)", borderRadius: 8, color: "var(--amber)", marginTop: 10, marginBottom: 10}}>
        {locale === "zh"
          ? "范围说明：仅关闭已核验的函件草稿流程。现场高处作业隐患尚未复检，不能视为整改完成或项目安全事件关闭。"
          : "Scope: Only the verified document-draft workflow is closed. No physical hazard reinspection, remediation or project safety-case closure is claimed."}
      </p>
      <div className="jury-closure-grid">
        <article><span>SESSION</span><b>{state.session.id}</b><small>{state.case.id}</small></article>
        <article><span>PM + HSE</span><b>{state.approvals.filter(row => row.status === 'APPROVED').length} / 2 APPROVED</b><small>{state.approvals.map(row => row.decided_by).filter(Boolean).join(' · ')}</small></article>
        <article><span>EXECUTION</span><b>{execution?.status ?? 'MISSING'}</b><small>{compact(execution?.receipt_digest)}</small></article>
        <article><span>VERIFICATION</span><b>{verification?.status ?? 'MISSING'}</b><small>{compact(verification?.verification_digest)}</small></article>
        <article><span>CLOSURE</span><b>{state.action?.status ?? 'MISSING'}</b><small>{compact(state.action?.closure_digest)}</small></article>
        <article><span>ELAPSED</span><b>{formatElapsed(elapsed)}</b><small>{state.governance.policy_version}</small></article>
        <article className={`jury-proof-authority ${boundary.status === 'BLOCKED' ? 'passed' : ''}`}>
          <span>AUTHORITY</span>
          <b>{boundary.status === 'BLOCKED' ? 'HTTP 403 · BLOCKED' : 'NOT RUN'}</b>
          <small>{boundary.status === 'BLOCKED' ? `${boundary.code ?? 'ROLE_SCOPE_REQUIRED'} · STATE UNCHANGED` : 'ROLE-BOUND SIGNED TICKETS'}</small>
        </article>
        <article className={`jury-proof-tamper ${tamper.status === 'INVALID_SIGNATURE' ? 'passed' : ''}`}>
          <span>TAMPER</span>
          <b>{tamper.status === 'INVALID_SIGNATURE' ? 'INVALID_SIGNATURE' : 'NOT RUN'}</b>
          <small>{tamper.status === 'INVALID_SIGNATURE' ? `${tamper.canonicalStatus ?? 'VERIFIED_INTACT'} · CANONICAL UNCHANGED` : 'IN-MEMORY COPY ONLY'}</small>
        </article>
      </div>
      <footer>
        <span>{COPY[locale].external}</span>
        <b>{state.governance.external_delivery_performed ? 'PERFORMED' : COPY[locale].notSent}</b>
        <code>{state.receipts.artifact?.delivery_status ?? 'DRAFT_ONLY_NOT_SENT'}</code>
      </footer>
    </section>
  );
}

export function JuryControlRoom({
  locale: rawLocale,
  golden,
  evidence,
}: {
  locale: string;
  golden: GoldenThread;
  evidence: SubmissionEvidence;
}) {
  const locale: 'zh' | 'en' = rawLocale === 'zh' ? 'zh' : 'en';
  const copy = COPY[locale];
  const labels = FLOW_LABELS[locale];
  const rootRef = useRef<HTMLDivElement>(null);
  const [sandbox, setSandbox] = useState<SandboxCreated | null>(null);
  const [state, setState] = useState<SandboxState | null>(null);
  const [boundary, setBoundary] = useState<BoundaryProbe>({ status: 'NOT_RUN' });
  const [tamper, setTamper] = useState<TamperProbe>({ status: 'NOT_RUN' });
  const [elapsed, setElapsed] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!sandbox || state?.complete) return;
    const timer = window.setInterval(
      () => setElapsed(value => Math.min(300, value + 1)),
      1000,
    );
    return () => window.clearInterval(timer);
  }, [sandbox, state?.complete]);

  const createSession = async () => {
    const response = await fetch('/backend/competition/sessions', { method: 'POST' });
    if (!response.ok) throw new Error(await response.text());
    const created = await response.json() as SandboxCreated;
    setSandbox(created);
    setState(created.state);
    setElapsed(0);
  };

  const postState = async (path: string, ticket: string) => {
    const response = await fetch(`/backend/competition/sessions${path}`, {
      method: 'POST',
      headers: { 'X-Competition-Role-Ticket': ticket },
    });
    if (!response.ok) throw new Error(await response.text());
    return response.json() as Promise<SandboxState>;
  };

  const runBoundaryProbe = async () => {
    if (!sandbox || !state?.action) return;
    const before = businessStateFingerprint(state);
    const response = await fetch(
      `/backend/competition/sessions/${state.session.id}/execute`,
      {
        method: 'POST',
        headers: {
          'X-Competition-Role-Ticket': sandbox.role_tickets.project_manager.ticket,
        },
      },
    );
    const payload = await response.json().catch(() => null) as { detail?: { code?: string } } | null;
    if (response.status !== 403 || payload?.detail?.code !== 'ROLE_SCOPE_REQUIRED') {
      throw new Error(`Boundary probe expected ROLE_SCOPE_REQUIRED/403, received ${response.status}`);
    }
    const stateResponse = await fetch(
      `/backend/competition/sessions/${state.session.id}/state`,
      { headers: { 'X-Competition-Role-Ticket': sandbox.role_tickets.project_manager.ticket } },
    );
    if (!stateResponse.ok) throw new Error(await stateResponse.text());
    const afterState = await stateResponse.json() as SandboxState;
    if (businessStateFingerprint(afterState) !== before) {
      throw new Error('Unauthorized probe changed the business state');
    }
    setState(afterState);
    setBoundary({ status: 'BLOCKED', httpStatus: 403, code: payload.detail.code });
  };

  const runTamperProbe = async () => {
    if (!sandbox || !state?.complete) return;
    const response = await fetch(
      `/backend/competition/sessions/${state.session.id}/tamper-probe`,
      {
        method: 'POST',
        headers: {
          'X-Competition-Role-Ticket': sandbox.role_tickets.closer.ticket,
        },
      },
    );
    if (!response.ok) throw new Error(await response.text());
    const result = await response.json() as {
      schema?: string;
      probe?: { status?: string; field?: string; signature_valid?: boolean };
      canonical?: { status?: string; unchanged?: boolean; signature_valid?: boolean };
    };
    if (
      result.probe?.status !== 'INVALID_SIGNATURE'
      || result.probe.signature_valid !== false
      || result.canonical?.status !== 'VERIFIED_INTACT'
      || result.canonical.unchanged !== true
      || result.canonical.signature_valid !== true
    ) {
      throw new Error('Tamper probe did not fail closed');
    }
    setTamper({
      status: 'INVALID_SIGNATURE',
      canonicalStatus: result.canonical.status,
      canonicalUnchanged: result.canonical.unchanged,
      mutation: result.probe.field,
    });
  };

  const advance = async () => {
    setBusy(true);
    setError('');
    try {
      if (!sandbox) {
        await createSession();
        return;
      }
      if (!state) throw new Error('Competition session state is missing');
      if (state.action && boundary.status === 'NOT_RUN') {
        await runBoundaryProbe();
        return;
      }
      if (state.complete) {
        await runTamperProbe();
        return;
      }
      const step = state.next_steps[0];
      const sessionId = state.session.id;
      let path: string;
      let role: SandboxRole;
      if (step === 'analyze') {
        path = `/${sessionId}/analyze`;
        role = 'project_manager';
      } else if (step === 'project_manager_approve' || step === 'hse_manager_approve') {
        role = step === 'project_manager_approve' ? 'project_manager' : 'hse_manager';
        const approval = state.approvals.find(row => row.required_role === role);
        if (!approval) throw new Error(`${role} approval is missing`);
        path = `/${sessionId}/approvals/${approval.id}/approve`;
      } else if (step === 'execute') {
        path = `/${sessionId}/execute`;
        role = 'engineer';
      } else if (step === 'verify') {
        path = `/${sessionId}/verify`;
        role = 'verifier';
      } else if (step === 'close') {
        path = `/${sessionId}/close`;
        role = 'closer';
      } else {
        throw new Error(`Unsupported jury step: ${step || 'none'}`);
      }
      setState(await postState(path, sandbox.role_tickets[role].ticket));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  };

  const reset = async () => {
    if (!sandbox || !state) return;
    setBusy(true);
    setError('');
    try {
      const response = await fetch(
        `/backend/competition/sessions/${state.session.id}/reset`,
        {
          method: 'POST',
          headers: {
            'X-Competition-Role-Ticket': sandbox.role_tickets.project_manager.ticket,
          },
        },
      );
      if (!response.ok) throw new Error(await response.text());
      const replacement = await response.json() as SandboxCreated & { replaces_session_id: string };
      setSandbox(replacement);
      setState(replacement.state);
      setBoundary({ status: 'NOT_RUN' });
      setTamper({ status: 'NOT_RUN' });
      setElapsed(0);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  };

  const fullscreen = () => {
    if (document.fullscreenElement) void document.exitFullscreen();
    else void rootRef.current?.requestFullscreen();
  };

  const nextStep = state?.next_steps[0] as FlowStep | undefined;
  const primaryLabel = !sandbox
    ? ACTION_LABELS[locale].session
    : busy
      ? copy.running
      : state?.action && boundary.status === 'NOT_RUN'
        ? copy.challengeRun
        : state?.complete && tamper.status === 'NOT_RUN'
          ? copy.tamperRun
          : state?.complete
            ? copy.complete
            : nextStep
              ? ACTION_LABELS[locale][nextStep]
              : copy.pending;
  const releaseVerified = evidence.release.evidence_status.startsWith('VERIFIED_');
  const twin = golden.twin;
  const liveEvidence: DisplayEvidence[] = state?.evidence.length
    ? state.evidence.map(row => ({
        source_ref: row.source_ref,
        title: localizedText(row.title, locale),
        verified: row.verified,
      }))
    : golden.evidence.length
      ? golden.evidence
      : [
          {
            source_ref: 'SYNTHETIC-OWNER-NOTICE',
            title: locale === 'zh' ? 'P47 高处作业合成业主来函' : 'Synthetic P47 work-at-height owner notice',
            verified: false,
            status: 'SYNTHETIC INPUT',
          },
          {
            source_ref: `${golden.country_pack.code}-${golden.country_pack.version}`,
            title: locale === 'zh' ? '马来西亚国家包与许可关卡' : 'Malaysia country pack and permit gates',
            verified: false,
            status: golden.country_pack.status,
          },
          {
            source_ref: twin?.twin_id ?? 'TWIN-MYRAIL-V12-P47',
            title: locale === 'zh' ? 'P47 合成数字孪生上下文' : 'Synthetic P47 digital-twin context',
            verified: false,
            status: 'SYNTHETIC DEMO',
          },
        ];

  return (
    <div className="jury-control-room" ref={rootRef}>
      <header className="jury-header">
        <div className="jury-brand">
          <span>GI</span>
          <div><b>GlobalInfra AI</b><small>{copy.eyebrow}</small></div>
        </div>
        <div className="jury-release">
          <span>{copy.release}</span>
          <b className={releaseVerified ? 'verified' : 'unverified'}>{evidence.release.evidence_status}</b>
          <code>{compact(evidence.release.deployment_commit)}</code>
        </div>
        <div className="jury-clock">
          <span>{copy.timer}</span>
          <strong>{formatCountdown(elapsed)}</strong>
        </div>
        <div className="jury-header-actions">
          <button type="button" onClick={fullscreen}>⛶ {copy.fullscreen}</button>
          <Link href="/competition">← {copy.exit}</Link>
        </div>
      </header>

      <JuryFlowRail state={state} locale={locale} />

      <main className="jury-grid">
        <section className="jury-incident" aria-labelledby="jury-incident-title">
          <header>
            <span>{copy.incident}</span>
            <b className="jury-risk">{state?.case.risk ?? golden.case.risk}</b>
          </header>
          <h1 id="jury-incident-title">{copy.title}</h1>
          <p className="jury-subtitle">{copy.subtitle}</p>
          <blockquote>{localizedText(state?.case.description ?? golden.case.description, locale)}</blockquote>
          <div className="jury-context-grid">
            <article><span>COUNTRY</span><b>{golden.project.country_code}</b><small>{golden.project.code}</small></article>
            <article><span>TWIN ID</span><b>{state?.case.twin_id ?? twin?.twin_id ?? 'TWIN-MYRAIL-V12-P47'}</b><small>{twin?.name ?? 'P47 SYNTHETIC PIER'}</small></article>
            <article><span>SCHEDULE</span><b>{twin?.schedule_variance_days ?? -8} DAYS</b><small>governed impact context</small></article>
            <article><span>COST</span><b>{twin?.cost_variance_m ?? 0.25} M</b><small>illustrative exposure</small></article>
          </div>
          <div className="jury-citations">
            <span>{copy.evidence} · {liveEvidence.length}</span>
            {liveEvidence.slice(0, 3).map((item, index) => (
              <article key={`${item.source_ref}-${index}`}>
                <b>{item.source_ref}</b>
                <p>{item.title}</p>
                <i>{item.status ?? (item.verified ? 'SOURCE-LINKED' : 'REVIEW REQUIRED')}</i>
              </article>
            ))}
          </div>
        </section>

        <section className="jury-live" aria-live="polite">
          {state?.complete ? (
            <JuryClosureCard
              state={state}
              elapsed={elapsed}
              locale={locale}
              boundary={boundary}
              tamper={tamper}
            />
          ) : (
            <>
              <header>
                <div><span>{copy.liveSession}</span><b>{state?.session.id ?? 'NOT STARTED'}</b></div>
                <i className={sandbox ? 'live' : ''}>{state?.session.status ?? 'READY'}</i>
              </header>
              <div className="jury-action-stage">
                <span>{state?.action ? `ACTION · ${state.action.id}` : 'GOVERNED ACTION'}</span>
                <h2>{state?.action && boundary.status === 'NOT_RUN' ? copy.challengeTitle : nextStep ? labels[nextStep] : copy.start}</h2>
                <p>{state?.action && boundary.status === 'NOT_RUN' ? copy.challengeHint : copy.actionRequired}</p>
                <button type="button" onClick={advance} disabled={busy}>
                  {busy && !sandbox ? copy.creating : primaryLabel}
                </button>
              </div>
              <div className={`jury-boundary-proof ${boundary.status === 'BLOCKED' ? 'passed' : ''}`}>
                <span>{copy.challenge}</span>
                <b>{boundary.status === 'BLOCKED' ? copy.challengePassed : 'NOT RUN'}</b>
                <small>{boundary.code ?? 'ROLE-BOUND SIGNED TICKETS'}</small>
              </div>
            </>
          )}

          {state?.complete ? (
            <div className={`jury-tamper-proof ${tamper.status === 'INVALID_SIGNATURE' ? 'passed' : ''}`}>
              <div><span>{copy.challenge}</span><b>{copy.tamperTitle}</b><small>{copy.tamperHint}</small></div>
              <strong>{tamper.status === 'INVALID_SIGNATURE' ? copy.tamperPassed : 'NOT RUN'}</strong>
              <button type="button" onClick={advance} disabled={busy || tamper.status === 'INVALID_SIGNATURE'}>
                {tamper.status === 'INVALID_SIGNATURE' ? copy.complete : copy.tamperRun}
              </button>
            </div>
          ) : null}

          {error ? <p className="jury-error" role="alert">{copy.error} · {error}</p> : null}
        </section>

        <JuryRoleRail sandbox={sandbox} state={state} locale={locale} />
      </main>

      <footer className="jury-footer">
        <span>{copy.synthetic}</span>
        <div>
          <code>{state?.governance.policy_version ?? 'globalinfra.sod.v6.2'}</code>
          <b>AI RECOMMENDS → HUMANS APPROVE → TOOL EXECUTES → INDEPENDENT VERIFY</b>
        </div>
        <button type="button" onClick={reset} disabled={!sandbox || busy}>↺ {copy.reset}</button>
      </footer>
    </div>
  );
}
