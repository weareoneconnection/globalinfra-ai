import { getLocale } from 'next-intl/server';

export async function api<T>(path: string): Promise<T> {
  const base = process.env.API_INTERNAL_URL || 'http://localhost:8000';
  const locale = await getLocale();
  const separator = path.includes('?') ? '&' : '?';
  const headers = new Headers();
  const serviceKey = process.env.API_SERVICE_KEY;
  if (serviceKey) headers.set('x-api-key', serviceKey);
  const res = await fetch(`${base}${path}${separator}lang=${locale}`, { cache: 'no-store', headers });
  if (!res.ok) throw new Error(`API ${res.status}: ${await res.text()}`);
  return res.json();
}
