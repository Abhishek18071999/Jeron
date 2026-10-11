// The single-user login (spec section 9): a password checked against an scrypt hash
// and a 6-digit code from an authenticator app (TOTP). Both come from .env, made by
// `python -m app.cli auth-setup` (backend/app/auth.py writes the same formats).
// A session is a signed cookie; its key is derived from the hash and the TOTP secret,
// so changing either logs out every device.
import { createHash, createHmac, scryptSync, timingSafeEqual } from "node:crypto";

export const SESSION_COOKIE = "jeron_session";
export const SESSION_DAYS = 30;

export type LoginConfig =
  | { mode: "off" }
  | { mode: "unset" }
  | { mode: "on"; passwordHash: string; totpSecret: string };

export function loginConfig(): LoginConfig {
  if (process.env.JERON_LOGIN_DISABLED === "true") return { mode: "off" };
  const passwordHash = process.env.JERON_LOGIN_PASSWORD_HASH?.trim() ?? "";
  const totpSecret = process.env.JERON_LOGIN_TOTP_SECRET?.trim() ?? "";
  if (!passwordHash || !totpSecret) return { mode: "unset" };
  return { mode: "on", passwordHash, totpSecret };
}

const same = (a: Buffer, b: Buffer) => a.length === b.length && timingSafeEqual(a, b);

export function verifyPassword(password: string, stored: string): boolean {
  const parts = stored.split(":");
  if (parts.length !== 6 || parts[0] !== "scrypt") return false;
  const [, n, r, p, salt, key] = parts;
  const expected = Buffer.from(key, "base64url");
  try {
    const found = scryptSync(password, Buffer.from(salt, "base64url"), expected.length, {
      N: Number(n),
      r: Number(r),
      p: Number(p),
      maxmem: 64 * 1024 * 1024,
    });
    return same(found, expected);
  } catch {
    return false;
  }
}

function base32(secret: string): Buffer {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let bits = "";
  for (const c of secret.toUpperCase().replace(/=+$/, "")) {
    const v = alphabet.indexOf(c);
    if (v < 0) throw new Error("bad base32");
    bits += v.toString(2).padStart(5, "0");
  }
  const bytes = [];
  for (let i = 0; i + 8 <= bits.length; i += 8) bytes.push(parseInt(bits.slice(i, i + 8), 2));
  return Buffer.from(bytes);
}

// RFC 6238: HMAC-SHA1, 30-second steps, 6 digits.
export function totp(secret: string, step: number): string {
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(step));
  const digest = createHmac("sha1", base32(secret)).update(counter).digest();
  const offset = digest[digest.length - 1] & 0x0f;
  const code = (digest.readUInt32BE(offset) & 0x7fffffff) % 1_000_000;
  return String(code).padStart(6, "0");
}

// One step either side for a phone clock that is a little off. A code that worked once
// is not accepted again.
let lastStep = 0;

export function verifyTotp(secret: string, code: string, now = Date.now()): boolean {
  const clean = code.replace(/\s/g, "");
  if (!/^\d{6}$/.test(clean)) return false;
  const step = Math.floor(now / 1000 / 30);
  for (const s of [step - 1, step, step + 1]) {
    if (s > lastStep && same(Buffer.from(totp(secret, s)), Buffer.from(clean))) {
      lastStep = s;
      return true;
    }
  }
  return false;
}

// Five wrong tries lock the login for 15 minutes.
const MAX_FAILURES = 5;
const LOCK_MS = 15 * 60 * 1000;
let failures = 0;
let lockedUntil = 0;

export function lockedFor(now = Date.now()): number {
  return Math.max(0, lockedUntil - now);
}

export function recordFailure(now = Date.now()) {
  failures += 1;
  if (failures >= MAX_FAILURES) {
    lockedUntil = now + LOCK_MS;
    failures = 0;
  }
}

export function recordSuccess() {
  failures = 0;
}

function sessionKey(config: { passwordHash: string; totpSecret: string }): Buffer {
  return createHash("sha256").update(`jeron-session|${config.passwordHash}|${config.totpSecret}`).digest();
}

const sign = (key: Buffer, expires: number) =>
  createHmac("sha256", key).update(`v1.${expires}`).digest("base64url");

export function newSession(config: { passwordHash: string; totpSecret: string }, now = Date.now()) {
  const expires = Math.floor(now / 1000) + SESSION_DAYS * 24 * 3600;
  return `v1.${expires}.${sign(sessionKey(config), expires)}`;
}

export function validSession(
  token: string | undefined,
  config: { passwordHash: string; totpSecret: string },
  now = Date.now(),
): boolean {
  if (!token) return false;
  const [version, expires, signature] = token.split(".");
  const at = Number(expires);
  if (version !== "v1" || !Number.isInteger(at) || at * 1000 < now || !signature) return false;
  return same(Buffer.from(signature), Buffer.from(sign(sessionKey(config), at)));
}
