import { NextRequest, NextResponse } from 'next/server';
import {
  OIDC_TRANSACTION_COOKIE,
  WEB_SESSION_COOKIE,
  secureCookieOptions,
} from '@/lib/auth/constants';
import { loadOidcRuntimeConfig, sanitizeReturnTo } from '@/lib/auth/oidc';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest) {
  const returnTo = sanitizeReturnTo(request.nextUrl.searchParams.get('returnTo') || '/competition');
  let base = request.url;
  if (process.env.API_AUTH_MODE !== 'disabled') {
    try {
      base = loadOidcRuntimeConfig().redirectUri;
    } catch {
      return NextResponse.json(
        { detail: 'Browser OIDC is not configured correctly.' },
        { status: 503, headers: { 'cache-control': 'no-store' } },
      );
    }
  }
  const response = NextResponse.redirect(new URL(returnTo, base));
  response.headers.set('cache-control', 'no-store');
  for (const name of [WEB_SESSION_COOKIE, OIDC_TRANSACTION_COOKIE]) {
    response.cookies.set(name, '', {
      ...secureCookieOptions(0),
      expires: new Date(0),
    });
  }
  return response;
}
