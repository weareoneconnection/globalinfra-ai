'use client';

import { useEffect, useState } from 'react';
import { useTranslations } from 'next-intl';

export const THEME_KEY = 'globalinfra-theme';
export const THEME_COLORS = { dark: '#071016', light: '#f3f7f9' } as const;
type Theme = keyof typeof THEME_COLORS;

// Runs before first paint (see layout.tsx) so a saved light theme never
// flashes dark. Dark stays the default.
export const THEME_BOOT_SCRIPT = `try{var t=localStorage.getItem('${THEME_KEY}');if(t==='light'){document.documentElement.dataset.theme='light';var m=document.querySelector('meta[name="theme-color"]');if(m)m.setAttribute('content','${THEME_COLORS.light}')}}catch(e){}`;

export function ThemeToggle() {
  const t = useTranslations('Topbar');
  const [theme, setTheme] = useState<Theme>('dark');

  useEffect(() => {
    setTheme(document.documentElement.dataset.theme === 'light' ? 'light' : 'dark');
  }, []);

  function toggle() {
    const next: Theme = theme === 'light' ? 'dark' : 'light';
    if (next === 'light') document.documentElement.dataset.theme = 'light';
    else delete document.documentElement.dataset.theme;
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', THEME_COLORS[next]);
    try { localStorage.setItem(THEME_KEY, next); } catch { /* storage unavailable: applies to this page only */ }
    setTheme(next);
  }

  const label = theme === 'light' ? t('themeToDark') : t('themeToLight');
  return <button type="button" className="lang-switch theme-switch" onClick={toggle} aria-label={label} title={label}>
    {theme === 'light' ? '☾' : '☀'}
  </button>;
}
