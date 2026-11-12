export const WEB_SESSION_COOKIE = '__Host-globalinfra_session';
export const OIDC_TRANSACTION_COOKIE = '__Host-globalinfra_oidc_tx';

export const OIDC_TRANSACTION_TTL_SECONDS = 10 * 60;
export const MAX_WEB_SESSION_TTL_SECONDS = 24 * 60 * 60;

export function secureCookieOptions(maxAge: number) {
  return {
    httpOnly: true,
    secure: true,
    sameSite: 'lax' as const,
    path: '/',
    maxAge,
  };
}
