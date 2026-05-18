/**
 * Client-side auth utilities — token management and user context.
 *
 * JWT verification happens server-side; this module only decodes
 * the payload for UI display and route guards.
 *
 * Tokens are stored in BOTH localStorage (for client-side reads) and
 * a cookie (for Next.js middleware auth checks). The cookie name must
 * match what middleware.ts expects.
 */

const TOKEN_KEY = "aoe_auth_token";

export interface JWTPayload {
  sub: string;
  org_id: string;
  roles: string[];
  email?: string;
  name?: string;
  exp?: number;
  iat?: number;
}

export interface CurrentUser {
  userId: string;
  orgId: string;
  roles: string[];
  email: string;
  displayName: string;
}

function setCookie(name: string, value: string): void {
  const secure = window.location.protocol === "https:";
  let cookie = `${name}=${encodeURIComponent(value)}; path=/; SameSite=Lax`;
  if (secure) cookie += "; Secure";
  document.cookie = cookie;
}

function deleteCookie(name: string): void {
  document.cookie = `${name}=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT; SameSite=Lax`;
}

function getCookie(name: string): string | null {
  const match = document.cookie.match(
    new RegExp(`(?:^|;\\s*)${name}=([^;]*)`)
  );
  return match ? decodeURIComponent(match[1]) : null;
}

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY) ?? getCookie(TOKEN_KEY);
}

export function setToken(token: string): void {
  if (typeof window === "undefined") return;
  localStorage.setItem(TOKEN_KEY, token);
  setCookie(TOKEN_KEY, token);
}

export function clearToken(): void {
  if (typeof window === "undefined") return;
  localStorage.removeItem(TOKEN_KEY);
  deleteCookie(TOKEN_KEY);
}

export function parseToken(token: string): JWTPayload | null {
  try {
    const parts = token.split(".");
    if (parts.length !== 3) return null;

    const payload = parts[1];
    const decoded = atob(payload.replace(/-/g, "+").replace(/_/g, "/"));
    return JSON.parse(decoded) as JWTPayload;
  } catch {
    return null;
  }
}

export function isAuthenticated(): boolean {
  const token = getToken();
  if (!token) return false;

  const payload = parseToken(token);
  if (!payload) return false;

  if (payload.exp) {
    const nowSeconds = Math.floor(Date.now() / 1000);
    if (payload.exp < nowSeconds) {
      clearToken();
      return false;
    }
  }

  return true;
}

export function getCurrentUser(): CurrentUser | null {
  const token = getToken();
  if (!token) return null;

  const payload = parseToken(token);
  if (!payload) return null;

  if (payload.exp) {
    const nowSeconds = Math.floor(Date.now() / 1000);
    if (payload.exp < nowSeconds) {
      clearToken();
      return null;
    }
  }

  return {
    userId: payload.sub,
    orgId: payload.org_id,
    roles: payload.roles ?? [],
    email: payload.email ?? "",
    displayName: payload.name ?? "",
  };
}
