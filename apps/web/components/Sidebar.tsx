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
  const allItems = groups.flatMap(group => group.items);
  const mobileHrefs = ['/', '/field', '/twin', '/cases', '/approvals'];
  const mobileItems = mobileHrefs
    .map(href => allItems.find(item => item.href === href))
    .filter((item): item is NavItem => Boolean(item));

  const isActive = (href: string) => href === '/' ? pathname === '/' : pathname.startsWith(href);

  return <>
    <aside className="sidebar">
      <Link className="brand" href="/">
        <div className="brand-mark"><span>GI</span></div>
        <div><h1>{t('brandName')}</h1><p>{t('brandTag')}</p></div>
      </Link>
      <nav className="nav" aria-label={t('brandName')}>
        {groups.map(group => <div className="nav-group" key={group.label}>
          <div className="nav-section">{group.label}</div>
          {group.items.map(({ href, label, icon }) => <Link className={isActive(href) ? 'active' : ''} key={href} href={href} aria-current={isActive(href) ? 'page' : undefined}><span className="nav-icon">{icon}</span><span>{label}</span></Link>)}
        </div>)}
      </nav>
      <div className="sidebar-foot"><div><span className="status-dot" />{t('footerVersion')}</div><span>{t('footerSub')}</span></div>
    </aside>
    <nav className="mobile-bottom-nav" aria-label={t('brandName')}>
      {mobileItems.map(({ href, label, icon }) => <Link className={isActive(href) ? 'active' : ''} key={href} href={href} aria-current={isActive(href) ? 'page' : undefined}>
        <span className="mobile-nav-icon">{icon}</span><span>{label}</span>
      </Link>)}
    </nav>
  </>;
}
