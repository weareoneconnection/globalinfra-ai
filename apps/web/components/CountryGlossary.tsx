'use client';

import { useEffect, useMemo, useState } from 'react';

type Term={id:string;domain:string;en:string;zh:string;local:string;local_lang:string;local_basis:string;review_status:string};
type GlossaryResponse={country:string;total:number;terms:Term[];domains:string[];local_language:string|null;review_notice:string};
export type GlossaryLabels={glossaryFull:string;glossarySearch:string;glossaryAll:string;glossaryAttested:string;glossaryCompiled:string;glossaryReview:string;glossaryEmpty:string;glossaryShown:string;glossaryNotice:string;glossaryDomains:Record<string,string>};

const ATTESTED='ATTESTED_IN:';
const LANGUAGE:Record<string,{short:string;name:string}>={ms:{short:'BM',name:'BAHASA MALAYSIA'},id:{short:'BI',name:'BAHASA INDONESIA'},ar:{short:'AR',name:'العربية'}};
const RTL=new Set(['ar']);

export function CountryGlossary({code,labels}:{code:string;labels:GlossaryLabels}){
  const [data,setData]=useState<GlossaryResponse|null>(null);
  const [query,setQuery]=useState('');
  const [domain,setDomain]=useState('');
  const [attestedOnly,setAttestedOnly]=useState(false);
  useEffect(()=>{
    const controller=new AbortController();
    setData(null);setQuery('');setDomain('');setAttestedOnly(false);
    fetch(`/backend/country-packs/${code}/glossary?limit=1000`,{signal:controller.signal})
      .then(response=>response.ok?response.json():null)
      .then(body=>setData(body))
      .catch(()=>{});
    return()=>controller.abort();
  },[code]);
  const terms=useMemo(()=>data?.terms||[],[data]);
  const attested=terms.filter(term=>term.local_basis.startsWith(ATTESTED)).length;
  const visible=useMemo(()=>{
    const needle=query.trim().toLowerCase();
    return terms.filter(term=>(!domain||term.domain===domain)&&(!attestedOnly||term.local_basis.startsWith(ATTESTED))&&(!needle||[term.en,term.zh,term.local].some(value=>value.toLowerCase().includes(needle))));
  },[terms,query,domain,attestedOnly]);
  if(!data||!terms.length)return null;
  const domainLabel=(value:string)=>labels.glossaryDomains[value]||value;
  const language=LANGUAGE[data.local_language||'']||{short:(data.local_language||'').toUpperCase(),name:(data.local_language||'').toUpperCase()};
  return <section className="card country-term-library" aria-label={labels.glossaryFull}>
    <div className="section-title"><div><span className="section-kicker">EN · 中文 · {language.name}</span><h3>{labels.glossaryFull}</h3></div>
      <div className="term-stats"><b>{terms.length}</b><span>{labels.glossaryShown.replace('{shown}',String(visible.length))}</span><button type="button" className={attestedOnly?'active':''} aria-pressed={attestedOnly} onClick={()=>setAttestedOnly(value=>!value)}><i/>{attested} {labels.glossaryAttested}</button></div>
    </div>
    <div className="term-toolbar">
      <input type="search" value={query} onChange={event=>setQuery(event.target.value)} placeholder={labels.glossarySearch} aria-label={labels.glossarySearch}/>
      <div role="group" aria-label="domain">
        <button type="button" className={!domain?'active':''} onClick={()=>setDomain('')}>{labels.glossaryAll}</button>
        {data.domains.map(value=><button type="button" key={value} className={domain===value?'active':''} onClick={()=>setDomain(value)}>{domainLabel(value)}</button>)}
      </div>
    </div>
    <div className="term-table" role="table">
      <div className="term-row head" role="row"><span role="columnheader">EN</span><span role="columnheader">中文</span><span role="columnheader">{language.short}</span><span role="columnheader">{labels.glossaryReview}</span></div>
      {visible.length?visible.map(term=>{
        const source=term.local_basis.startsWith(ATTESTED)?term.local_basis.slice(ATTESTED.length):'';
        return <div className="term-row" role="row" key={term.id}>
          <b role="cell">{term.en}<small>{domainLabel(term.domain)}</small></b>
          <span role="cell">{term.zh}</span>
          <span role="cell" lang={term.local_lang} dir={RTL.has(term.local_lang)?'rtl':undefined}>{term.local}</span>
          <em role="cell" className={source?'attested':'compiled'} title={source||labels.glossaryCompiled}>{source?`✓ ${source}`:labels.glossaryCompiled}</em>
        </div>;
      }):<p className="term-empty">{labels.glossaryEmpty}</p>}
    </div>
    <footer className="term-notice">⚠ {labels.glossaryNotice}</footer>
  </section>;
}
