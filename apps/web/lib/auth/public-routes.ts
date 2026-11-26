const PUBLIC_COMPETITION_GET_ROUTES = new Set([
  'competition/golden-thread',
  'competition/evaluation',
  'competition/submission-evidence',
  'competition/finals/overview',
  'competition/evaluation-artifacts/latest',
  'competition/evidence-bundle',
]);

const PUBLIC_AUTH_ROUTES = new Set([
  '/auth/login',
  '/auth/callback',
  '/auth/logout',
]);

const SESSION_ID = 'CS-[A-F0-9]{20}';
const SESSION_STATE_ROUTE = new RegExp(`^competition/sessions/${SESSION_ID}/state$`);
const SESSION_ACTION_ROUTE = new RegExp(
  `^competition/sessions/${SESSION_ID}/(?:analyze|execute|verify|close|reset|tamper-probe)$`,
);
const SESSION_APPROVAL_ROUTE = new RegExp(
  `^competition/sessions/${SESSION_ID}/approvals/[1-9][0-9]*/approve$`,
);

function normalizeApiRoute(path: string | readonly string[]): string {
  const raw = typeof path === 'string' ? path : path.join('/');
  return raw.split(/[?#]/, 1)[0].replace(/^\/+|\/+$/g, '');
}

/**
 * Public competition traffic is deliberately fail-closed. Adding an API route
 * under /competition does not expose it until its method and shape are listed
 * here as part of the synthetic judge experience.
 */
export function isPublicCompetitionApiRequest(
  method: string,
  path: string | readonly string[],
): boolean {
  const route = normalizeApiRoute(path);
  const normalizedMethod = method.toUpperCase();

  if (normalizedMethod === 'GET') {
    return PUBLIC_COMPETITION_GET_ROUTES.has(route) || SESSION_STATE_ROUTE.test(route);
  }
  if (normalizedMethod !== 'POST') return false;
  return route === 'competition/sessions'
    || SESSION_ACTION_ROUTE.test(route)
    || SESSION_APPROVAL_ROUTE.test(route);
}

export function isPublicWebRequest(method: string, pathname: string): boolean {
  if (
    (pathname === '/competition' || pathname === '/competition/'
      || pathname === '/competition/jury' || pathname === '/competition/jury/'
      || pathname === '/competition/finals' || pathname === '/competition/finals/')
    || pathname === '/healthz'
    || pathname === '/readyz'
    || pathname === '/manifest.webmanifest'
    || pathname === '/sw.js'
    || PUBLIC_AUTH_ROUTES.has(pathname.replace(/\/$/, ''))
    || pathname.startsWith('/icons/')
  ) {
    return true;
  }

  const backendPrefix = '/backend/';
  return pathname.startsWith(backendPrefix)
    && isPublicCompetitionApiRequest(method, pathname.slice(backendPrefix.length));
}
