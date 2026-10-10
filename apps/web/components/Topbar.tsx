import Link from 'next/link';
import { useTranslations } from 'next-intl';
import { LocaleSwitcher } from './LocaleSwitcher';

export function Topbar() {
  const t = useTranslations('Topbar');
  return <header className="topbar">
    <Link className="mobile-app-brand" href="/" aria-label="GlobalInfra AI">
      <span className="mobile-brand-mark">GI</span><span><b>GlobalInfra AI</b><small>{t('title')}</small></span>
    </Link>
    <div className="scope"><span className="crumb">{t('crumb')}</span><span>/</span><b>{t('title')}</b></div>
    <div className="top-actions">
      <span className="data-pill"><span className="status-dot" />{t('dataSynced')}</span>
      <span className="scope">{t('timestamp')}</span>
      <LocaleSwitcher />
      <span className="avatar">MQ</span>
    </div>
  </header>;
}
