import { NextRequest } from 'next/server';

async function proxy(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  const base = process.env.API_INTERNAL_URL || 'http://localhost:8000';
  const target = `${base}/${path.join('/')}${req.nextUrl.search}`;
  const body = ['GET','HEAD'].includes(req.method) ? undefined : await req.arrayBuffer();
  const res = await fetch(target, {
    method: req.method,
    headers: { 'content-type': req.headers.get('content-type') || 'application/json' },
    body
  });
  const data = await res.arrayBuffer();
  return new Response(data, { status: res.status, headers: { 'content-type': res.headers.get('content-type') || 'application/json' } });
}
export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
