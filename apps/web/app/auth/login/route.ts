import { NextRequest, NextResponse } from 'next/server';
import {
  OIDC_TRANSACTION_COOKIE,
  OIDC_TRANSACTION_TTL_SECONDS,
  secureCookieOptions,
} from '@/lib/auth/constants';
import { createAuthorizationRequest, loadOidcRuntimeConfig, sanitizeReturnTo } from '@/lib/auth/oidc';
import { sealOidcTransaction } from '@/lib/auth/session';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest) {
  const returnTo = sanitizeReturnTo(request.nextUrl.searchParams.get('returnTo'));
  if (process.env.API_AUTH_MODE === 'disabled') {
    return NextResponse.redirect(new URL(returnTo, request.url));
  }

  try {
    const config = loadOidcRuntimeConfig();
    const { authorizationUrl, transaction } = createAuthorizationRequest(config, returnTo);
    const response = NextResponse.redirect(authorizationUrl);
    response.headers.set('cache-control', 'no-store');
    response.cookies.set(
      OIDC_TRANSACTION_COOKIE,
      sealOidcTransaction(transaction),
      secureCookieOptions(OIDC_TRANSACTION_TTL_SECONDS),
    );
    return response;
  } catch {
    return NextResponse.json(
      { detail: 'Browser OIDC is not configured correctly.' },
      { status: 503, headers: { 'cache-control': 'no-store' } },
    );
  }
}
