import { useTranslations } from 'next-intl';
import { LocaleSwitcher } from './LocaleSwitcher';

export function Topbar() {
  const t = useTranslations('Topbar');
  return <header className="topbar">
    <div className="scope"><span className="crumb">{t('crumb')}</span><span>/</span><b>{t('title')}</b></div>
    <div className="top-actions">
      <span className="data-pill"><span className="status-dot" />{t('dataSynced')}</span>
      <span className="scope">{t('timestamp')}</span>
      <LocaleSwitcher />
      <span className="avatar">MQ</span>
    </div>
  </header>;
}
