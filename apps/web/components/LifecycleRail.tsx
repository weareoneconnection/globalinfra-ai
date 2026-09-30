type Stage = { id:string; name:string; short:string; order:number };

export function LifecycleRail({ stages, active }: { stages:Stage[]; active?:string }) {
  const activeIndex = Math.max(0, stages.findIndex(s => s.id === active));
  return <div className="lifecycle-rail" aria-label="Project lifecycle">
    {stages.map((stage, index) => <div className={`life-stage ${index < activeIndex ? 'complete' : ''} ${index === activeIndex ? 'current' : ''}`} key={stage.id}>
      <div className="life-node"><span>{String(stage.order).padStart(2,'0')}</span></div>
      <div><strong>{stage.short}</strong><small>{stage.name}</small></div>
    </div>)}
  </div>;
}
