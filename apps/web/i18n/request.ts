import { cookies, headers } from 'next/headers';
import { getRequestConfig } from 'next-intl/server';

const SUPPORTED_LOCALES = ['en', 'zh'];
const DEFAULT_LOCALE = 'en';

// No locale-prefixed routing: the locale is resolved from the cookie that
// `middleware.ts` sets after auto-detecting the browser's Accept-Language
// header (or from a manual override written to the same cookie), with the
// `x-locale` request header as a fallback for the very first request.
export default getRequestConfig(async () => {
  const [cookieStore, headerStore] = await Promise.all([cookies(), headers()]);
  const cookieLocale = cookieStore.get('NEXT_LOCALE')?.value;
  const headerLocale = headerStore.get('x-locale');
  const locale = [cookieLocale, headerLocale].find(
    (value): value is string => !!value && SUPPORTED_LOCALES.includes(value)
  ) || DEFAULT_LOCALE;

  return {
    locale,
    messages: (await import(`../messages/${locale}.json`)).default
  };
});
