import Link from 'next/link';
import { getTranslations } from 'next-intl/server';
import { api } from '@/lib/api';

type Card = {
  id: string; name: string; group: string; role: string; risk_level: string; focus: string; tools: string[];
  authority: string; version: string; governance: boolean; evidence_policy: string; escalation: string | null; countries: string[];
};
type Run = {
  run_id: string; case_id: string; title: string | null; created_at: string; passed: boolean | null;
  consistency_score: number | null; model_calls: number | null; team: { agent_id: string; name: string; source: string }[];
};
type Score = {
  agent_id: string; name: string; runs: number; supported_rate: number | null; gap_rate: number | null;
  needs_input_rate: number | null; llm_share: number | null; avg_duration_ms: number | null; rejected_cases: number;
};

const pct = (value: number | null) => value === null ? '—' : `${Math.round(value * 100)}%`;

export default async function Agents() {
  const t = await getTranslations('Agents');
  const [cards, runs, scores] = await Promise.all([
    api<Card[]>('/agents/cards'), api<Run[]>('/agents/runs?limit=12'), api<Score[]>('/agents/scorecards'),
  ]);
  const specialists = cards.filter(card => !card.governance);
  const groups = [...new Set(specialists.map(card => card.group))];
  const flow = t.raw('flow') as { title: string; text: string }[];
  const active = scores.filter(score => score.runs > 0);

  return <>
    <div className="header-row">
      <div><div className="eyebrow">{t('eyebrow')}</div><h2 className="page-title">{t('title')}</h2><p className="page-subtitle">{t('subtitle')}</p></div>
      <span className="badge ok">{t('available', { count: specialists.length })} · v{cards[0]?.version}</span>
    </div>

    <div className="org-flow">{flow.map((step, index) => <div className="org-flow-step" key={step.title}>
      <span>{index + 1}</span><b>{step.title}</b><small>{step.text}</small>
    </div>)}</div>

    <section className="card section">
      <div className="section-title"><div><span className="section-kicker">{t('runsKicker')}</span><h3>{t('runsTitle')}</h3></div><span>{t('runsCount', { count: runs.length })}</span></div>
      {runs.length === 0 ? <p className="muted org-empty">{t('runsEmpty')}</p> : <div className="org-table">
        <div className="org-row head"><span>{t('colCase')}</span><span>{t('colTeam')}</span><span>{t('colConsistency')}</span><span>{t('colModelCalls')}</span><span>{t('colChecks')}</span></div>
        {runs.map(run => <div className="org-row" key={run.run_id}>
          <span><Link href={`/cases/${run.case_id}`}>{run.case_id}</Link><small>{run.title}</small></span>
          <span className="org-team">{run.team.map(member => <i key={member.agent_id} className={member.source}>{member.name}</i>)}</span>
          <span>{pct(run.consistency_score)}</span>
          <span>{run.model_calls ?? 0}</span>
          <span className={`badge ${run.passed ? 'ok' : 'high'}`}>{run.passed ? t('checksPassed') : t('checksFailed')}</span>
        </div>)}
      </div>}
    </section>

    <section className="card section">
      <div className="section-title"><div><span className="section-kicker">{t('scoreKicker')}</span><h3>{t('scoreTitle')}</h3></div><span>{t('scoreNote')}</span></div>
      {active.length === 0 ? <p className="muted org-empty">{t('runsEmpty')}</p> : <div className="org-table">
        <div className="org-row head score"><span>{t('colAgent')}</span><span>{t('colRuns')}</span><span>{t('colSupported')}</span><span>{t('colGap')}</span><span>{t('colInput')}</span><span>{t('colLlm')}</span><span>{t('colRejected')}</span></div>
        {active.map(score => <div className="org-row score" key={score.agent_id}>
          <span>{score.name}</span><span>{score.runs}</span><span>{pct(score.supported_rate)}</span><span>{pct(score.gap_rate)}</span>
          <span>{pct(score.needs_input_rate)}</span><span>{pct(score.llm_share)}</span><span>{score.rejected_cases}</span>
        </div>)}
      </div>}
    </section>

    {groups.map(group => <section className="agent-group section" key={group}>
      <div className="outside-title"><div><span className="section-kicker">{t('practiceKicker')}</span><h3>{group}</h3></div><span>{t('agentsCount', { count: specialists.filter(card => card.group === group).length })}</span></div>
      <div className="agent-grid">{specialists.filter(card => card.group === group).map(card => <div className="agent-card" key={card.id}>
        <div className="agent-card-head"><div className="agent-icon">{card.name.slice(0, 2)}</div><span className="badge info">{t('advisory')}</span></div>
        <h4>{card.name}</h4>
        <p>{card.focus}</p>
        <div className="tool-list">{card.tools.map(tool => <span key={tool}>{tool}</span>)}</div>
        <p className="org-policy">{card.evidence_policy}</p>
        {card.escalation && <p className="org-policy"><b>{t('escalation')}</b>{card.escalation}</p>}
        {card.countries.length > 0 && <p className="org-policy"><b>{t('countryVariants')}</b>{card.countries.join(' / ')}</p>}
      </div>)}</div>
    </section>)}
  </>;
}
