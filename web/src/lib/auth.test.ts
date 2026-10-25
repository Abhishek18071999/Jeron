// The login's checks (src/lib/auth.ts), run with `npm test` (Node's own test runner).
// The hash and codes were made by the backend (backend/app/auth.py), so both sides
// read the same formats.
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  lockedFor,
  newSession,
  recordFailure,
  recordSuccess,
  safeNext,
  totp,
  validSession,
  verifyPassword,
  verifyTotp,
} from "./auth.ts";

// hash_password("correct horse battery", salt=b"0123456789abcdef")
const HASH = "scrypt:16384:8:1:MDEyMzQ1Njc4OWFiY2RlZg:ebnHHTApWa0oNoXTYCCHxLXDaejcvcTRQhZaD1OJNCE";
const config = { passwordHash: HASH, totpSecret: "JBSWY3DPEHPK3PXP" };

test("the password is checked against the backend's scrypt hash", () => {
  assert.equal(verifyPassword("correct horse battery", HASH), true);
  assert.equal(verifyPassword("correct horse batter", HASH), false);
  assert.equal(verifyPassword("", HASH), false);
  assert.equal(verifyPassword("correct horse battery", HASH.replace("scrypt", "bcrypt")), false);
  assert.equal(verifyPassword("correct horse battery", "scrypt:16384:8:1"), false);
  assert.equal(verifyPassword("correct horse battery", "scrypt:0:8:1:AA:AA"), false);
});

test("TOTP codes match RFC 6238 and the backend", () => {
  // RFC 6238 appendix B, SHA-1 secret "12345678901234567890", last 6 of 8 digits.
  const rfc = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ";
  assert.equal(totp(rfc, Math.floor(59 / 30)), "287082");
  assert.equal(totp(rfc, Math.floor(1111111109 / 30)), "081804");
  assert.equal(totp(rfc, Math.floor(2000000000 / 30)), "279037");
  // backend: totp("JBSWY3DPEHPK3PXP", at=1_700_000_000)
  assert.equal(totp(config.totpSecret, Math.floor(1_700_000_000 / 30)), "324550");
});

test("a code works within one step either side, and only once", () => {
  const now = 1_800_000_000_000;
  const step = Math.floor(now / 1000 / 30);
  assert.equal(verifyTotp(config.totpSecret, "12345", now), false);
  assert.equal(verifyTotp(config.totpSecret, "abcdef", now), false);
  assert.equal(verifyTotp(config.totpSecret, totp(config.totpSecret, step + 2), now), false);
  const code = totp(config.totpSecret, step - 1);
  assert.equal(verifyTotp(config.totpSecret, `${code.slice(0, 3)} ${code.slice(3)}`, now), true);
  assert.equal(verifyTotp(config.totpSecret, code, now), false); // replayed
  assert.equal(verifyTotp(config.totpSecret, totp(config.totpSecret, step), now), true);
});

test("five failures lock the login for 15 minutes", () => {
  const now = 1_900_000_000_000;
  recordSuccess();
  for (let i = 0; i < 4; i++) recordFailure(now);
  assert.equal(lockedFor(now), 0);
  recordFailure(now);
  assert.equal(lockedFor(now), 15 * 60 * 1000);
  assert.equal(lockedFor(now + 15 * 60 * 1000), 0);
});

test("sessions are signed, expire, and end when the secrets change", () => {
  const now = 1_700_000_000_000;
  const token = newSession(config, now);
  assert.equal(validSession(token, config, now), true);
  assert.equal(validSession(token, config, now + 29 * 24 * 3600 * 1000), true);
  assert.equal(validSession(token, config, now + 31 * 24 * 3600 * 1000), false);
  assert.equal(validSession(token, { ...config, totpSecret: "KRSXG5CTMVRXEZLU" }, now), false);
  assert.equal(validSession(undefined, config, now), false);
  const [v, expires, sig] = token.split(".");
  assert.equal(validSession(`${v}.${Number(expires) + 3600}.${sig}`, config, now), false); // forged expiry
  assert.equal(validSession(`v2.${expires}.${sig}`, config, now), false);
  assert.equal(validSession(`${v}.${expires}.`, config, now), false);
});

test("after login, only a path inside Jeron", () => {
  assert.equal(safeNext("/journal?signal=1"), "/journal?signal=1");
  assert.equal(safeNext("/stocks/M%26M"), "/stocks/M%26M");
  for (const bad of [
    "https://evil.com",
    "//evil.com",
    "/\\evil.com",
    "/\\/evil.com",
    "/\t/evil.com",
    "/\n/evil.com",
    "evil.com",
    "",
  ]) {
    assert.equal(safeNext(bad), "/", JSON.stringify(bad));
  }
});
