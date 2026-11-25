import { NextResponse } from 'next/server';
import { loadOidcRuntimeConfig } from '../../lib/auth/oidc';
import { assertSessionConfiguration } from '../../lib/auth/session';

export const dynamic = 'force-dynamic';

export function GET() {
  const authMode = process.env.API_AUTH_MODE?.trim();
  if (authMode === 'disabled') {
    return NextResponse.json({
      status: 'ready',
      readiness_class: process.env.DEPLOYMENT_PROFILE === 'competition_fast_launch'
        ? 'DEGRADED_COMPETITION'
        : 'STANDARD',
      deployment_profile: process.env.DEPLOYMENT_PROFILE ?? 'standard',
      auth_mode: 'disabled',
    });
  }
  if (authMode !== 'oidc') {
    return NextResponse.json(
      { status: 'not_ready', reason: 'unsupported_auth_mode' },
      { status: 503 },
    );
  }

  try {
    loadOidcRuntimeConfig();
    assertSessionConfiguration();
    return NextResponse.json({ status: 'ready', auth_mode: 'oidc' });
  } catch {
    return NextResponse.json(
      { status: 'not_ready', reason: 'invalid_oidc_configuration' },
      { status: 503 },
    );
  }
}
