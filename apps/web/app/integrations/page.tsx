import { getTranslations } from 'next-intl/server';
import { api } from '@/lib/api';

type Catalog={type:string;name:string;plane:string;objects:string[]};
type Connector={id:string;connector_type:string;name:string;status:string;project_id:number|null;last_sync_at:string|null};
type TwinSource={id:string;source_type:string;name:string;version:string;status:string;project_id:number;coordinate_reference_system:string|null};

export default async function IntegrationsPage(){
  const t=await getTranslations('Integrations');
  const [catalog,connectors,sources]=await Promise.all([
    api<Catalog[]>('/integrations/catalog'),api<Connector[]>('/integrations/connectors'),api<TwinSource[]>('/twin/sources')
  ]);
  return <><div className="header-row"><div><div className="eyebrow">{t('eyebrow')}</div><h2 className="page-title">{t('title')}</h2><p className="page-subtitle">{t('subtitle')}</p></div><span className="badge info">6 DATA PLANES</span></div>
  <section className="section"><div className="outside-title"><div><span className="section-kicker">CATALOG</span><h3>{t('catalog')}</h3></div><span>{catalog.length}</span></div><div className="connector-grid">{catalog.map(item=><div className="card connector-card" key={item.type}><span>{item.plane}</span><h3>{item.name}</h3><p>{item.objects.join(' · ')}</p><div className="connector-contract">external_id · object_type · updated_at · payload</div></div>)}</div></section>
  <div className="grid-2 section"><section className="card"><div className="section-title"><h3>{t('configured')}</h3><span>{connectors.length}</span></div>{connectors.length?<div className="integration-list">{connectors.map(row=><div key={row.id}><span className="mono">{row.connector_type}</span><b>{row.name}</b><small>{row.status} · {row.last_sync_at||'NEVER SYNCED'}</small></div>)}</div>:<div className="empty-state">{t('empty')}</div>}</section><section className="card"><div className="section-title"><h3>{t('sources')}</h3><span>{sources.length}</span></div>{sources.length?<div className="integration-list">{sources.map(row=><div key={row.id}><span className="mono">{row.source_type}</span><b>{row.name}</b><small>{row.version} · {row.status} · {row.coordinate_reference_system||'SOURCE CRS'}</small></div>)}</div>:<div className="empty-state">IFC · 3D Tiles · GeoJSON · IoT</div>}</section></div>
  <p className="integration-policy">✓ {t('secretPolicy')}</p></>;
}
