import Link from 'next/link';
import { getLocale } from 'next-intl/server';
import { api } from '@/lib/api';
import styles from './finals.module.css';

type MissionStep = {
  id: string;
  index: string;
  name: string;
  status: string;
  detail: string;
  evidence_ref: string;
};
type ScoreItem = {
  id: string;
  category: string;
  criterion: string;
  max_score: number;
  evidence: string;
  evidence_ids: string[];
};
type Country = {
  code: string;
  name: string;
  version?: string | null;
  status: string;
  release_gate: string;
  languages: string[];
  authorities: string[];
  permit_gates: string[];
  source_type?: string;
};
type FinalsOverview = {
  schema: string;
  product_version: string;
  edition: string;
  track: string;
  scoring_standard: string;
  scenario: {
    id: string;
    title: string;
    description: string;
    project_code: string;
    country_code: string;
    risk: string;
    deadline: string;
    data_boundary: string;
    synthetic: boolean;
    evidence: { source_ref: string; title: string; source_status: string }[];
  };
  mission: {
    steps: MissionStep[];
    document_workflow: string;
    physical_hazard: string;
    project_safety_case_closed: boolean;
    external_delivery_performed: boolean;
    runtime: string;
    authority: string;
  };
  release: {
    status: string;
    commit: string;
    verified_cases: number;
    total_cases: number;
    ci_run: string;
    verification_reason: string[];
  };
  business_impact: {
    model_comparison: { status: string; verified_score: number | null; method: string; boundary: string };
    paired_roi: {
      status: string;
      baseline_minutes: number | null;
      assisted_minutes: number | null;
      improvement_percent: number | null;
      boundary: string;
    };
  };
  country_adaptation: {
    status: string;
    first: Country;
    second: Country;
    differences: { languages: boolean; authorities: boolean; permit_gates: boolean };
    boundary: string;
  };
  scorecard: ScoreItem[];
  limits: string[];
};

const COPY = {
  zh: {
    eyebrow: 'GLOBALINFRA AI  /  FINALIST EDITION',
    title: '一个海外工程问题，',
    titleAccent: '一条可信行动链。',
    intro: '从跨语言业主通知，到属地知识、多专业AI协同、人工授权与可复核交付。不是展示更多功能，而是展示每一步的业务责任与证据。',
    openJury: '进入可信执行演示',
    openEvidence: '查看完整技术证据',
    keyIssue: '真实行业问题 · 合成案例验证',
    status: '风险等级',
    deadline: '响应期限',
    country: '项目国家',
    boundary: '数据边界',
    scenario: '海外工程黄金主线',
    steps: '一条可复核的六阶段任务链',
    governed: '人类保留决策权，AI负责生成有依据的建议与草案。',
    method: '工程责任与交付状态',
    doc: '函件工作流',
    field: '现场隐患',
    delivery: '外部发送',
    notDelivered: '未发送',
    handoff: '下一个真实世界动作：现场整改与独立复检。',
    evidenceHeader: '三项决赛关键证据',
    realModel: '真实模型对照',
    roi: '项目经济效益',
    release: '受信发布',
    modelHelp: '四组模型对照必须使用获授权的盲测数据与真实运行链路。',
    roiHelp: '不能把固定合成测试结果换算成节省工时或资金。',
    releaseHelp: '这里显示当前部署的签名证据状态，不以CI绿灯替代生产证明。',
    noResult: '尚无可公开验证结果',
    config: '可配置的跨国能力',
    configHelp: '使用同一套核心契约比较两个国家包的语言、主管机关与许可要求；展示的是配置能力，不是当地法律合规认证。',
    comparison: 'Country Pack 配置对照',
    languages: '语言',
    authorities: '主管机关索引',
    permitGates: '许可关卡',
    scores: '决赛11项评分与证据映射',
    scoreHelp: '表格展示官方指标权重与系统中的证据说明，绝非评委已给分数。',
    weight: '权重',
    scope: '必须公开的证明边界',
    fromCI: '技术证据中心',
    viewOriginal: '审查原始工作流',
    statusLegend: '状态均来自现有记录或明确的未验证标记，非现场成效预测。',
    phaseStatus: '当前状态',
    signed: '已签名结果',
    sample: '参赛合成样本',
    modelNone: '真实对照未运行',
    notVerified: '未验证',
  },
  en: {
    eyebrow: 'GLOBALINFRA AI  /  FINALIST EDITION',
    title: 'One overseas issue.',
    titleAccent: 'One accountable action chain.',
    intro: 'From a multilingual owner notice to country context, specialist AI coordination, human authority, and verifiable delivery. Every claim has an explicit evidence boundary.',
    openJury: 'Open governed-action proof',
    openEvidence: 'Inspect technical evidence',
    keyIssue: 'REAL INDUSTRY PROBLEM · SYNTHETIC TEST CASE',
    status: 'Risk level',
    deadline: 'Response window',
    country: 'Country',
    boundary: 'Data scope',
    scenario: 'Overseas engineering golden thread',
    steps: 'Six evidence-linked mission stages',
    governed: 'Humans retain decision rights. AI drafts recommendations and documents.',
    method: 'Delivery accountability',
    doc: 'Document workflow',
    field: 'Physical hazard',
    delivery: 'External delivery',
    notDelivered: 'Not sent',
    handoff: 'Next actual field action: physical remediation and independent reinspection.',
    evidenceHeader: 'Three proofs that matter to finalists',
    realModel: 'Real-model comparison',
    roi: 'Quantified business value',
    release: 'Trusted release',
    modelHelp: 'Four-arm comparison requires authorized blind data and real governed execution.',
    roiHelp: 'Synthetic regression is not evidence of labor or financial savings.',
    releaseHelp: 'Current deployed evidence verification, not a substitute CI success badge.',
    noResult: 'No public verified result yet',
    config: 'Cross-border by configuration',
    configHelp: 'Compare two country packages using common core contracts. This proves configuration differences, not legal certification or a foreign production deployment.',
    comparison: 'Country Pack configuration',
    languages: 'Languages',
    authorities: 'Authority indexes',
    permitGates: 'Permit gates',
    scores: 'Official 11-item finals evidence map',
    scoreHelp: 'The weights are official criterion maxima, not awarded or forecast marks.',
    weight: 'Weight',
    scope: 'Non-negotiable evidence boundaries',
    fromCI: 'Technical evidence center',
    viewOriginal: 'Review existing execution proof',
    statusLegend: 'Statuses derive from existing records or explicit unverified gates.',
    phaseStatus: 'Evidence status',
    signed: 'Signed release cases',
    sample: 'Synthetic competition fixture',
    modelNone: 'Real comparison NOT_RUN',
    notVerified: 'Not verified',
  },
} as const;

function statusTone(value: string) {
  if (value === 'VERIFIED_PASSED' || value === 'DRAFT_VERIFIED' || value === 'APPROVED' || value === 'REVIEW_RECORDED') {
    return styles.pass;
  }
  if (value === 'NOT_RUN' || value === 'NOT_VERIFIED' || value === 'NO_AUDITED_PUBLIC_RESULT' || value.includes('REVIEW') || value.includes('AWAITING')) {
    return styles.wait;
  }
  return styles.neutral;
}

function PrettyStatus({ value }: { value: string }) {
  return <span className={`${styles.state} ${statusTone(value)}`}>{value.replaceAll('_', ' ')}</span>;
}

function CountryCard({ data, labels }: { data: Country; labels: (typeof COPY)['en'] }) {
  return (
    <article className={styles.countryCard}>
      <div className={styles.countryHead}>
        <div className={styles.countryCode}>{data.code}</div>
        <div>
          <strong>{data.name}</strong>
          <small>{data.version ?? 'VERSION NOT CONFIGURED'}</small>
        </div>
      </div>
      <PrettyStatus value={data.release_gate} />
      <dl className={styles.countrySpecs}>
        <div><dt>{labels.languages}</dt><dd>{data.languages.join(' · ') || '—'}</dd></div>
        <div><dt>{labels.authorities}</dt><dd>{data.authorities.join(' · ') || '—'}</dd></div>
        <div><dt>{labels.permitGates}</dt><dd>{data.permit_gates.length}</dd></div>
      </dl>
    </article>
  );
}

export default async function FinalsPage() {
  const locale = (await getLocale()) === 'zh' ? 'zh' : 'en';
  const t = COPY[locale];
  // Only the allowlisted, synthetic-safe projection can be called publicly.
  // Tenant-scoped /pilot/roi-summary must never be used by this route.
  const overview = await api<FinalsOverview>('/competition/finals/overview');
  if (overview.schema !== 'globalinfra.finals-mission.v1' ||
      overview.scenario.synthetic !== true ||
      overview.scenario.data_boundary !== 'SYNTHETIC_COMPETITION_ONLY' ||
      overview.scoring_standard !== 'C4AI_2026_FINAL_AI_OUTBOUND_11_ITEMS') {
    throw new Error('Finals evidence boundary failed closed');
  }
  const totalWeight = overview.scorecard.reduce((sum, row) => sum + row.max_score, 0);
  if (overview.scorecard.length !== 11 || totalWeight !== 100) {
    throw new Error('Finals scorecard mismatch');
  }
  return (
    <div className={styles.page}>
      <section className={styles.hero}>
        <div className={styles.topline}>
          <span>{t.eyebrow}</span>
          <span className={styles.edition}>P2 · {overview.product_version}</span>
        </div>
        <div className={styles.heroGrid}>
          <div className={styles.heroWords}>
            <h1>{t.title}<br/><em>{t.titleAccent}</em></h1>
            <p>{t.intro}</p>
            <div className={styles.heroLinks}>
              <Link href="/competition/jury" className={styles.primaryLink}>{t.openJury} <span aria-hidden>↗</span></Link>
              <Link href="/competition" className={styles.secondaryLink}>{t.openEvidence} <span aria-hidden>↗</span></Link>
            </div>
          </div>
          <div className={styles.missionBadge}>
            <span className={styles.eyebrow}>OVERSEAS MISSION / MY-RAIL-A</span>
            <div className={styles.badgeSymbol} aria-hidden="true">GI<span>●</span></div>
            <div className={styles.badgeLines}>
              <span>01 / INTAKE</span><span>02 / INTELLIGENCE</span><span>03 / HUMAN AUTHORITY</span><span>04 / VERIFIED DRAFT</span>
            </div>
            <small>{t.sample} · {overview.scenario.id}</small>
          </div>
        </div>
        <div className={styles.heroFoot}>
          <span>{overview.track}</span>
          <span>{t.statusLegend}</span>
        </div>
      </section>

      <section className={styles.issue} aria-label={t.scenario}>
        <div className={styles.sectionTop}>
          <div><span className={styles.kicker}>01 / GLOBAL ISSUE</span><h2>{t.scenario}</h2></div>
          <span className={styles.risk}>{overview.scenario.risk}</span>
        </div>
        <h3>{overview.scenario.title}</h3>
        <p className={styles.issueDescription}>{overview.scenario.description}</p>
        <div className={styles.facts}>
          <div><small>{t.country}</small><strong>{overview.scenario.country_code}</strong></div>
          <div><small>{t.status}</small><strong>{overview.scenario.risk}</strong></div>
          <div><small>{t.deadline}</small><strong>{overview.scenario.deadline}</strong></div>
          <div><small>{t.boundary}</small><strong>SYNTHETIC</strong></div>
        </div>
      </section>

      <section className={styles.section} id="mission">
        <div className={styles.sectionTop}>
          <div><span className={styles.kicker}>02 / GOVERNED INTELLIGENCE</span><h2>{t.steps}</h2></div>
          <span className={styles.muted}>{overview.mission.steps.length} STAGES</span>
        </div>
        <div className={styles.missionGrid}>
          {overview.mission.steps.map(step => (
            <article className={styles.stepCard} key={step.id}>
              <div className={styles.stepTop}><span>{step.index}</span><PrettyStatus value={step.status}/></div>
              <h3>{step.name}</h3>
              <p>{step.detail}</p>
              <small className={styles.ref}>{step.evidence_ref}</small>
            </article>
          ))}
        </div>
        <div className={styles.accountability}>
          <div>
            <span className={styles.kicker}>HUMAN ACCOUNTABILITY</span>
            <strong>{t.governed}</strong>
            <small>{t.handoff}</small>
          </div>
          <div className={styles.outcomes}>
            <div><span>{t.doc}</span><PrettyStatus value={overview.mission.document_workflow}/></div>
            <div><span>{t.field}</span><PrettyStatus value={overview.mission.physical_hazard}/></div>
            <div><span>{t.delivery}</span><strong>{t.notDelivered}</strong></div>
          </div>
        </div>
      </section>

      <section className={styles.section} id="impact">
        <div className={styles.sectionTop}>
          <div><span className={styles.kicker}>03 / MEASURABLE EVIDENCE</span><h2>{t.evidenceHeader}</h2></div>
        </div>
        <div className={styles.proofGrid}>
          <article className={styles.proofCard}>
            <span className={styles.cardNum}>01 · INTELLIGENCE</span>
            <h3>{t.realModel}</h3>
            <PrettyStatus value={overview.business_impact.model_comparison.status}/>
            <strong className={styles.emptyValue}>{t.noResult}</strong>
            <p>{overview.business_impact.model_comparison.boundary}</p>
            <small>{t.modelHelp}</small>
          </article>
          <article className={styles.proofCard}>
            <span className={styles.cardNum}>02 · BUSINESS</span>
            <h3>{t.roi}</h3>
            <PrettyStatus value={overview.business_impact.paired_roi.status}/>
            <strong className={styles.emptyValue}>{overview.business_impact.paired_roi.improvement_percent === null ? '—' : overview.business_impact.paired_roi.improvement_percent + '%'}</strong>
            <p>{overview.business_impact.paired_roi.boundary}</p>
            <small>{t.roiHelp}</small>
          </article>
          <article className={styles.proofCard}>
            <span className={styles.cardNum}>03 · RELEASE INTEGRITY</span>
            <h3>{t.release}</h3>
            <PrettyStatus value={overview.release.status}/>
            <strong className={styles.releaseValue}>{overview.release.verified_cases} / {overview.release.total_cases}</strong>
            <p>{t.releaseHelp}</p>
            <small>COMMIT · {overview.release.commit}</small>
          </article>
        </div>
      </section>

      <section className={styles.section} id="countries">
        <div className={styles.sectionTop}>
          <div><span className={styles.kicker}>04 / REUSABLE CORE</span><h2>{t.config}</h2></div>
          <PrettyStatus value={overview.country_adaptation.status}/>
        </div>
        <p className={styles.sectionLead}>{t.configHelp}</p>
        <div className={styles.countryGrid}>
          <CountryCard data={overview.country_adaptation.first} labels={t}/>
          <div className={styles.countryBetween} aria-hidden>≠</div>
          <CountryCard data={overview.country_adaptation.second} labels={t}/>
        </div>
        <p className={styles.boundaryText}>{overview.country_adaptation.boundary}</p>
      </section>

      <section className={styles.section} id="scoring">
        <div className={styles.sectionTop}>
          <div><span className={styles.kicker}>05 / OFFICIAL CRITERIA</span><h2>{t.scores}</h2></div>
          <span className={styles.weightTotal}>11 ITEMS / {totalWeight} POINTS</span>
        </div>
        <p className={styles.sectionLead}>{t.scoreHelp}</p>
        <div className={styles.scoreWrap}>
          <table className={styles.scoreTable}>
            <thead><tr><th>{overview.track}</th><th>{t.method}</th><th>{t.weight}</th></tr></thead>
            <tbody>{overview.scorecard.map(row => (
              <tr key={row.id}><td><strong>{row.criterion}</strong><small>{row.category}</small></td><td>{row.evidence}</td><td><strong>{row.max_score}</strong></td></tr>
            ))}</tbody>
          </table>
        </div>
      </section>
      <section className={styles.disclaimer}>
        <span className={styles.kicker}>06 / EVIDENCE BOUNDARIES</span>
        <h2>{t.scope}</h2>
        <ul>{overview.limits.map((limit,i)=><li key={i}>{limit}</li>)}</ul>
        <div className={styles.footerLinks}><Link href="/competition">{t.fromCI} ↗</Link><Link href="/competition/jury">{t.viewOriginal} ↗</Link></div>
      </section>
    </div>
  );
}
