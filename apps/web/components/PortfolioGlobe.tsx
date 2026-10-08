'use client';

import Link from 'next/link';
import { useState, type CSSProperties } from 'react';

export type GlobeProject = {
  id:number;
  code:string;
  name:string;
  country_code:string;
  country_name:string;
  domain:string;
  phase:string;
  status:string;
  risk_level:string;
  progress:number;
  schedule_variance:number;
  latitude:number;
  longitude:number;
  location_name:string;
};

type GlobeLabels = {
  live:string;
  projectsOnline:string;
  progress:string;
  schedule:string;
  phase:string;
  openProject:string;
};

function projectCoordinates(project:GlobeProject) {
  const latitude=project.latitude*Math.PI/180;
  const deltaLongitude=(project.longitude-85)*Math.PI/180;
  const centerLatitude=12*Math.PI/180;
  const radius=292;
  return {
    x: 360+radius*Math.cos(latitude)*Math.sin(deltaLongitude),
    y: 360-radius*(Math.cos(centerLatitude)*Math.sin(latitude)-Math.sin(centerLatitude)*Math.cos(latitude)*Math.cos(deltaLongitude)),
  };
}

function pointStyle(project:GlobeProject):CSSProperties {
  const {x,y}=projectCoordinates(project);
  return {
    '--point-x': `${(x / 720) * 100}%`,
    '--point-y': `${(y / 720) * 100}%`,
  } as CSSProperties;
}

function routePath(from:GlobeProject,to:GlobeProject) {
  const a=projectCoordinates(from);
  const b=projectCoordinates(to);
  const lift=Math.max(26,Math.abs(b.x-a.x)*.22);
  return `M ${a.x} ${a.y} Q ${(a.x+b.x)/2} ${Math.min(a.y,b.y)-lift} ${b.x} ${b.y}`;
}

export function PortfolioGlobe({projects,labels}:{projects:GlobeProject[];labels:GlobeLabels}) {
  const [selectedId,setSelectedId]=useState(projects[0]?.id ?? 0);
  const selected=projects.find(project=>project.id===selectedId) ?? projects[0];

  return <div className="portfolio-map-layout">
    <div className="globe-stage" aria-label={labels.projectsOnline}>
      <div className="globe-stars" aria-hidden="true"/>
      <div className="globe-halo halo-a" aria-hidden="true"/>
      <div className="globe-halo halo-b" aria-hidden="true"/>
      <div className="globe-sphere">
        <svg className="globe-world" viewBox="0 0 720 720" role="img" aria-label={labels.projectsOnline}>
          <defs>
            <clipPath id="earthClip"><circle cx="360" cy="360" r="304"/></clipPath>
            <radialGradient id="oceanDepth" cx="31%" cy="25%" r="82%">
              <stop offset="0" stopColor="#146378"/><stop offset=".34" stopColor="#0a394b"/>
              <stop offset=".72" stopColor="#061d2a"/><stop offset="1" stopColor="#020a11"/>
            </radialGradient>
            <linearGradient id="landLight" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0" stopColor="#52b9aa"/><stop offset=".48" stopColor="#247c78"/><stop offset="1" stopColor="#123d47"/>
            </linearGradient>
            <linearGradient id="nightFall" x1="0" x2="1">
              <stop offset=".36" stopColor="#001019" stopOpacity="0"/><stop offset=".72" stopColor="#00070d" stopOpacity=".48"/><stop offset="1" stopColor="#000208" stopOpacity=".92"/>
            </linearGradient>
            <radialGradient id="specular" cx="28%" cy="22%" r="54%">
              <stop offset="0" stopColor="#d8fbff" stopOpacity=".22"/><stop offset=".38" stopColor="#7adceb" stopOpacity=".05"/><stop offset="1" stopColor="#071823" stopOpacity="0"/>
            </radialGradient>
            <filter id="earthTexture" x="-10%" y="-10%" width="120%" height="120%">
              <feTurbulence type="fractalNoise" baseFrequency=".018 .08" numOctaves="3" seed="21"/>
              <feColorMatrix type="saturate" values="0"/><feComponentTransfer><feFuncA type="table" tableValues="0 .13"/></feComponentTransfer>
            </filter>
            <filter id="softGlow" x="-80%" y="-80%" width="260%" height="260%">
              <feGaussianBlur stdDeviation="5" result="blur"/><feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
            </filter>
          </defs>
          <circle className="globe-depth-shadow" cx="360" cy="370" r="307"/>
          <g clipPath="url(#earthClip)">
            <rect width="720" height="720" fill="url(#oceanDepth)"/>
            <g className="globe-grid">
              <path d="M88 235Q360 326 632 235M65 300Q360 366 655 300M56 360H664M65 420Q360 354 655 420M88 485Q360 394 632 485"/>
              <path d="M360 56C292 170 292 550 360 664M360 56C428 170 428 550 360 664M360 56C220 170 220 550 360 664M360 56C500 170 500 550 360 664"/>
            </g>
            <g className="landmasses">
              <path className="continent" d="M139 226l26-45 55-22 38-29 58 8 33-31 65 12 39 32 56 8 33 31 60 16 52 45-14 43-50 6-25 33-45-8-27 39-44-14-31 33-38-28-33 14-29-38-40-17-33-35-35 3-20-33-21-20z"/>
              <path className="continent continent-secondary" d="M150 225l-34 37-18 48 12 37 45 8 31-22 29-53-9-42-30-20z"/>
              <path className="continent" d="M196 279l44-7 60 6 43 30 22 48-14 38-32 24-15 56-39 14-19-51-9-58-37-38z"/>
              <path className="continent" d="M238 277l45-5 39 22-4 41-33 13-25-24z"/>
              <path className="continent" d="M379 343l35 9 35 40-4 57-27 41-14 51-33-8-15-55-25-40 11-38z"/>
              <path className="continent" d="M505 481l42-25 58 9 40 45-11 50-50 35-64-7-31-43z"/>
              <path className="islands" d="M463 395l15 13-7 25-18-11zm38 34 11 8-4 19-13-9zm52-12 12 16-8 22-13-14zm-26 60 15 10-8 15-14-8zm-84-164 9 13-8 14-10-12z"/>
            </g>
            <rect className="earth-texture" width="720" height="720" filter="url(#earthTexture)"/>
            <rect width="720" height="720" fill="url(#nightFall)"/>
            <circle cx="360" cy="360" r="304" fill="url(#specular)"/>
            <g className="route-network" filter="url(#softGlow)">
              {selected && projects.filter(project=>project.id!==selected.id).map(project=><path className="globe-route" d={routePath(selected,project)} key={`route-${project.id}`}/>)}
            </g>
            <g className="city-lights" aria-hidden="true">
              <circle cx="278" cy="275" r="2"/><circle cx="322" cy="258" r="1.4"/><circle cx="379" cy="287" r="1.8"/>
              <circle cx="425" cy="312" r="1.4"/><circle cx="460" cy="360" r="2.2"/><circle cx="506" cy="394" r="1.8"/>
              <circle cx="548" cy="372" r="1.2"/><circle cx="214" cy="322" r="1.4"/><circle cx="186" cy="283" r="1.1"/>
            </g>
          </g>
          <circle className="globe-outline" cx="360" cy="360" r="305"/>
          <path className="globe-rim-light" d="M121 171C223 35 424 27 539 127"/>
        </svg>
        <div className="globe-atmosphere" aria-hidden="true"/>
        <div className="globe-scan"/>
        {projects.map(project=><button
          type="button"
          className={`project-map-point risk-${project.risk_level.toLowerCase()} ${project.id===selected?.id?'active':''}`}
          style={pointStyle(project)}
          onClick={()=>setSelectedId(project.id)}
          aria-label={`${project.name}, ${project.location_name}`}
          aria-pressed={project.id===selected?.id}
          key={project.id}
        ><i/><span>{project.country_code}</span></button>)}
      </div>
      <div className="map-coordinates" aria-hidden="true"><span>03°08&apos;N</span><i/><span>LIVE GEOINT</span><i/><span>101°41&apos;E</span></div>
      <div className="map-status"><i className="live-dot"/>{labels.live}<span>{projects.length} {labels.projectsOnline}</span></div>
    </div>
    {selected?<aside className="globe-project-detail" aria-live="polite">
      <div className="globe-project-code"><span>{selected.country_code}</span>{selected.code}</div>
      <h3>{selected.name}</h3>
      <p>{selected.location_name} · {selected.country_name}</p>
      <div className="globe-project-tags"><span>{selected.domain}</span><span className={`risk-${selected.risk_level.toLowerCase()}`}>{selected.risk_level}</span></div>
      <div className="globe-project-kpis">
        <div><span>{labels.progress}</span><b>{selected.progress}%</b></div>
        <div><span>{labels.schedule}</span><b className={selected.schedule_variance<0?'negative':'positive'}>{selected.schedule_variance>0?'+':''}{selected.schedule_variance}d</b></div>
        <div><span>{labels.phase}</span><b>{selected.phase}</b></div>
      </div>
      <div className="globe-progress"><i style={{width:`${selected.progress}%`}}/></div>
      <Link className="map-project-link" href={`/projects/${selected.id}`}>{labels.openProject}<span>↗</span></Link>
    </aside>:null}
  </div>;
}
