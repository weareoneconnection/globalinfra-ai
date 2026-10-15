'use client';

import { FormEvent, useCallback, useEffect, useState } from 'react';
import { FIELD_SYNCED_EVENT } from './FieldReports';

type Project = { id:number; code:string; name:string };
type Labels = Record<string,string>;
type QueuedObservation = {
  client_id:string; project_id:number; twin_id:string|null; event_type:string;
  severity:string; description:string; location:Record<string,number>;
  attachments:{name:string;media_type:string;size:number;sha256:string;storage_ref:null}[];
  captured_at:string;
};

const DB_NAME = 'globalinfra-field';
const STORE = 'observations';

function database(): Promise<IDBDatabase> {
  return new Promise((resolve,reject) => {
    const request = indexedDB.open(DB_NAME,1);
    request.onupgradeneeded = () => request.result.createObjectStore(STORE,{keyPath:'client_id'});
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function putQueued(value: QueuedObservation) {
  const db = await database();
  await new Promise<void>((resolve,reject) => {
    const tx = db.transaction(STORE,'readwrite');
    tx.objectStore(STORE).put(value); tx.oncomplete=()=>resolve(); tx.onerror=()=>reject(tx.error);
  });
  db.close();
}

async function readQueued(): Promise<QueuedObservation[]> {
  const db = await database();
  const values = await new Promise<QueuedObservation[]>((resolve,reject) => {
    const request = db.transaction(STORE).objectStore(STORE).getAll();
    request.onsuccess=()=>resolve(request.result); request.onerror=()=>reject(request.error);
  });
  db.close(); return values;
}

async function removeQueued(ids:string[]) {
  const db = await database();
  await new Promise<void>((resolve,reject) => {
    const tx=db.transaction(STORE,'readwrite'); ids.forEach(id=>tx.objectStore(STORE).delete(id));
    tx.oncomplete=()=>resolve(); tx.onerror=()=>reject(tx.error);
  });
  db.close();
}

async function digest(file:File) {
  const hash=await crypto.subtle.digest('SHA-256',await file.arrayBuffer());
  return Array.from(new Uint8Array(hash)).map(x=>x.toString(16).padStart(2,'0')).join('');
}

const EVENT_TYPES=['inspection','ncr','rfi','hse','progress','delivery','commissioning','maintenance'];

export function FieldCapture({projects,labels,eventLabels,severityLabels}:{projects:Project[];labels:Labels;eventLabels:Labels;severityLabels:Labels}) {
  const [projectId,setProjectId]=useState(projects[0]?.id||0);
  const [twinId,setTwinId]=useState(''); const [eventType,setEventType]=useState('inspection');
  const [severity,setSeverity]=useState('MEDIUM'); const [description,setDescription]=useState('');
  const [location,setLocation]=useState<Record<string,number>>({}); const [files,setFiles]=useState<File[]>([]);
  const [pending,setPending]=useState(0); const [status,setStatus]=useState(''); const [busy,setBusy]=useState(false);
  // Read connectivity after mount; navigator is not available during server render.
  const [online,setOnline]=useState(false);

  const refreshPending=useCallback(async()=>setPending((await readQueued()).length),[]);
  const sync=useCallback(async()=>{
    const observations=await readQueued(); if(!observations.length) return;
    setBusy(true); setStatus(labels.syncing);
    try {
      const response=await fetch('/backend/field/sync',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({observations})});
      if(!response.ok) throw new Error();
      const body=await response.json(); await removeQueued(body.results.map((x:{client_id:string})=>x.client_id));
      await refreshPending(); setStatus(labels.synced.replace('{count}',String(body.accepted)));
      window.dispatchEvent(new Event(FIELD_SYNCED_EVENT));
    } catch { setStatus(labels.offlineQueued); } finally { setBusy(false); }
  },[labels,refreshPending]);

  useEffect(()=>{
    setOnline(navigator.onLine); const offline=()=>setOnline(false);
    refreshPending(); const online=()=>{setOnline(true); sync();}; const message=(event:MessageEvent)=>{if(event.data?.type==='GLOBALINFRA_FIELD_SYNC')sync()};
    window.addEventListener('online',online); window.addEventListener('offline',offline); navigator.serviceWorker?.addEventListener('message',message);
    return()=>{window.removeEventListener('online',online);window.removeEventListener('offline',offline);navigator.serviceWorker?.removeEventListener('message',message)};
  },[refreshPending,sync]);

  function locate(){
    if(!navigator.geolocation){setStatus(labels.locationUnavailable);return}
    navigator.geolocation.getCurrentPosition(
      p=>{setLocation({lat:p.coords.latitude,lng:p.coords.longitude,accuracy_m:p.coords.accuracy});setStatus(labels.locationCaptured)},
      ()=>setStatus(labels.locationUnavailable),{enableHighAccuracy:true,timeout:12000}
    );
  }

  async function submit(event:FormEvent){
    event.preventDefault(); setBusy(true);
    const attachments=await Promise.all(files.map(async file=>({name:file.name,media_type:file.type||'application/octet-stream',size:file.size,sha256:await digest(file),storage_ref:null})));
    const observation:QueuedObservation={
      client_id:`web-${crypto.randomUUID()}`,project_id:projectId,twin_id:twinId.trim()||null,
      event_type:eventType,severity,description:description.trim(),location,attachments,captured_at:new Date().toISOString()
    };
    await putQueued(observation);
    // serviceWorker.ready never settles when no worker is registered (blocked
    // registration, private mode, development), so never wait on it forever.
    if('serviceWorker' in navigator){
      const registration=await Promise.race([navigator.serviceWorker.ready,new Promise<null>(resolve=>setTimeout(()=>resolve(null),1000))]);
      const syncManager=(registration as (ServiceWorkerRegistration&{sync?:{register:(tag:string)=>Promise<void>}})|null)?.sync;
      await syncManager?.register('globalinfra-field-sync').catch(()=>undefined);
    }
    setDescription(''); setFiles([]); await refreshPending(); setStatus(labels.savedOffline); setBusy(false);
    if(navigator.onLine) await sync();
  }

  return <div className="field-layout">
    <form className="card card-pad field-form" onSubmit={submit}>
      <div className="section-kicker">{labels.captureKicker}</div><h3>{labels.captureTitle}</h3>
      <label>{labels.project}<select value={projectId} onChange={e=>setProjectId(Number(e.target.value))}>{projects.map(p=><option value={p.id} key={p.id}>{p.code} · {p.name}</option>)}</select></label>
      <div className="field-form-grid"><label>{labels.eventType}<select value={eventType} onChange={e=>setEventType(e.target.value)}>{EVENT_TYPES.map(type=><option value={type} key={type}>{eventLabels[type]??type}</option>)}</select></label><label>{labels.severity}<select value={severity} onChange={e=>setSeverity(e.target.value)}>{['LOW','MEDIUM','HIGH','CRITICAL'].map(level=><option value={level} key={level}>{severityLabels[level]??level}</option>)}</select></label></div>
      <label>{labels.twinId}<input value={twinId} onChange={e=>setTwinId(e.target.value)} placeholder="TWIN-MYRAIL-V12-P47"/></label>
      <label>{labels.description}<textarea required minLength={4} value={description} onChange={e=>setDescription(e.target.value)} placeholder={labels.descriptionHint}/></label>
      <label>{labels.media}<input type="file" accept="image/*,video/*,audio/*" capture="environment" multiple onChange={e=>setFiles(Array.from(e.target.files||[]))}/><small>{files.length?labels.files.replace('{count}',String(files.length)):labels.mediaHint}</small></label>
      <div className="field-location"><button className="button secondary" type="button" onClick={locate}>{labels.captureLocation}</button><span>{location.lat?`${location.lat.toFixed(5)}, ${location.lng.toFixed(5)} · ±${Math.round(location.accuracy_m)}m`:labels.noLocation}</span></div>
      <button className="button" disabled={busy||!description.trim()||!projectId}>{busy?labels.working:labels.save}</button>
      {status&&<p className="field-status" role="status">{status}</p>}
    </form>
    <aside className="card card-pad field-queue"><div className="section-kicker">{labels.queueKicker}</div><strong>{pending}</strong><h3>{labels.queueTitle}</h3><p>{labels.queueHint}</p><button className="button secondary" onClick={sync} disabled={busy||!pending}>{labels.syncNow}</button><div className={`connectivity ${online?'online':''}`}><i/>{labels.connectivity}</div></aside>
  </div>;
}
