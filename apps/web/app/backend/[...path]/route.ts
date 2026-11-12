import { NextRequest } from 'next/server';
import { WEB_SESSION_COOKIE } from '@/lib/auth/constants';
import { isPublicCompetitionApiRequest } from '@/lib/auth/public-routes';
import {
  parseBearerAuthorization,
  SessionCookieError,
  unsealWebSession,
} from '@/lib/auth/session';

const DEFAULT_TIMEOUT_MS = 30_000;
const LONG_AI_TIMEOUT_MS = 180_000;

function timeoutFor(path: string[]): number {
  const route = path.join('/');
  if (route.includes('telemetry/live')) return 300_000;
  if (
    route === 'intake/text' ||
    route === 'intake/document' ||
    route === 'i18n/translate' ||
    route === 'assistant/chat' ||
    route === 'assistant/dispatch' ||
    /^cases\/[^/]+\/(analyze|confirm-project|execute)$/.test(route) ||
    /^actions\/[^/]+\/execute$/.test(route)
  ) {
    const configured = Number(process.env.API_LONG_REQUEST_TIMEOUT_MS);
    return Number.isFinite(configured) && configured >= DEFAULT_TIMEOUT_MS
      ? configured
      : LONG_AI_TIMEOUT_MS;
  }
  return DEFAULT_TIMEOUT_MS;
}

function trustedBrowserOrigin(): string | null {
  const configured = process.env.OIDC_REDIRECT_URI;
  if (!configured) return null;
  try {
    return new URL(configured).origin;
  } catch {
    return null;
  }
}

async function proxy(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  const base = (process.env.API_INTERNAL_URL || 'http://localhost:8000').replace(/\/$/, '');
  const target = `${base}/${path.join('/')}${req.nextUrl.search}`;
  const body = ['GET','HEAD'].includes(req.method) ? undefined : await req.arrayBuffer();
  const headers = new Headers();
  for (const name of ['content-type', 'accept', 'accept-language', 'x-request-id', 'x-competition-role-ticket']) {
    const value = req.headers.get(name);
    if (value) headers.set(name, value);
  }
  const explicitBearer = parseBearerAuthorization(req.headers.get('authorization'));
  const publicCompetitionRequest = isPublicCompetitionApiRequest(req.method, path);
  const demoMode = process.env.API_AUTH_MODE === 'disabled';
  const unsafeMethod = !['GET', 'HEAD', 'OPTIONS'].includes(req.method);
  let accessToken = explicitBearer;
  let sessionAuthenticated = false;
  if (!accessToken && !publicCompetitionRequest && !demoMode) {
    const sealedSession = req.cookies.get(WEB_SESSION_COOKIE)?.value;
    if (sealedSession) {
      try {
        accessToken = unsealWebSession(sealedSession).accessToken;
        sessionAuthenticated = true;
      } catch (error) {
        if (!(error instanceof SessionCookieError)) throw error;
      }
    }
  }
  if (accessToken) headers.set('authorization', `Bearer ${accessToken}`);
  if (!accessToken && !publicCompetitionRequest && !demoMode) {
    return Response.json(
      { detail: 'A valid OIDC browser session is required for this API route.' },
      { status: 401 }
    );
  }
  const requestOrigin = req.headers.get('origin');
  const expectedOrigin = trustedBrowserOrigin() ?? (demoMode ? req.nextUrl.origin : null);
  if (
    unsafeMethod
    && ((sessionAuthenticated && !requestOrigin)
      || (requestOrigin !== null && requestOrigin !== expectedOrigin))
  ) {
    return Response.json(
      { detail: 'The browser request origin is not allowed.' },
      { status: 403 },
    );
  }
  // API_SERVICE_KEY is preferred; API_KEY keeps single-service deployments
  // compatible. Neither value is forwarded for tenant/business routes.
  const serviceKey = process.env.API_SERVICE_KEY || process.env.API_KEY;
  if (!explicitBearer && publicCompetitionRequest && serviceKey) {
    headers.set('x-api-key', serviceKey);
  }
  const timeoutMs = timeoutFor(path);

  try {
    const res = await fetch(target, {
      method: req.method,
      headers,
      body,
      cache: 'no-store',
      signal: AbortSignal.timeout(timeoutMs)
    });
    const responseHeaders = new Headers();
    for (const name of ['content-type', 'content-language', 'content-disposition', 'x-data-provenance', 'retry-after']) {
      const value = res.headers.get(name);
      if (value) responseHeaders.set(name, value);
    }
    if (res.headers.get('content-type')?.includes('text/event-stream')) {
      responseHeaders.set('cache-control', 'no-cache');
      return new Response(res.body, { status: res.status, headers: responseHeaders });
    }
    const data = await res.arrayBuffer();
    return new Response(data, { status: res.status, headers: responseHeaders });
  } catch (error) {
    if (error instanceof Error && (error.name === 'TimeoutError' || error.name === 'AbortError')) {
      return Response.json(
        { detail: `AI processing exceeded ${Math.round(timeoutMs / 1000)} seconds. Please retry.` },
        { status: 504 }
      );
    }
    return Response.json({ detail: 'API service is unavailable' }, { status: 502 });
  }
}
export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
