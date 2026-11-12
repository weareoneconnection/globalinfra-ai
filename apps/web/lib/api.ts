import { getLocale } from 'next-intl/server';
import { cookies, headers as requestHeaders } from 'next/headers';
import { WEB_SESSION_COOKIE } from './auth/constants';
import { isPublicCompetitionApiRequest } from './auth/public-routes';
import { parseBearerAuthorization, SessionCookieError, unsealWebSession } from './auth/session';

export async function api<T>(path: string): Promise<T> {
  const base = process.env.API_INTERNAL_URL || 'http://localhost:8000';
  const locale = await getLocale();
  const separator = path.includes('?') ? '&' : '?';
  const headers = new Headers();
  const incoming = await requestHeaders();
  const explicitBearer = parseBearerAuthorization(incoming.get('authorization'));
  const demoMode = process.env.API_AUTH_MODE === 'disabled';
  const publicCompetitionRequest = isPublicCompetitionApiRequest('GET', path);
  let accessToken = explicitBearer;
  if (!accessToken && !publicCompetitionRequest && !demoMode) {
    const cookieStore = await cookies();
    const sealedSession = cookieStore.get(WEB_SESSION_COOKIE)?.value;
    if (sealedSession) {
      try {
        accessToken = unsealWebSession(sealedSession).accessToken;
      } catch (error) {
        if (!(error instanceof SessionCookieError)) throw error;
      }
    }
  }
  if (accessToken) {
    headers.set('authorization', `Bearer ${accessToken}`);
  } else if (publicCompetitionRequest) {
    const serviceKey = process.env.API_SERVICE_KEY || process.env.API_KEY;
    if (serviceKey) headers.set('x-api-key', serviceKey);
  } else if (!demoMode) {
    throw new Error('A valid OIDC browser session is required for tenant API data');
  }
  const res = await fetch(`${base}${path}${separator}lang=${locale}`, { cache: 'no-store', headers });
  if (!res.ok) throw new Error(`API ${res.status}: ${await res.text()}`);
  return res.json();
}
