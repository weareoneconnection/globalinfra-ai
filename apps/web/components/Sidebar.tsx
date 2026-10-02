'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useTranslations } from 'next-intl';

type NavItem = { href: string; label: string; icon: string };
type NavGroup = { label: string; items: NavItem[] };

export function Sidebar() {
  const pathname = usePathname();
  const t = useTranslations('Sidebar');
  const groups = t.raw('groups') as NavGroup[];
  return <aside className="sidebar">
    <Link className="brand" href="/">
      <div className="brand-mark"><span>GI</span></div>
      <div><h1>{t('brandName')}</h1><p>{t('brandTag')}</p></div>
    </Link>
    <nav className="nav">
      {groups.map(group => <div className="nav-group" key={group.label}>
        <div className="nav-section">{group.label}</div>
        {group.items.map(({ href, label, icon }) => {
          const active = href === '/' ? pathname === '/' : pathname.startsWith(href);
          return <Link className={active ? 'active' : ''} key={href} href={href}><span className="nav-icon">{icon}</span><span>{label}</span></Link>;
        })}
      </div>)}
    </nav>
    <div className="sidebar-foot"><div><span className="status-dot" />{t('footerVersion')}</div><span>{t('footerSub')}</span></div>
  </aside>;
}
