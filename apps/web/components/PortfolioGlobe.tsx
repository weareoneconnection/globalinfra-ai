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

function pointStyle(project:GlobeProject):CSSProperties {
  return {
    '--point-x': `${((project.longitude + 180) / 360) * 100}%`,
    '--point-y': `${((90 - project.latitude) / 180) * 100}%`,
  } as CSSProperties;
}

export function PortfolioGlobe({projects,labels}:{projects:GlobeProject[];labels:GlobeLabels}) {
  const [selectedId,setSelectedId]=useState(projects[0]?.id ?? 0);
  const selected=projects.find(project=>project.id===selectedId) ?? projects[0];

  return <div className="portfolio-map-layout">
    <div className="globe-stage" aria-label={labels.projectsOnline}>
      <div className="globe-halo"/>
      <div className="globe-sphere">
        <svg className="globe-world" viewBox="0 0 720 360" role="img" aria-label={labels.projectsOnline}>
          <defs><clipPath id="earthClip"><ellipse cx="360" cy="180" rx="350" ry="170"/></clipPath></defs>
          <ellipse className="globe-ocean" cx="360" cy="180" rx="350" ry="170"/>
          <g clipPath="url(#earthClip)">
            <path className="continent" d="M54 105l49-48 79-18 68 17 33 45-24 28-44 2-31 38-35 8-22-25-50-10z"/>
            <path className="continent" d="M206 183l42 18 20 45-13 77-37 21-28-43 4-51-24-32z"/>
            <path className="continent" d="M326 75l55-29 69 13 47 35 65 4 90 50-17 37-73 8-31 34-60-16-47 18-32-40-43-9-31-42z"/>
            <path className="continent" d="M382 191l67 13 25 43-24 76-39 17-30-61-18-52z"/>
            <path className="continent" d="M588 255l49-11 45 31-18 43-58 4-31-34z"/>
            <path className="globe-route" d="M453 131 Q505 205 563 182 T594 180"/>
          </g>
          <ellipse className="globe-outline" cx="360" cy="180" rx="350" ry="170"/>
          <ellipse className="globe-grid-line" cx="360" cy="180" rx="350" ry="93"/>
          <ellipse className="globe-grid-line" cx="360" cy="180" rx="192" ry="170"/>
          <path className="globe-grid-line" d="M10 180h700M360 10v340"/>
        </svg>
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
