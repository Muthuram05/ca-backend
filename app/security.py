import base64
import hashlib
import hmac
import json

from cryptography.fernet import Fernet, InvalidToken


class TokenCipher:
    """Encrypts Instagram access tokens before they are stored in the database."""

    def __init__(self, key: str):
        self._fernet = Fernet(key.encode())

    def encrypt(self, token: str) -> str:
        return self._fernet.encrypt(token.encode()).decode()

    def decrypt(self, value: str) -> str:
        try:
            return self._fernet.decrypt(value.encode()).decode()
        except InvalidToken as exc:
            raise ValueError("Stored access token could not be decrypted (wrong TOKEN_ENCRYPTION_KEY?)") from exc


def verify_webhook_signature(app_secret: str, body: bytes, header: str | None) -> bool:
    """Checks Meta's X-Hub-Signature-256 header."""
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))


def _b64url_decode(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def parse_signed_request(app_secret: str, signed_request: str) -> dict | None:
    """Decodes the signed_request Meta sends to deauthorize / data-deletion callbacks."""
    try:
        encoded_sig, payload = signed_request.split(".", 1)
        sig = _b64url_decode(encoded_sig)
        data = json.loads(_b64url_decode(payload))
    except (ValueError, json.JSONDecodeError):
        return None
    expected = hmac.new(app_secret.encode(), payload.encode(), hashlib.sha256).digest()
    if not hmac.compare_digest(sig, expected):
        return None
    return data
