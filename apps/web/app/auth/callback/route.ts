import { NextRequest, NextResponse } from 'next/server';
import {
  OIDC_TRANSACTION_COOKIE,
  WEB_SESSION_COOKIE,
  secureCookieOptions,
} from '@/lib/auth/constants';
import {
  exchangeAuthorizationCode,
  loadOidcRuntimeConfig,
  statesMatch,
} from '@/lib/auth/oidc';
import {
  sealWebSession,
  SessionCookieError,
  unsealOidcTransaction,
} from '@/lib/auth/session';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

function clearTransaction(response: NextResponse) {
  response.cookies.set(OIDC_TRANSACTION_COOKIE, '', {
    ...secureCookieOptions(0),
    expires: new Date(0),
  });
  return response;
}

function callbackError(status: number, detail: string) {
  return clearTransaction(NextResponse.json(
    { detail },
    { status, headers: { 'cache-control': 'no-store' } },
  ));
}

export async function GET(request: NextRequest) {
  if (process.env.API_AUTH_MODE === 'disabled') {
    return NextResponse.redirect(new URL('/', request.url));
  }
  if (request.nextUrl.searchParams.has('error')) {
    return callbackError(400, 'The identity provider did not authorize this sign-in.');
  }
  const sealedTransaction = request.cookies.get(OIDC_TRANSACTION_COOKIE)?.value;
  if (!sealedTransaction) {
    return callbackError(400, 'The OIDC transaction cookie is missing or expired.');
  }

  try {
    const transaction = unsealOidcTransaction(sealedTransaction);
    if (!statesMatch(request.nextUrl.searchParams.get('state'), transaction.state)) {
      return callbackError(400, 'The OIDC state did not match.');
    }
    const returnedIssuer = request.nextUrl.searchParams.get('iss');
    const config = loadOidcRuntimeConfig();
    if (returnedIssuer && returnedIssuer !== config.issuer) {
      return callbackError(400, 'The OIDC authorization response issuer did not match.');
    }
    const token = await exchangeAuthorizationCode(
      config,
      request.nextUrl.searchParams.get('code') || '',
      transaction,
    );
    const now = Date.now();
    const response = clearTransaction(
      NextResponse.redirect(new URL(transaction.returnTo, config.redirectUri)),
    );
    response.headers.set('cache-control', 'no-store');
    response.cookies.set(
      WEB_SESSION_COOKIE,
      sealWebSession({
        version: 1,
        accessToken: token.accessToken,
        expiresAt: now + token.expiresIn * 1_000,
      }),
      secureCookieOptions(token.expiresIn),
    );
    return response;
  } catch (error) {
    const detail = error instanceof SessionCookieError
      ? 'The OIDC transaction is invalid or expired.'
      : 'The OIDC authorization code could not be exchanged.';
    return callbackError(400, detail);
  }
}
