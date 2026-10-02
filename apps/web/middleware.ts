import { NextRequest, NextResponse } from 'next/server';

export const SUPPORTED_LOCALES = ['en', 'zh'] as const;
export const DEFAULT_LOCALE = 'en';
export const LOCALE_COOKIE = 'NEXT_LOCALE';

function pickLocale(acceptLanguage: string | null): string {
  if (!acceptLanguage) return DEFAULT_LOCALE;
  const weighted = acceptLanguage
    .split(',')
    .map(part => {
      const [tag, qPart] = part.trim().split(';q=');
      return { tag: tag.trim().toLowerCase(), q: qPart ? parseFloat(qPart) : 1 };
    })
    .sort((a, b) => b.q - a.q);
  for (const { tag } of weighted) {
    const primary = tag.split('-')[0];
    if ((SUPPORTED_LOCALES as readonly string[]).includes(primary)) return primary;
  }
  return DEFAULT_LOCALE;
}

// Follows the browser's language automatically (Accept-Language) on first
// visit, then remembers the choice (or a manual override) in a cookie so
// every subsequent request - and every server-side call into the API - uses
// the same language without changing any URL.
export function middleware(request: NextRequest) {
  const cookieLocale = request.cookies.get(LOCALE_COOKIE)?.value;
  const locale = cookieLocale && (SUPPORTED_LOCALES as readonly string[]).includes(cookieLocale)
    ? cookieLocale
    : pickLocale(request.headers.get('accept-language'));

  const forwardedHeaders = new Headers(request.headers);
  forwardedHeaders.set('x-locale', locale);
  const response = NextResponse.next({ request: { headers: forwardedHeaders } });
  if (!cookieLocale) {
    response.cookies.set(LOCALE_COOKIE, locale, { maxAge: 60 * 60 * 24 * 365, path: '/' });
  }
  return response;
}

export const config = {
  matcher: '/((?!_next|favicon.svg).*)'
};
