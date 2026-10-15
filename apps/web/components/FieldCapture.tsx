'use client';

import { FormEvent, useCallback, useEffect, useRef, useState } from 'react';
import { FIELD_SYNCED_EVENT } from './FieldReports';

type Project = { id:number; code:string; name:string; latitude?:number; longitude?:number };
type Labels = Record<string,string>;
type TwinObject = { id:string; name:string; object_type:string };
type Attachment = { name:string; media_type:string; size:number; sha256:string; storage_ref:string|null; blob?:Blob };
type QueuedObservation = {
  client_id:string; project_id:number; twin_id:string|null; event_type:string;
  severity:string; description:string; location:Record<string,number>;
  attachments:Attachment[]; captured_at:string;
};

const DB_NAME = 'globalinfra-field';
const STORE = 'observations';
const EVENT_TYPES = ['inspection','ncr','rfi','hse','progress','delivery','commissioning','maintenance'];
const NEAREST_PROJECT_KM = 150;

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

async function digest(file:Blob) {
  const hash=await crypto.subtle.digest('SHA-256',await file.arrayBuffer());
  return Array.from(new Uint8Array(hash)).map(x=>x.toString(16).padStart(2,'0')).join('');
}

function distanceKm(a:{lat:number;lng:number}, b:{lat:number;lng:number}) {
  const rad=(d:number)=>d*Math.PI/180; const dLat=rad(b.lat-a.lat); const dLng=rad(b.lng-a.lng);
  const h=Math.sin(dLat/2)**2+Math.cos(rad(a.lat))*Math.cos(rad(b.lat))*Math.sin(dLng/2)**2;
  return 6371*2*Math.asin(Math.sqrt(h));
}

/** Upload any original files still held in the queue; the stored copy is kept until the server confirms it. */
async function uploadPending(observation: QueuedObservation): Promise<QueuedObservation> {
  let changed=false;
  const attachments: Attachment[] = [];
  for (const item of observation.attachments) {
    if (item.storage_ref || !item.blob) { attachments.push(item); continue; }
    const form=new FormData(); form.append('file', item.blob, item.name);
    const response=await fetch('/backend/field/media',{method:'POST',body:form});
    if(!response.ok) throw new Error(`media ${response.status}`);
    const body=await response.json();
    attachments.push({name:item.name,media_type:body.media_type,size:body.size,sha256:body.sha256,storage_ref:body.storage_ref});
    changed=true;
  }
  const next={...observation,attachments};
  if(changed) await putQueued(next);
  return next;
}

type BarcodeDetectorLike = { detect:(source:CanvasImageSource)=>Promise<{rawValue:string}[]> };

export function FieldCapture({projects,labels,eventLabels,severityLabels}:{projects:Project[];labels:Labels;eventLabels:Labels;severityLabels:Labels}) {
  const [projectId,setProjectId]=useState(projects[0]?.id||0);
  const [twinId,setTwinId]=useState(''); const [twinObjects,setTwinObjects]=useState<TwinObject[]>([]);
  const [eventType,setEventType]=useState('inspection');
  const [severity,setSeverity]=useState('MEDIUM'); const [description,setDescription]=useState('');
  const [location,setLocation]=useState<Record<string,number>>({}); const [files,setFiles]=useState<File[]>([]);
  const [fileInputKey,setFileInputKey]=useState(0); // remounts the native picker so it forgets saved files
  const [pending,setPending]=useState(0); const [status,setStatus]=useState(''); const [busy,setBusy]=useState(false);
  // Read browser-only capabilities after mount; navigator is not available during server render.
  const [online,setOnline]=useState(false); const [canScan,setCanScan]=useState(false); const [scanning,setScanning]=useState(false);
  const videoRef=useRef<HTMLVideoElement>(null);

  useEffect(()=>{
    let alive=true; setTwinObjects([]);
    fetch(`/backend/twin/scene?project_id=${projectId}`).then(r=>r.ok?r.json():{objects:[]}).then(body=>{
      if(alive) setTwinObjects((body.objects||[]).filter((o:TwinObject)=>o.object_type!=='PROJECT'));
    }).catch(()=>undefined);
    return()=>{alive=false};
  },[projectId]);

  const refreshPending=useCallback(async()=>setPending((await readQueued()).length),[]);
  const sync=useCallback(async()=>{
    const queued=await readQueued(); if(!queued.length) return;
    setBusy(true); setStatus(labels.syncing);
    try {
      const ready:QueuedObservation[]=[];
      for(const observation of queued) ready.push(await uploadPending(observation));
      const observations=ready.map(o=>({...o,attachments:o.attachments.map(({blob,...rest})=>rest)}));
      const response=await fetch('/backend/field/sync',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({observations})});
      if(!response.ok) throw new Error();
      const body=await response.json(); await removeQueued(body.results.map((x:{client_id:string})=>x.client_id));
      await refreshPending(); setStatus(labels.synced.replace('{count}',String(body.accepted)));
      window.dispatchEvent(new Event(FIELD_SYNCED_EVENT));
    } catch { setStatus(labels.offlineQueued); } finally { setBusy(false); }
  },[labels,refreshPending]);

  useEffect(()=>{
    setOnline(navigator.onLine); setCanScan('BarcodeDetector' in window && !!navigator.mediaDevices?.getUserMedia);
    const offline=()=>setOnline(false);
    refreshPending(); const goOnline=()=>{setOnline(true); sync();};
    const message=(event:MessageEvent)=>{if(event.data?.type==='GLOBALINFRA_FIELD_SYNC')sync()};
    window.addEventListener('online',goOnline); window.addEventListener('offline',offline); navigator.serviceWorker?.addEventListener('message',message);
    return()=>{window.removeEventListener('online',goOnline);window.removeEventListener('offline',offline);navigator.serviceWorker?.removeEventListener('message',message)};
  },[refreshPending,sync]);

  function locate(){
    if(!navigator.geolocation){setStatus(labels.locationUnavailable);return}
    navigator.geolocation.getCurrentPosition(
      p=>{
        const here={lat:p.coords.latitude,lng:p.coords.longitude};
        setLocation({...here,accuracy_m:p.coords.accuracy});
        const nearest=projects.filter(x=>x.latitude!=null&&x.longitude!=null)
          .map(x=>({project:x,km:distanceKm(here,{lat:x.latitude as number,lng:x.longitude as number})}))
          .sort((a,b)=>a.km-b.km)[0];
        if(nearest&&nearest.km<=NEAREST_PROJECT_KM&&nearest.project.id!==projectId){
          setProjectId(nearest.project.id);
          setStatus(labels.nearestProject.replace('{project}',nearest.project.code).replace('{km}',String(Math.round(nearest.km))));
        } else setStatus(labels.locationCaptured);
      },
      ()=>setStatus(labels.locationUnavailable),{enableHighAccuracy:true,timeout:12000}
    );
  }

  async function scan(){
    const Detector=(window as unknown as {BarcodeDetector:new(o:{formats:string[]})=>BarcodeDetectorLike}).BarcodeDetector;
    let stream:MediaStream|null=null;
    try {
      setScanning(true);
      stream=await navigator.mediaDevices.getUserMedia({video:{facingMode:'environment'}});
      const video=videoRef.current; if(!video) return;
      video.srcObject=stream; await video.play();
      const detector=new Detector({formats:['qr_code','code_128','data_matrix']});
      const deadline=Date.now()+20000;
      while(Date.now()<deadline){
        const codes=await detector.detect(video);
        const value=codes[0]?.rawValue?.trim();
        if(value){
          const match=twinObjects.find(o=>value.toUpperCase().includes(o.id.toUpperCase()));
          if(match){setTwinId(match.id); setStatus(labels.scanMatched.replace('{name}',match.name));}
          else setStatus(labels.scanUnknown.replace('{code}',value.slice(0,60)));
          return;
        }
        await new Promise(r=>setTimeout(r,300));
      }
      setStatus(labels.scanTimeout);
    } catch { setStatus(labels.scanUnavailable); }
    finally { stream?.getTracks().forEach(t=>t.stop()); setScanning(false); }
  }

  async function submit(event:FormEvent){
    event.preventDefault(); setBusy(true);
    const attachments:Attachment[]=await Promise.all(files.map(async file=>({
      name:file.name,media_type:file.type||'application/octet-stream',size:file.size,sha256:await digest(file),storage_ref:null,blob:file,
    })));
    const observation:QueuedObservation={
      client_id:`web-${crypto.randomUUID()}`,project_id:projectId,twin_id:twinId||null,
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
    setDescription(''); setFiles([]); setFileInputKey(k=>k+1); setTwinId(''); await refreshPending(); setStatus(labels.savedOffline); setBusy(false);
    if(navigator.onLine) await sync();
  }

  return <div className="field-layout">
    <form className="card card-pad field-form" onSubmit={submit}>
      <div className="section-kicker">{labels.captureKicker}</div><h3>{labels.captureTitle}</h3>
      <label>{labels.project}<select value={projectId} onChange={e=>{setProjectId(Number(e.target.value)); setTwinId('');}}>{projects.map(p=><option value={p.id} key={p.id}>{p.code} · {p.name}</option>)}</select></label>
      <div className="field-form-grid"><label>{labels.eventType}<select value={eventType} onChange={e=>setEventType(e.target.value)}>{EVENT_TYPES.map(type=><option value={type} key={type}>{eventLabels[type]??type}</option>)}</select></label><label>{labels.severity}<select value={severity} onChange={e=>setSeverity(e.target.value)}>{['LOW','MEDIUM','HIGH','CRITICAL'].map(level=><option value={level} key={level}>{severityLabels[level]??level}</option>)}</select></label></div>
      <label>{labels.twinId}
        <div className="field-twin-row">
          <select value={twinId} onChange={e=>setTwinId(e.target.value)}>
            <option value="">{labels.twinNone}</option>
            {twinObjects.map(o=><option value={o.id} key={o.id}>{o.name} · {o.id}</option>)}
          </select>
          {canScan&&<button type="button" className="button secondary" onClick={scan} disabled={scanning||!twinObjects.length}>{scanning?labels.scanning:labels.scan}</button>}
        </div>
      </label>
      {scanning&&<video ref={videoRef} className="field-scan-video" muted playsInline/>}
      <label>{labels.description}<textarea required minLength={4} value={description} onChange={e=>setDescription(e.target.value)} placeholder={labels.descriptionHint}/></label>
      <label>{labels.media}<input key={fileInputKey} type="file" accept="image/*,video/*,audio/*" capture="environment" multiple onChange={e=>setFiles(Array.from(e.target.files||[]))}/><small>{files.length?labels.files.replace('{count}',String(files.length)):labels.mediaHint}</small></label>
      <div className="field-location"><button className="button secondary" type="button" onClick={locate}>{labels.captureLocation}</button><span>{location.lat?`${location.lat.toFixed(5)}, ${location.lng.toFixed(5)} · ±${Math.round(location.accuracy_m)}m`:labels.noLocation}</span></div>
      <button className="button" disabled={busy||!description.trim()||!projectId}>{busy?labels.working:labels.save}</button>
      {status&&<p className="field-status" role="status">{status}</p>}
    </form>
    <aside className="card card-pad field-queue"><div className="section-kicker">{labels.queueKicker}</div><strong>{pending}</strong><h3>{labels.queueTitle}</h3><p>{labels.queueHint}</p><button className="button secondary" onClick={sync} disabled={busy||!pending}>{labels.syncNow}</button><div className={`connectivity ${online?'online':''}`}><i/>{labels.connectivity}</div></aside>
  </div>;
}
