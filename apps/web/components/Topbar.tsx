import Link from 'next/link';
import { useLocale, useTranslations } from 'next-intl';
import { LocaleSwitcher } from './LocaleSwitcher';
import { ThemeToggle } from './ThemeToggle';

export function Topbar() {
  const t = useTranslations('Topbar');
  const locale = useLocale();
  const timestamp = new Intl.DateTimeFormat(locale === 'zh' ? 'zh-CN' : 'en-GB', {
    year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
    hour12: false, timeZone: 'Asia/Shanghai', timeZoneName: 'short',
  }).format(new Date());
  return <header className="topbar">
    <Link className="mobile-app-brand" href="/" aria-label="GlobalInfra AI">
      <span className="mobile-brand-mark">GI</span><span><b>GlobalInfra AI</b><small>{t('title')}</small></span>
    </Link>
    <div className="scope"><span className="crumb">{t('crumb')}</span><span>/</span><b>{t('title')}</b></div>
    <div className="top-actions">
      <span className="data-pill"><span className="status-dot" />{t('dataSynced')}</span>
      <time className="scope" dateTime={new Date().toISOString()}>{timestamp}</time>
      <ThemeToggle />
      <LocaleSwitcher />
      <span className="avatar">MQ</span>
    </div>
  </header>;
}
