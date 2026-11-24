import { NextResponse } from 'next/server';

export const dynamic = 'force-dynamic';

export function GET() {
  return NextResponse.json(
    { status: 'ok', service: 'globalinfra-web', version: '6.1.0' },
    { headers: { 'cache-control': 'no-store' } },
  );
}
