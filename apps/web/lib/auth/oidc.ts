import {
  constants as cryptoConstants,
  createHash,
  createPublicKey,
  randomBytes,
  verify as verifySignature,
} from 'node:crypto';
import type { JsonWebKey } from 'node:crypto';
import { MAX_WEB_SESSION_TTL_SECONDS, OIDC_TRANSACTION_TTL_SECONDS } from './constants';
import { constantTimeTextEqual, type OidcTransaction } from './session';

export type OidcRuntimeConfig = {
  clientId: string;
  clientSecret: string | null;
  issuer: string;
  jwksUrl: string;
  authorizationEndpoint: string;
  tokenEndpoint: string;
  redirectUri: string;
  scopes: string;
  resourceAudience: string | null;
};

export type ExchangedAccessToken = {
  accessToken: string;
  expiresIn: number;
};

export class OidcConfigurationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'OidcConfigurationError';
  }
}

export class OidcProtocolError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'OidcProtocolError';
  }
}

type JwkRecord = Record<string, unknown>;
type JwksCache = { url: string; expiresAt: number; keys: JwkRecord[] };
let jwksCache: JwksCache | null = null;
const JWKS_CACHE_TTL_MS = 5 * 60 * 1_000;

function requiredEnvironment(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new OidcConfigurationError(`${name} is required for browser OIDC.`);
  const normalized = value.toUpperCase();
  if (
    normalized.startsWith('REPLACE')
    || normalized.includes('CHANGEME')
    || normalized.includes('CHANGE_ME')
  ) {
    throw new OidcConfigurationError(`${name} must not be a placeholder.`);
  }
  return value;
}

function secureUrl(name: string, value: string): URL {
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    throw new OidcConfigurationError(`${name} must be an absolute URL.`);
  }
  if (url.username || url.password || url.hash) {
    throw new OidcConfigurationError(`${name} must not contain credentials or a fragment.`);
  }
  const localDevelopment = process.env.NODE_ENV !== 'production'
    && url.protocol === 'http:'
    && ['localhost', '127.0.0.1', '::1'].includes(url.hostname);
  if (url.protocol !== 'https:' && !localDevelopment) {
    throw new OidcConfigurationError(`${name} must use HTTPS outside local development.`);
  }
  return url;
}

export function loadOidcRuntimeConfig(): OidcRuntimeConfig {
  const clientId = requiredEnvironment('OIDC_CLIENT_ID');
  const issuerValue = requiredEnvironment('OIDC_ISSUER');
  const authorizationEndpoint = secureUrl(
    'OIDC_AUTHORIZATION_ENDPOINT',
    requiredEnvironment('OIDC_AUTHORIZATION_ENDPOINT'),
  );
  const tokenEndpoint = secureUrl(
    'OIDC_TOKEN_ENDPOINT',
    requiredEnvironment('OIDC_TOKEN_ENDPOINT'),
  );
  const jwksUrl = secureUrl('OIDC_JWKS_URL', requiredEnvironment('OIDC_JWKS_URL'));
  const redirectUri = secureUrl('OIDC_REDIRECT_URI', requiredEnvironment('OIDC_REDIRECT_URI'));
  if (redirectUri.pathname !== '/auth/callback' || redirectUri.search) {
    throw new OidcConfigurationError('OIDC_REDIRECT_URI must point exactly to /auth/callback.');
  }
  // Issuer matching is byte-for-byte in OIDC. Validate the URL but preserve
  // the configured identifier so URL serialization cannot add a trailing
  // slash that the provider's `iss` claim does not contain.
  secureUrl('OIDC_ISSUER', issuerValue);
  const issuer = issuerValue;
  const scopes = process.env.OIDC_SCOPES?.trim() || 'openid profile email';
  if (!scopes.split(/\s+/).includes('openid')) {
    throw new OidcConfigurationError('OIDC_SCOPES must include openid.');
  }
  const clientSecret = process.env.OIDC_CLIENT_SECRET?.trim() || null;
  if (clientSecret && /^(REPLACE|CHANGEME|CHANGE_ME)/i.test(clientSecret)) {
    throw new OidcConfigurationError('OIDC_CLIENT_SECRET must not be a placeholder.');
  }
  return {
    clientId,
    clientSecret,
    issuer,
    jwksUrl: jwksUrl.toString(),
    authorizationEndpoint: authorizationEndpoint.toString(),
    tokenEndpoint: tokenEndpoint.toString(),
    redirectUri: redirectUri.toString(),
    scopes,
    resourceAudience: process.env.OIDC_AUDIENCE?.trim() || null,
  };
}

function randomUrlSafe(bytes: number): string {
  return randomBytes(bytes).toString('base64url');
}

export function sanitizeReturnTo(value: string | null): string {
  if (!value) return '/';
  const candidate = value.trim();
  if (
    !candidate.startsWith('/')
    || candidate.startsWith('//')
    || candidate.includes('\\')
    || /%5c/i.test(candidate)
    || /[\u0000-\u001f\u007f]/.test(candidate)
  ) {
    return '/';
  }
  try {
    const base = new URL('https://globalinfra.invalid');
    const parsed = new URL(candidate, base);
    if (parsed.origin !== base.origin || parsed.pathname.startsWith('/auth/')) return '/';
    return `${parsed.pathname}${parsed.search}${parsed.hash}`;
  } catch {
    return '/';
  }
}

export function createAuthorizationRequest(
  config: OidcRuntimeConfig,
  returnToValue: string | null,
  now = Date.now(),
): { authorizationUrl: URL; transaction: OidcTransaction } {
  const state = randomUrlSafe(32);
  const nonce = randomUrlSafe(32);
  const codeVerifier = randomUrlSafe(64);
  const codeChallenge = createHash('sha256').update(codeVerifier, 'ascii').digest('base64url');
  const authorizationUrl = new URL(config.authorizationEndpoint);
  authorizationUrl.searchParams.set('response_type', 'code');
  authorizationUrl.searchParams.set('client_id', config.clientId);
  authorizationUrl.searchParams.set('redirect_uri', config.redirectUri);
  authorizationUrl.searchParams.set('scope', config.scopes);
  authorizationUrl.searchParams.set('state', state);
  authorizationUrl.searchParams.set('nonce', nonce);
  authorizationUrl.searchParams.set('code_challenge', codeChallenge);
  authorizationUrl.searchParams.set('code_challenge_method', 'S256');
  if (config.resourceAudience) {
    authorizationUrl.searchParams.set('audience', config.resourceAudience);
  }

  return {
    authorizationUrl,
    transaction: {
      version: 1,
      state,
      nonce,
      codeVerifier,
      returnTo: sanitizeReturnTo(returnToValue),
      expiresAt: now + OIDC_TRANSACTION_TTL_SECONDS * 1_000,
    },
  };
}

function parseJwtPart(value: string): Record<string, unknown> {
  try {
    const parsed = JSON.parse(Buffer.from(value, 'base64url').toString('utf8')) as unknown;
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) throw new Error();
    return parsed as Record<string, unknown>;
  } catch {
    throw new OidcProtocolError('The returned ID token is malformed.');
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

async function loadJwks(url: string, forceRefresh = false): Promise<JwkRecord[]> {
  if (!forceRefresh && jwksCache?.url === url && jwksCache.expiresAt > Date.now()) {
    return jwksCache.keys;
  }
  let response: Response;
  try {
    response = await fetch(url, {
      headers: { accept: 'application/json' },
      cache: 'no-store',
      signal: AbortSignal.timeout(10_000),
    });
  } catch {
    throw new OidcProtocolError('The OIDC JWKS endpoint is unavailable.');
  }
  if (!response.ok) {
    throw new OidcProtocolError(`The OIDC JWKS endpoint returned ${response.status}.`);
  }
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new OidcProtocolError('The OIDC JWKS endpoint returned invalid JSON.');
  }
  if (
    !isRecord(payload)
    || !Array.isArray(payload.keys)
    || payload.keys.length === 0
    || payload.keys.length > 100
    || !payload.keys.every(isRecord)
  ) {
    throw new OidcProtocolError('The OIDC JWKS document is invalid.');
  }
  const keys = payload.keys as JwkRecord[];
  jwksCache = { url, keys, expiresAt: Date.now() + JWKS_CACHE_TTL_MS };
  return keys;
}

function compatibleJwk(jwk: JwkRecord, algorithm: string): boolean {
  if (jwk.use !== undefined && jwk.use !== 'sig') return false;
  if (jwk.alg !== undefined && jwk.alg !== algorithm) return false;
  if (
    jwk.key_ops !== undefined
    && (!Array.isArray(jwk.key_ops)
      || !jwk.key_ops.every(operation => typeof operation === 'string')
      || !jwk.key_ops.includes('verify'))
  ) return false;
  if (algorithm === 'RS256' || algorithm === 'PS256') return jwk.kty === 'RSA';
  if (algorithm === 'ES256') return jwk.kty === 'EC' && jwk.crv === 'P-256';
  return false;
}

async function selectSigningKey(
  config: OidcRuntimeConfig,
  algorithm: string,
  keyId: unknown,
): Promise<JwkRecord> {
  if (keyId !== undefined && (typeof keyId !== 'string' || !keyId)) {
    throw new OidcProtocolError('The returned ID token key ID is invalid.');
  }
  const match = (keys: JwkRecord[]) => keys.filter(key =>
    compatibleJwk(key, algorithm)
    && (typeof keyId === 'string' ? key.kid === keyId : true));
  let candidates = match(await loadJwks(config.jwksUrl));
  if (typeof keyId === 'string' && candidates.length === 0) {
    candidates = match(await loadJwks(config.jwksUrl, true));
  }
  if (candidates.length !== 1) {
    throw new OidcProtocolError('The returned ID token does not identify one trusted signing key.');
  }
  return candidates[0];
}

function hashClaim(value: string): string {
  const digest = createHash('sha256').update(value, 'ascii').digest();
  return digest.subarray(0, digest.length / 2).toString('base64url');
}

async function validateIdToken(
  idToken: string,
  config: OidcRuntimeConfig,
  expectedNonce: string,
  accessToken: string,
  authorizationCode: string,
  now = Date.now(),
): Promise<void> {
  const parts = idToken.split('.');
  if (
    parts.length !== 3
    || parts.some(part => !part || !/^[A-Za-z0-9_-]+$/.test(part))
  ) {
    throw new OidcProtocolError('The returned ID token is malformed.');
  }
  const header = parseJwtPart(parts[0]);
  const claims = parseJwtPart(parts[1]);
  const algorithm = header.alg;
  if (
    header.crit !== undefined
    || (header.b64 !== undefined && header.b64 !== true)
  ) {
    throw new OidcProtocolError('The returned ID token uses unsupported critical headers.');
  }
  if (!['RS256', 'PS256', 'ES256'].includes(String(algorithm))) {
    throw new OidcProtocolError('The returned ID token uses an invalid algorithm.');
  }
  const jwk = await selectSigningKey(config, String(algorithm), header.kid);
  let key;
  try {
    key = createPublicKey({ key: jwk as JsonWebKey, format: 'jwk' });
  } catch {
    throw new OidcProtocolError('The OIDC signing key is invalid.');
  }
  const signingInput = Buffer.from(`${parts[0]}.${parts[1]}`, 'ascii');
  const signature = Buffer.from(parts[2], 'base64url');
  let signatureValid = false;
  if (algorithm === 'RS256') {
    signatureValid = verifySignature('RSA-SHA256', signingInput, key, signature);
  } else if (algorithm === 'PS256') {
    signatureValid = verifySignature('sha256', signingInput, {
      key,
      padding: cryptoConstants.RSA_PKCS1_PSS_PADDING,
      saltLength: 32,
    }, signature);
  } else if (algorithm === 'ES256') {
    signatureValid = verifySignature('sha256', signingInput, {
      key,
      dsaEncoding: 'ieee-p1363',
    }, signature);
  }
  if (!signatureValid) {
    throw new OidcProtocolError('The returned ID token signature is invalid.');
  }
  if (claims.iss !== config.issuer) {
    throw new OidcProtocolError('The returned ID token issuer does not match.');
  }
  if (typeof claims.nonce !== 'string' || !constantTimeTextEqual(claims.nonce, expectedNonce)) {
    throw new OidcProtocolError('The returned ID token nonce does not match.');
  }
  const audience = claims.aud;
  if (typeof audience === 'string') {
    if (audience !== config.clientId) {
      throw new OidcProtocolError('The returned ID token audience does not match.');
    }
  } else if (Array.isArray(audience) && audience.every(item => typeof item === 'string')) {
    if (!audience.includes(config.clientId) || (audience.length > 1 && claims.azp !== config.clientId)) {
      throw new OidcProtocolError('The returned ID token audience does not match.');
    }
  } else {
    throw new OidcProtocolError('The returned ID token audience is invalid.');
  }
  if (claims.azp !== undefined && claims.azp !== config.clientId) {
    throw new OidcProtocolError('The returned ID token authorized party does not match.');
  }
  const nowSeconds = Math.floor(now / 1_000);
  if (!Number.isSafeInteger(claims.exp) || (claims.exp as number) <= nowSeconds - 60) {
    throw new OidcProtocolError('The returned ID token is expired or has no valid expiry.');
  }
  if (!Number.isSafeInteger(claims.iat) || (claims.iat as number) > nowSeconds + 60) {
    throw new OidcProtocolError('The returned ID token has no valid issued-at time.');
  }
  if (typeof claims.sub !== 'string' || !claims.sub) {
    throw new OidcProtocolError('The returned ID token has no subject.');
  }
  if (
    claims.at_hash !== undefined
    && (typeof claims.at_hash !== 'string'
      || !constantTimeTextEqual(claims.at_hash, hashClaim(accessToken)))
  ) {
    throw new OidcProtocolError('The returned ID token access-token hash does not match.');
  }
  if (
    claims.c_hash !== undefined
    && (typeof claims.c_hash !== 'string'
      || !constantTimeTextEqual(claims.c_hash, hashClaim(authorizationCode)))
  ) {
    throw new OidcProtocolError('The returned ID token authorization-code hash does not match.');
  }
}

export async function exchangeAuthorizationCode(
  config: OidcRuntimeConfig,
  code: string,
  transaction: OidcTransaction,
): Promise<ExchangedAccessToken> {
  if (!code || code.length > 4_096) throw new OidcProtocolError('Authorization code is missing.');
  const body = new URLSearchParams({
    grant_type: 'authorization_code',
    code,
    redirect_uri: config.redirectUri,
    code_verifier: transaction.codeVerifier,
  });
  const headers = new Headers({
    accept: 'application/json',
    'content-type': 'application/x-www-form-urlencoded',
  });
  if (config.clientSecret) {
    const formEncode = (value: string) => new URLSearchParams({ value })
      .toString()
      .slice('value='.length);
    const clientCredentials = `${formEncode(config.clientId)}:${formEncode(config.clientSecret)}`;
    headers.set('authorization', `Basic ${Buffer.from(clientCredentials, 'utf8').toString('base64')}`);
  } else {
    body.set('client_id', config.clientId);
  }

  let response: Response;
  try {
    response = await fetch(config.tokenEndpoint, {
      method: 'POST',
      headers,
      body,
      cache: 'no-store',
      signal: AbortSignal.timeout(15_000),
    });
  } catch {
    throw new OidcProtocolError('The OIDC token endpoint is unavailable.');
  }
  if (!response.ok) {
    throw new OidcProtocolError(`The OIDC token endpoint rejected the authorization code (${response.status}).`);
  }

  let payload: Record<string, unknown>;
  try {
    const parsed = await response.json() as unknown;
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) throw new Error();
    payload = parsed as Record<string, unknown>;
  } catch {
    throw new OidcProtocolError('The OIDC token endpoint returned an invalid response.');
  }
  if (
    typeof payload.access_token !== 'string'
    || payload.access_token.length === 0
    || /\s/.test(payload.access_token)
  ) {
    throw new OidcProtocolError('The OIDC token endpoint did not return an access token.');
  }
  if (typeof payload.token_type !== 'string' || payload.token_type.toLowerCase() !== 'bearer') {
    throw new OidcProtocolError('The OIDC token endpoint returned an unsupported token type.');
  }
  if (typeof payload.expires_in !== 'number' || !Number.isFinite(payload.expires_in) || payload.expires_in <= 0) {
    throw new OidcProtocolError('The OIDC token endpoint did not return a valid token lifetime.');
  }
  if (typeof payload.id_token !== 'string') {
    throw new OidcProtocolError('The OIDC token endpoint did not return a valid ID token.');
  }
  await validateIdToken(
    payload.id_token,
    config,
    transaction.nonce,
    payload.access_token,
    code,
  );
  return {
    accessToken: payload.access_token,
    expiresIn: Math.min(Math.floor(payload.expires_in), MAX_WEB_SESSION_TTL_SECONDS),
  };
}

export function statesMatch(returnedState: string | null, expectedState: string): boolean {
  return typeof returnedState === 'string'
    && returnedState.length > 0
    && constantTimeTextEqual(returnedState, expectedState);
}
