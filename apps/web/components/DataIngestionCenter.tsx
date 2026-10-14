'use client';

import { FormEvent, ReactNode, useState } from 'react';
import { useLocale, useTranslations } from 'next-intl';

type Project = { id: number; code: string; name: string };
type ChannelId = 'event_work_order' | 'document_correspondence' | 'project_master' | 'enterprise_connector' | 'twin_model' | 'iot_telemetry';
type Channel = {
  id: ChannelId;
  code: string;
  icon: string;
  name: string;
  description: string;
  source_types: string[];
  canonical_objects: string[];
  endpoint: string;
  event_policy: string;
};
type Receipt = {
  id: string;
  project_id: number | null;
  channel: ChannelId;
  source_type: string;
  status: string;
  records_received: number;
  records_accepted: number;
  records_rejected: number;
  target_type: string;
  target_id: string | null;
  mapping_version: string;
  validation_summary: Record<string, unknown>;
  lineage: Record<string, unknown>;
  created_at: string;
};

export type IngestionCatalog = {
  version: string;
  channel_count: number;
  principle: string;
  channels: Channel[];
};

export type IngestionSummary = {
  channel_count: number;
  active_channels: number;
  operations: number;
  records_accepted: number;
  records_rejected: number;
  by_channel: Record<ChannelId, { operations: number; accepted: number; rejected: number }>;
  by_status: Record<string, number>;
  recent: Receipt[];
};

type Props = { projects: Project[]; catalog: IngestionCatalog; initialSummary: IngestionSummary };

function FormField({ label, hint, children, wide = false }: { label: string; hint?: string; children: ReactNode; wide?: boolean }) {
  return <label className={wide ? 'ingestion-field wide' : 'ingestion-field'}>
    <span>{label}</span>
    {children}
    {hint ? <small>{hint}</small> : null}
  </label>;
}

function ProjectSelect({ projects, name = 'project_id', optional = false }: { projects: Project[]; name?: string; optional?: boolean }) {
  return <select name={name} defaultValue={optional ? '' : String(projects[0]?.id ?? '')} required={!optional}>
    {optional ? <option value="">Portfolio scope</option> : null}
    {projects.map(project => <option value={project.id} key={project.id}>{project.code} · {project.name}</option>)}
  </select>;
}

function ChannelForm({ channel, projects }: { channel: ChannelId; projects: Project[] }) {
  const t = useTranslations('DataIngestion');
  if (channel === 'event_work_order') return <>
    <FormField label={t('fields.content')} hint={t('fields.contentHint')} wide>
      <textarea name="text" rows={7} required defaultValue="Malaysia site inspection identified an access-control issue requiring engineering and HSE review within 24 hours." />
    </FormField>
    <FormField label={t('fields.classification')}>
      <select name="classification" defaultValue="internal"><option value="public">Public</option><option value="internal">Internal</option><option value="restricted">Restricted</option></select>
    </FormField>
    <FormField label={t('fields.modelRoute')}>
      <select name="model_route" defaultValue="auto"><option value="auto">Auto</option><option value="local">Local</option><option value="openai">OpenAI</option></select>
    </FormField>
  </>;

  if (channel === 'document_correspondence') return <>
    <FormField label={t('fields.document')} hint={t('fields.documentHint')} wide>
      <input name="file" type="file" accept=".pdf,.docx,.txt,application/pdf,text/plain" required />
    </FormField>
    <FormField label={t('fields.classification')}>
      <select name="classification" defaultValue="internal"><option value="public">Public</option><option value="internal">Internal</option><option value="restricted">Restricted</option></select>
    </FormField>
  </>;

  if (channel === 'project_master') return <>
    <FormField label={t('fields.projectCode')}><input name="code" placeholder="SG-RAIL-D" pattern="[A-Za-z0-9-]+" required /></FormField>
    <FormField label={t('fields.projectName')}><input name="name" placeholder="Singapore Rail Programme D" required /></FormField>
    <FormField label={t('fields.countryCode')}><input name="country_code" placeholder="SG" minLength={2} maxLength={3} required /></FormField>
    <FormField label={t('fields.countryName')}><input name="country_name" placeholder="Singapore" /></FormField>
    <FormField label={t('fields.domain')}><input name="domain" placeholder="Rail" required /></FormField>
    <FormField label={t('fields.region')}><input name="region" defaultValue="APAC" required /></FormField>
    <FormField label={t('fields.languages')} hint={t('fields.languagesHint')} wide><input name="languages" defaultValue="English, 中文" required /></FormField>
  </>;

  if (channel === 'enterprise_connector') return <>
    <FormField label={t('fields.connectorType')}>
      <select name="connector_type" defaultValue="primavera_p6"><option value="primavera_p6">Primavera P6</option><option value="autodesk_acc">Autodesk ACC</option><option value="sharepoint">SharePoint</option><option value="sap">SAP / Oracle</option><option value="arcgis">ArcGIS / GeoServer</option><option value="mqtt">MQTT / BMS / SCADA</option></select>
    </FormField>
    <FormField label={t('fields.connectorName')}><input name="name" defaultValue="Project system adapter" required /></FormField>
    <FormField label={t('fields.project')}><ProjectSelect projects={projects} optional /></FormField>
    <FormField label={t('fields.endpointAlias')} hint={t('fields.secretHint')}><input name="endpoint_alias" defaultValue="PRODUCTION_ALIAS" required /></FormField>
  </>;

  if (channel === 'twin_model') return <>
    <FormField label={t('fields.project')}><ProjectSelect projects={projects} /></FormField>
    <FormField label={t('fields.sourceType')}><select name="source_type" defaultValue="IFC"><option>IFC</option><option>GLTF</option><option value="3D_TILES">3D Tiles</option><option>GEOJSON</option><option>WMS</option><option>IOT</option></select></FormField>
    <FormField label={t('fields.sourceName')}><input name="name" defaultValue="Federated delivery model" required /></FormField>
    <FormField label={t('fields.version')}><input name="version" defaultValue="REV-A" required /></FormField>
    <FormField label={t('fields.uri')} hint={t('fields.uriHint')} wide><input name="uri" defaultValue="s3://models/project/model.ifc" required /></FormField>
    <FormField label={t('fields.crs')}><input name="crs" defaultValue="EPSG:4326" /></FormField>
  </>;

  return <>
    <FormField label={t('fields.project')}><ProjectSelect projects={projects} /></FormField>
    <FormField label={t('fields.sensorId')} hint={t('fields.sensorHint')}><input name="sensor_id" defaultValue="SNS-VIB-AHU01" required /></FormField>
    <FormField label={t('fields.value')}><input name="value" type="number" step="any" defaultValue="5.5" required /></FormField>
    <FormField label={t('fields.quality')}><select name="quality" defaultValue="GOOD"><option>GOOD</option><option>SUSPECT</option><option>BAD</option></select></FormField>
  </>;
}

function toNumber(value: FormDataEntryValue | null): number {
  return Number(String(value ?? '0'));
}

function buildRequest(channel: ChannelId, data: FormData, locale: string): { url: string; init: RequestInit } {
  const json = (body: object): RequestInit => ({ method: 'POST', headers: { 'content-type': 'application/json', 'accept-language': locale }, body: JSON.stringify(body) });
  if (channel === 'event_work_order') return {
    url: `/backend/intake/text?lang=${locale}`,
    init: json({ text: String(data.get('text')), model_route: String(data.get('model_route')), data_classification: String(data.get('classification')) }),
  };
  if (channel === 'document_correspondence') {
    const body = new FormData();
    const file = data.get('file');
    if (file instanceof File) body.set('file', file);
    return { url: `/backend/intake/document?lang=${locale}&data_classification=${data.get('classification')}`, init: { method: 'POST', headers: { 'accept-language': locale }, body } };
  }
  if (channel === 'project_master') return {
    url: `/backend/ingestion/project-master?lang=${locale}`,
    init: json({ code: String(data.get('code')).toUpperCase(), name: String(data.get('name')), country_code: String(data.get('country_code')).toUpperCase(), country_name: String(data.get('country_name') || ''), domain: String(data.get('domain')), region: String(data.get('region')), languages: String(data.get('languages')).split(',').map(item => item.trim()).filter(Boolean), risk_level: 'MEDIUM' }),
  };
  if (channel === 'enterprise_connector') {
    const projectId = String(data.get('project_id') || '');
    return { url: '/backend/integrations/connectors', init: json({ connector_type: String(data.get('connector_type')), name: String(data.get('name')), project_id: projectId ? Number(projectId) : null, config: { endpoint_alias: String(data.get('endpoint_alias')) } }) };
  }
  if (channel === 'twin_model') return {
    url: '/backend/twin/sources',
    init: json({ project_id: toNumber(data.get('project_id')), source_type: String(data.get('source_type')), name: String(data.get('name')), uri: String(data.get('uri')), version: String(data.get('version')), coordinate_reference_system: String(data.get('crs') || '') || null, metadata: { registered_from: 'data_ingestion_center' } }),
  };
  return {
    url: '/backend/twin/telemetry/ingest',
    init: json({ project_id: toNumber(data.get('project_id')), sensor_id: String(data.get('sensor_id')), value: toNumber(data.get('value')), quality: String(data.get('quality')) }),
  };
}

export function DataIngestionCenter({ projects, catalog, initialSummary }: Props) {
  const t = useTranslations('DataIngestion');
  const locale = useLocale();
  const [selected, setSelected] = useState<ChannelId>('event_work_order');
  const [summary, setSummary] = useState(initialSummary);
  const [receipt, setReceipt] = useState<Receipt | null>(null);
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const channel = catalog.channels.find(item => item.id === selected) ?? catalog.channels[0];

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError('');
    try {
      const request = buildRequest(selected, new FormData(event.currentTarget), locale);
      const response = await fetch(request.url, request.init);
      const body = await response.json();
      if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail ?? body));
      const nextReceipt = body.ingestion_receipt as Receipt | undefined;
      if (!nextReceipt) throw new Error(t('missingReceipt'));
      const summaryResponse = await fetch(`/backend/ingestion/summary?lang=${locale}`, { cache: 'no-store' });
      if (summaryResponse.ok) setSummary(await summaryResponse.json());
      setReceipt(nextReceipt);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t('unknownError'));
    } finally {
      setSubmitting(false);
    }
  }

  return <div className="ingestion-console">
    <section className="ingestion-principle">
      <span>CANONICAL · V1</span><b>{catalog.principle}</b><small>{t('principleDetail')}</small>
    </section>

    <section className="ingestion-metrics" aria-label={t('metricsLabel')}>
      <div><span>{t('metrics.channels')}</span><b>{summary.active_channels}/{summary.channel_count}</b><small>{t('metrics.channelsHint')}</small></div>
      <div><span>{t('metrics.operations')}</span><b>{summary.operations}</b><small>{t('metrics.operationsHint')}</small></div>
      <div><span>{t('metrics.accepted')}</span><b>{summary.records_accepted}</b><small>{t('metrics.acceptedHint')}</small></div>
      <div><span>{t('metrics.rejected')}</span><b className={summary.records_rejected ? 'amber-text' : 'good-text'}>{summary.records_rejected}</b><small>{t('metrics.rejectedHint')}</small></div>
    </section>

    <div className="ingestion-workspace">
      <section className="card ingestion-channel-rail" aria-label={t('channelSelector')}>
        <header><span className="section-kicker">01 · {t('selectChannel')}</span><h3>{t('sixEntrances')}</h3></header>
        <div role="tablist" aria-orientation="vertical">
          {catalog.channels.map(item => <button type="button" role="tab" aria-selected={selected === item.id} className={selected === item.id ? 'active' : ''} key={item.id} onClick={() => { setSelected(item.id); setReceipt(null); setError(''); }}>
            <span>{item.code}</span><i>{item.icon}</i><div><b>{item.name}</b><small>{item.description}</small></div><strong>{summary.by_channel[item.id]?.operations ?? 0}</strong>
          </button>)}
        </div>
      </section>

      <section className="card ingestion-form-panel" role="tabpanel">
        <header>
          <div><span className="section-kicker">02 · {t('configure')}</span><h3>{channel.name}</h3><p>{channel.description}</p></div>
          <span className="ingestion-channel-icon">{channel.icon}</span>
        </header>
        <div className="ingestion-contract">
          <div><span>{t('sourceTypes')}</span><b>{channel.source_types.join(' · ')}</b></div>
          <i>→</i><div><span>{t('domainObjects')}</span><b>{channel.canonical_objects.join(' · ')}</b></div>
        </div>
        <form key={selected} onSubmit={submit}>
          <div className="ingestion-form-grid"><ChannelForm channel={selected} projects={projects} /></div>
          {error ? <p className="ingestion-error" role="alert">{error}</p> : null}
          <footer><small>{channel.event_policy}</small><button className="button" type="submit" disabled={submitting}>{submitting ? t('submitting') : t('submit')}</button></footer>
        </form>
      </section>

      <aside className="card ingestion-receipt-panel">
        <header><span className="section-kicker">03 · {t('receipt')}</span><h3>{t('validationLineage')}</h3></header>
        {receipt ? <div className="ingestion-receipt-live">
          <div className={`receipt-status ${receipt.status === 'OCR_REQUIRED' ? 'pending' : ''}`}><i /><span>{receipt.status}</span><b>{receipt.id}</b></div>
          {receipt.status === 'OCR_REQUIRED' ? <p className="ingestion-notice">{t('ocrPending')}</p> : null}
          <dl>
            <div><dt>{t('receiptFields.target')}</dt><dd>{receipt.target_type}<small>{receipt.target_id}</small></dd></div>
            <div><dt>{t('receiptFields.records')}</dt><dd>{receipt.records_accepted}/{receipt.records_received}<small>{receipt.records_rejected} rejected</small></dd></div>
            <div><dt>{t('receiptFields.mapping')}</dt><dd>{receipt.mapping_version}</dd></div>
            <div><dt>{t('receiptFields.project')}</dt><dd>{receipt.project_id ?? 'PORTFOLIO'}</dd></div>
          </dl>
          <div className="receipt-json"><span>{t('receiptFields.validation')}</span><code>{JSON.stringify(receipt.validation_summary, null, 2)}</code></div>
          <div className="receipt-json"><span>{t('receiptFields.lineage')}</span><code>{JSON.stringify(receipt.lineage, null, 2)}</code></div>
        </div> : <div className="receipt-placeholder"><span>◎</span><b>{t('receiptEmpty')}</b><p>{t('receiptEmptyHint')}</p></div>}
      </aside>
    </div>

    <section className="card ingestion-feed">
      <div className="section-title"><div><span className="section-kicker">{t('recentKicker')}</span><h3>{t('recentTitle')}</h3></div><span>{summary.recent.length} / {summary.operations}</span></div>
      <div className="ingestion-feed-table">
        {summary.recent.map(item => <article key={item.id}>
          <span className="feed-channel">{catalog.channels.find(candidate => candidate.id === item.channel)?.icon ?? 'DATA'}</span>
          <div><b>{catalog.channels.find(candidate => candidate.id === item.channel)?.name ?? item.channel}</b><small>{item.source_type} · {item.target_type} / {item.target_id}</small></div>
          <span className={`badge ${item.records_rejected || item.status === 'OCR_REQUIRED' ? 'medium' : 'ok'}`}>{item.status}</span>
          <time>{new Date(item.created_at).toLocaleString(locale)}</time>
        </article>)}
      </div>
    </section>
  </div>;
}
