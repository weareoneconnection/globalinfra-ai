import { NextRequest } from 'next/server';

async function proxy(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  const base = (process.env.API_INTERNAL_URL || 'http://localhost:8000').replace(/\/$/, '');
  const target = `${base}/${path.join('/')}${req.nextUrl.search}`;
  const body = ['GET','HEAD'].includes(req.method) ? undefined : await req.arrayBuffer();
  const headers = new Headers();
  for (const name of ['content-type', 'accept', 'accept-language', 'authorization', 'x-request-id']) {
    const value = req.headers.get(name);
    if (value) headers.set(name, value);
  }
  const serviceKey = process.env.API_SERVICE_KEY;
  if (serviceKey) headers.set('x-api-key', serviceKey);

  try {
    const res = await fetch(target, {
      method: req.method,
      headers,
      body,
      cache: 'no-store',
      signal: AbortSignal.timeout(30_000)
    });
    const data = await res.arrayBuffer();
    const responseHeaders = new Headers();
    for (const name of ['content-type', 'content-language', 'content-disposition', 'x-data-provenance', 'retry-after']) {
      const value = res.headers.get(name);
      if (value) responseHeaders.set(name, value);
    }
    return new Response(data, { status: res.status, headers: responseHeaders });
  } catch {
    return Response.json({ detail: 'API service is unavailable' }, { status: 502 });
  }
}
export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
