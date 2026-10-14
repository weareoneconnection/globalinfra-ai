'use client';

import Link from 'next/link';
import { useTranslations } from 'next-intl';
import { useMemo, useState } from 'react';

type Step={id:string;title:string;proof:string;status:string};
type EvidenceRow={source_ref:string;title:string;confidence:number;verified:boolean};
type AgentRow={name:string;status:string;summary:string;duration_ms:number};
type Approval={id:number;role:string;status:string;decided_by:string|null};
type Receipt={id:string;status:string;input_digest?:string;output_digest?:string;artifact_ref?:string;checks?:Record<string,boolean>;artifact_digest?:string};
export type GoldenThread={
  phase:string;positioning:string;case:{id:string;status:string;title:string;description:string;risk:string;deadline:string;synthetic:boolean};
  project:{id:number;code:string;name:string;country_code:string};
  intake:{country:string;lifecycle_stage:{id:string;name:string};case_type:string;case_type_label?:string;risk:string;confidence:number;recommended_agents:string[]};
  country_pack:{code:string;name:string;version:string;status:string;permit_count:number;disclaimer:string};
  steps:Step[];evidence:EvidenceRow[];agents:AgentRow[];approvals:Approval[];
  action:{id:string;type:string;status:string;evidence_refs:string[]}|null;
  twin:{twin_id:string;name:string;health_score:number;schedule_variance_days:number;cost_variance_m:number;interfaces:{type:string;status:string;uri:string}[]}|null;
  receipts:{execution:Receipt|null;verification:Receipt|null;artifact:{id:string;type:string;digest:string}|null};
  complete:boolean;governance:string;data_boundary:string;
  run?:{status:string;elapsed_ms:number;human_approval_recorded:boolean;external_delivery_performed:boolean};
};
type Evaluation={status:string;dataset_version:string;total_cases:number;passed_cases:number;metrics:Record<string,number>;thresholds:Record<string,number>;gates:Record<string,boolean>;category_coverage:Record<string,number>;method:string;data_boundary:string};
export type SubmissionEvidence={track:string;phase:string;three_routes:{id:string;label:string;proof:string}[];scorecard:{criterion:string;max_score:number;evidence:string}[];evaluation:Evaluation;reproducibility:{api:string;dataset:string;runner:string}};

const METRIC_KEYS=['country_accuracy','lifecycle_accuracy','risk_accuracy','top3_evidence_recall','citation_completeness','unsupported_query_abstention','schema_validity','deterministic_fallback_success'];
const compact=(value?:string)=>value?`${value.slice(0,10)}…${value.slice(-8)}`:'—';

export function CompetitionEvidence({initialGolden,evidence,locale}:{initialGolden:GoldenThread;evidence:SubmissionEvidence;locale:string}){
  const t=useTranslations('Competition');
  const [golden,setGolden]=useState(initialGolden);const [running,setRunning]=useState(false);const [error,setError]=useState('');const [selected,setSelected]=useState(0);
  const totalScore=evidence.scorecard.reduce((sum,row)=>sum+row.max_score,0);
  const metrics=useMemo(()=>METRIC_KEYS.map(key=>({key,value:evidence.evaluation.metrics[key]??0,gate:evidence.evaluation.gates[key]??true})),[evidence]);
  const run=async()=>{setRunning(true);setError('');try{const response=await fetch(`/backend/competition/golden-thread/run?lang=${locale}`,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({human_approval_confirmed:true,approver:'Competition demo operator'})});if(!response.ok){const detail=await response.text();throw new Error(detail)}const next=await response.json() as GoldenThread;setGolden(next);setSelected(next.steps.length-1)}catch(reason){setError(reason instanceof Error?reason.message:t('runFailed'))}finally{setRunning(false)}};
  const selectedStep=golden.steps[selected]||golden.steps[0];
  return <div className="competition-console">
    <section className="competition-routes">{evidence.three_routes.map((route,index)=><article key={route.id}><span>0{index+1}</span><div><b>{route.label}</b><p>{route.proof}</p></div><i>VERIFIED</i></article>)}</section>
    <section className="competition-main">
      <div className="card golden-thread">
        <header><div><span className="section-kicker">{t('goldenKicker')}</span><h3>{golden.positioning}</h3><p>{golden.project.code} · {golden.case.id} · {golden.data_boundary}</p></div><div className={`golden-state ${golden.complete?'complete':''}`}><i/><span>{golden.complete?t('closedLoop'):t('ready')}</span></div></header>
        <div className="golden-body">
          <ol className="golden-steps">{golden.steps.map((step,index)=><li className={selected===index?'active':''} key={step.id}><button onClick={()=>setSelected(index)}><span>{step.id}</span><div><b>{step.title}</b><small>{step.proof}</small></div><i>{step.status==='VERIFIED'?'✓':'→'}</i></button></li>)}</ol>
          <div className="golden-proof">
            <div className="proof-head"><span>{selectedStep.id}</span><div><b>{selectedStep.title}</b><small>{selectedStep.proof}</small></div><strong>{selectedStep.status}</strong></div>
            {selected<3?<EvidenceProof golden={golden}/>:selected===3?<EvidenceProof golden={golden}/>:selected===4?<TwinProof golden={golden}/>:selected===5?<AgentProof golden={golden}/>:<ReceiptProof golden={golden}/>}
          </div>
        </div>
        <footer><div><span>AI RECOMMENDS</span><i>→</i><span>HUMAN APPROVES</span><i>→</i><span>TOOL EXECUTES</span><i>→</i><span>INDEPENDENT VERIFY</span></div><button className="button" onClick={run} disabled={running}>{running?t('running'):golden.complete?t('replay'):t('runGolden')}</button></footer>
        {error?<p className="competition-error" role="alert">{t('runFailed')} · {error}</p>:null}
      </div>
      <aside className="competition-side">
        <section className="card eval-card"><header><div><span className="section-kicker">{t('evalKicker')}</span><h3>{t('evalTitle')}</h3></div><strong>{evidence.evaluation.status}</strong></header><div className="eval-total"><b>{evidence.evaluation.passed_cases}/{evidence.evaluation.total_cases}</b><span>{t('casesPassed')}</span><small>{evidence.evaluation.dataset_version}</small></div><div className="eval-metrics">{metrics.map(metric=><div key={metric.key}><span>{t.raw('metrics')[metric.key]||metric.key}</span><b>{metric.value}{metric.key.includes('latency')?'ms':'%'}</b><i className={metric.gate?'pass':'fail'}>{metric.gate?'PASS':'FAIL'}</i></div>)}</div><footer><a href="/backend/competition/evaluation?include_cases=true" target="_blank" rel="noreferrer">{t('openEvidence')} ↗</a><code>{evidence.reproducibility.runner}</code></footer></section>
      </aside>
    </section>
    <section className="competition-scorecard"><div className="scorecard-title"><div><span className="section-kicker">{t('scoreKicker')}</span><h3>{t('scoreTitle')}</h3></div><strong>{totalScore}<small> / 100</small></strong></div>{evidence.scorecard.map(row=><article key={row.criterion}><span>{row.max_score}</span><div><b>{row.criterion}</b><p>{row.evidence}</p></div><i>READY</i></article>)}<div className="competition-actions"><Link className="button secondary" href="/showcase?project_id=1">{t('open180')} ↗</Link><Link className="button secondary" href="/country-packs">{t('openCountry')} ↗</Link><Link className="button secondary" href="/knowledge">{t('openKnowledge')} ↗</Link></div></section>
  </div>;
}

function EvidenceProof({golden}:{golden:GoldenThread}){return <div className="proof-stack"><div className="intake-receipt"><span>INPUT</span><p>{golden.case.description}</p><div><b>{golden.intake.country}</b><b>{golden.intake.lifecycle_stage.name}</b><b>{golden.intake.case_type_label||golden.intake.case_type}</b><b className="risk">{golden.intake.risk}</b></div></div><div className="evidence-list">{golden.evidence.length?golden.evidence.slice(0,5).map(row=><article key={row.source_ref}><span>{row.verified?'✓':'!'}</span><div><b>{row.source_ref}</b><small>{row.title}</small></div><strong>{Math.round(row.confidence*100)}%</strong></article>):<div className="proof-empty">Run the golden thread to generate live evidence citations.</div>}</div></div>}
function TwinProof({golden}:{golden:GoldenThread}){const twin=golden.twin;return twin?<div className="twin-proof"><div className="twin-proof-core"><span>TWIN ID</span><b>{twin.twin_id}</b><small>{twin.name}</small><dl><div><dt>HEALTH</dt><dd>{twin.health_score}%</dd></div><div><dt>SCHEDULE</dt><dd>{twin.schedule_variance_days}d</dd></div><div><dt>COST</dt><dd>+{twin.cost_variance_m}M</dd></div></dl></div><div className="twin-interface-proof">{twin.interfaces.map(item=><a href={item.uri} target="_blank" rel="noreferrer" key={item.type}><span>{item.type.replace('_',' ')}</span><b>{item.status}</b><i>↗</i></a>)}</div></div>:<div className="proof-empty">Twin context unavailable.</div>}
function AgentProof({golden}:{golden:GoldenThread}){return <div className="agent-proof"><div>{golden.agents.map((agent,index)=><article key={`${index}-${agent.name}`}><span>{String(index+1).padStart(2,'0')}</span><div><b>{agent.name}</b><p>{agent.summary}</p></div><i>{agent.status}</i></article>)}</div><footer>{golden.approvals.map(row=><span key={row.id}><b>{row.role}</b><i>{row.status}</i><small>{row.decided_by||'HUMAN REQUIRED'}</small></span>)}</footer></div>}
function ReceiptProof({golden}:{golden:GoldenThread}){const execution=golden.receipts.execution;const verification=golden.receipts.verification;return <div className="receipt-proof"><div className="receipt-flow"><span className={execution?'done':''}>APPROVAL</span><i>→</i><span className={execution?'done':''}>EXECUTION</span><i>→</i><span className={verification?'done':''}>VERIFY</span><i>→</i><span className={golden.complete?'done':''}>CLOSE</span></div>{execution?<><article><span>EXECUTION RECEIPT</span><b>{execution.id}</b><small>INPUT · {compact(execution.input_digest)}</small><small>OUTPUT · {compact(execution.output_digest)}</small></article>{verification?<article><span>VERIFICATION RECEIPT</span><b>{verification.id}</b><div>{Object.entries(verification.checks||{}).map(([key,value])=><i className={value?'pass':'fail'} key={key}>{value?'✓':'×'} {key.replaceAll('_',' ')}</i>)}</div><small>ARTIFACT · {compact(verification.artifact_digest)}</small></article>:null}</>:<div className="proof-empty">Explicit human confirmation will run the governed draft generator and independent verifier. No external delivery occurs.</div>}</div>}
