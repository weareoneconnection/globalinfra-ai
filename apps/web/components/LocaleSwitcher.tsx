'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useRouter } from 'next/navigation';

// The platform auto-detects the browser's language on first visit (see
// middleware.ts). This lets a user override that choice manually; the
// choice is remembered in the same cookie the middleware uses.
export function LocaleSwitcher() {
  const locale = useLocale();
  const t = useTranslations('Topbar');
  const router = useRouter();
  const nextLocale = locale === 'zh' ? 'en' : 'zh';

  function switchLocale() {
    document.cookie = `NEXT_LOCALE=${nextLocale}; path=/; max-age=31536000`;
    router.refresh();
  }

  return (
    <button type="button" className="lang-switch" onClick={switchLocale} aria-label="switch language">
      {t('switchToLabel')}
    </button>
  );
}
