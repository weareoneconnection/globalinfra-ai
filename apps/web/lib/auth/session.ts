import {
  createCipheriv,
  createDecipheriv,
  createHmac,
  randomBytes,
  timingSafeEqual,
} from 'node:crypto';

const COOKIE_VERSION = 'v1';
const COOKIE_AAD_PREFIX = 'globalinfra.web.cookie';
const MAX_SEALED_COOKIE_LENGTH = 3_800;

type CookiePurpose = 'oidc-transaction' | 'web-session';

export type OidcTransaction = {
  version: 1;
  state: string;
  nonce: string;
  codeVerifier: string;
  returnTo: string;
  expiresAt: number;
};

export type WebSession = {
  version: 1;
  accessToken: string;
  expiresAt: number;
};

export class SessionCookieError extends Error {
  constructor(message = 'The encrypted browser session is invalid or expired.') {
    super(message);
    this.name = 'SessionCookieError';
  }
}

function sessionSecret(): string {
  const secret = process.env.WEB_SESSION_SECRET;
  const normalized = secret?.trim().toUpperCase() || '';
  if (
    !secret
    || Buffer.byteLength(secret, 'utf8') < 32
    || normalized.startsWith('REPLACE')
    || normalized.includes('CHANGEME')
    || normalized.includes('CHANGE_ME')
  ) {
    throw new SessionCookieError('WEB_SESSION_SECRET must contain at least 32 bytes.');
  }
  return secret;
}

/** Validate the server-side cookie key without issuing or reading a cookie. */
export function assertSessionConfiguration(): void {
  sessionSecret();
}

function cookieKey(purpose: CookiePurpose): Buffer {
  return createHmac('sha256', sessionSecret())
    .update(`${COOKIE_AAD_PREFIX}:${COOKIE_VERSION}:${purpose}`)
    .digest();
}

function cookieAad(purpose: CookiePurpose): Buffer {
  return Buffer.from(`${COOKIE_AAD_PREFIX}:${COOKIE_VERSION}:${purpose}`, 'utf8');
}

function seal(payload: object, purpose: CookiePurpose): string {
  const iv = randomBytes(12);
  const cipher = createCipheriv('aes-256-gcm', cookieKey(purpose), iv);
  cipher.setAAD(cookieAad(purpose));
  const ciphertext = Buffer.concat([
    cipher.update(JSON.stringify(payload), 'utf8'),
    cipher.final(),
  ]);
  const authenticationTag = cipher.getAuthTag();
  return [
    COOKIE_VERSION,
    iv.toString('base64url'),
    ciphertext.toString('base64url'),
    authenticationTag.toString('base64url'),
  ].join('.');
}

function unseal(value: string, purpose: CookiePurpose): unknown {
  try {
    const [version, encodedIv, encodedCiphertext, encodedTag, extra] = value.split('.');
    if (version !== COOKIE_VERSION || !encodedIv || !encodedCiphertext || !encodedTag || extra) {
      throw new Error('Malformed cookie');
    }
    const iv = Buffer.from(encodedIv, 'base64url');
    const ciphertext = Buffer.from(encodedCiphertext, 'base64url');
    const authenticationTag = Buffer.from(encodedTag, 'base64url');
    if (iv.length !== 12 || authenticationTag.length !== 16 || ciphertext.length === 0) {
      throw new Error('Malformed cookie');
    }
    const decipher = createDecipheriv('aes-256-gcm', cookieKey(purpose), iv);
    decipher.setAAD(cookieAad(purpose));
    decipher.setAuthTag(authenticationTag);
    const plaintext = Buffer.concat([decipher.update(ciphertext), decipher.final()]);
    return JSON.parse(plaintext.toString('utf8')) as unknown;
  } catch (error) {
    if (error instanceof SessionCookieError) throw error;
    throw new SessionCookieError();
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isUrlSafeRandom(value: unknown): value is string {
  return typeof value === 'string' && /^[A-Za-z0-9_-]{32,128}$/.test(value);
}

export function sealOidcTransaction(transaction: OidcTransaction): string {
  return seal(transaction, 'oidc-transaction');
}

export function unsealOidcTransaction(value: string, now = Date.now()): OidcTransaction {
  const payload = unseal(value, 'oidc-transaction');
  if (
    !isRecord(payload)
    || payload.version !== 1
    || !isUrlSafeRandom(payload.state)
    || !isUrlSafeRandom(payload.nonce)
    || !isUrlSafeRandom(payload.codeVerifier)
    || typeof payload.returnTo !== 'string'
    || !payload.returnTo.startsWith('/')
    || payload.returnTo.startsWith('//')
    || typeof payload.expiresAt !== 'number'
    || !Number.isSafeInteger(payload.expiresAt)
    || payload.expiresAt <= now
  ) {
    throw new SessionCookieError('The OIDC transaction is invalid or expired.');
  }
  return payload as OidcTransaction;
}

export function sealWebSession(session: WebSession): string {
  const value = seal(session, 'web-session');
  if (value.length > MAX_SEALED_COOKIE_LENGTH) {
    throw new SessionCookieError('The access token is too large for a browser session cookie.');
  }
  return value;
}

export function unsealWebSession(value: string, now = Date.now()): WebSession {
  const payload = unseal(value, 'web-session');
  if (
    !isRecord(payload)
    || payload.version !== 1
    || typeof payload.accessToken !== 'string'
    || payload.accessToken.length === 0
    || /\s/.test(payload.accessToken)
    || typeof payload.expiresAt !== 'number'
    || !Number.isSafeInteger(payload.expiresAt)
    || payload.expiresAt <= now
  ) {
    throw new SessionCookieError();
  }
  return payload as WebSession;
}

export function parseBearerAuthorization(value: string | null): string | null {
  if (!value) return null;
  const match = /^Bearer ([A-Za-z0-9\-._~+/]+=*)$/i.exec(value);
  return match?.[1] ?? null;
}

export function constantTimeTextEqual(left: string, right: string): boolean {
  const leftBytes = Buffer.from(left, 'utf8');
  const rightBytes = Buffer.from(right, 'utf8');
  return leftBytes.length === rightBytes.length && timingSafeEqual(leftBytes, rightBytes);
}
