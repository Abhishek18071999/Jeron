"""Login secrets for the web app (spec section 9: password + TOTP).

The web app checks the login; this module only makes what goes in `.env`, through
`python -m app.cli auth-setup`: an scrypt hash of the password and a TOTP secret for an
authenticator app. `web/src/lib/auth.ts` reads the same formats. The hash has no `$`,
so Docker Compose leaves it alone in `.env`. Pure: no database.
"""

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

# scrypt cost: about 16 MB and a few tens of milliseconds per check.
SCRYPT_N, SCRYPT_R, SCRYPT_P = 16384, 8, 1
TOTP_STEP = 30
TOTP_DIGITS = 6
MIN_PASSWORD = 10


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, maxmem=64 * 2**20, dklen=32)


def hash_password(password: str, salt: bytes | None = None) -> str:
    """`scrypt:N:r:p:salt:hash`, salt and hash in unpadded base64url."""
    salt = salt or secrets.token_bytes(16)
    key = _scrypt(password, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P)
    return f"scrypt:{SCRYPT_N}:{SCRYPT_R}:{SCRYPT_P}:{_b64(salt)}:{_b64(key)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        kind, n, r, p, salt, key = stored.split(":")
        if kind != "scrypt":
            return False
        found = _scrypt(password, _unb64(salt), int(n), int(r), int(p))
    except ValueError:
        return False
    return hmac.compare_digest(found, _unb64(key))


def new_totp_secret() -> str:
    """160 random bits in base32, the form authenticator apps take."""
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def totp(secret: str, at: float | None = None, digits: int = TOTP_DIGITS) -> str:
    """RFC 6238 code (HMAC-SHA1, 30-second steps)."""
    key = base64.b32decode(secret.upper() + "=" * (-len(secret) % 8))
    step = int((time.time() if at is None else at) // TOTP_STEP)
    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(code % 10**digits).zfill(digits)


def otpauth_uri(secret: str, account: str = "Jeron", issuer: str = "Jeron") -> str:
    """What an authenticator app reads from a QR code, or the key typed in by hand."""
    return (
        f"otpauth://totp/{quote(issuer)}:{quote(account)}"
        f"?secret={secret}&issuer={quote(issuer)}&algorithm=SHA1&digits={TOTP_DIGITS}"
        f"&period={TOTP_STEP}"
    )
