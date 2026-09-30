'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

const groups = [
  { label: 'Global', items: [['Command Center', '/', '⌂'], ['Portfolio', '/projects', '◫']] },
  { label: 'Project Operations', items: [['Cases', '/cases', '◎'], ['Approvals', '/approvals', '✓'], ['Knowledge', '/knowledge', '◇']] },
  { label: 'Intelligence', items: [
    ['Project', '/intelligence/project', '01'], ['Engineering', '/intelligence/engineering', '02'],
    ['Delivery', '/intelligence/delivery', '03'], ['Commercial', '/intelligence/commercial', '04'],
    ['Risk & Assurance', '/intelligence/assurance', '05'], ['Resources', '/intelligence/resources', '06'],
    ['Knowledge', '/intelligence/knowledge', '07'], ['Assets & Operations', '/intelligence/assets', '08'],
  ]},
  { label: 'Platform', items: [['Agent Organization', '/agents', 'AI'], ['Architecture', '/architecture', '⌘']] },
];

export function Sidebar() {
  const pathname = usePathname();
  return <aside className="sidebar">
    <Link className="brand" href="/">
      <div className="brand-mark"><span>GI</span></div>
      <div><h1>GlobalInfra AI</h1><p>PROJECT INTELLIGENCE</p></div>
    </Link>
    <nav className="nav">
      {groups.map(group => <div className="nav-group" key={group.label}>
        <div className="nav-section">{group.label}</div>
        {group.items.map(([label, href, icon]) => {
          const active = href === '/' ? pathname === '/' : pathname.startsWith(href);
          return <Link className={active ? 'active' : ''} key={href} href={href}><span className="nav-icon">{icon}</span><span>{label}</span></Link>;
        })}
      </div>)}
    </nav>
    <div className="sidebar-foot"><div><span className="status-dot" />V1.1 · Domain Architecture</div><span>8 intelligence domains · 24 disciplines</span></div>
  </aside>;
}
