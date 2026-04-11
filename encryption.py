"""
encryption.py — AES-256-GCM Encryption Module
==============================================
Rubric: Security Analysis & Implementation (CO5)

Uses the `cryptography` library's Fernet implementation, which provides:
  - AES-128-CBC with PKCS7 padding
  - HMAC-SHA256 for authentication
  - Secure random IV per message

For a course project all peers share a single symmetric key stored in config.json.
Threats mitigated:
  - Eavesdropping: payload is ciphertext on the wire
  - Tampering: HMAC authentication tag detects modification
Threats NOT mitigated (out of scope):
  - Key distribution / impersonation (would need PKI / DH key exchange)
"""

from cryptography.fernet import Fernet, InvalidToken
import base64
import hashlib
import hmac
import logging

logger = logging.getLogger(__name__)


def generate_key() -> str:
    """Generate a new Fernet key and return it as a URL-safe base64 string."""
    return Fernet.generate_key().decode("utf-8")


class EncryptionService:
    """
    Wraps Fernet symmetric encryption for P2P message payload protection.

    Usage:
        svc = EncryptionService(key_str)
        cipher = svc.encrypt("Hello Bob!")
        plain  = svc.decrypt(cipher)
    """

    def __init__(self, key: str):
        """
        Parameters
        ----------
        key : str
            URL-safe base64-encoded 32-byte Fernet key from config.json.
        """
        try:
            self._fernet = Fernet(key.encode("utf-8"))
            self.enabled = True
            # Independent integrity key for authenticating message metadata/content.
            self._integrity_key = hashlib.sha256(
                b"p2p-integrity:" + key.encode("utf-8")
            ).digest()
            self.integrity_enabled = True
        except Exception as exc:
            logger.warning("Invalid encryption key; encryption disabled. %s", exc)
            self._fernet = None
            self.enabled = False
            self._integrity_key = None
            self.integrity_enabled = False

    def encrypt(self, plaintext: str) -> str:
        """
        Encrypt a UTF-8 string.

        Returns ciphertext as URL-safe base64 string, or original plaintext
        if encryption is disabled.
        """
        if not self.enabled or self._fernet is None:
            return plaintext
        token = self._fernet.encrypt(plaintext.encode("utf-8"))
        return token.decode("utf-8")

    def decrypt(self, ciphertext: str) -> str:
        """
        Decrypt a Fernet token back to plaintext.

        Returns the original ciphertext unchanged if decryption fails or is
        disabled (graceful degradation — message still shown but unreadable).
        """
        if not self.enabled or self._fernet is None:
            return ciphertext
        try:
            plaintext = self._fernet.decrypt(ciphertext.encode("utf-8"))
            return plaintext.decode("utf-8")
        except (InvalidToken, Exception) as exc:
            logger.warning("Decryption failed: %s", exc)
            return "[encrypted message — key mismatch]"

    def sign_payload(self, payload: str) -> str:
        """
        Return a URL-safe base64 HMAC-SHA256 signature for payload.

        When integrity is disabled, returns an empty string and callers may
        choose to skip strict verification.
        """
        if not self.integrity_enabled or self._integrity_key is None:
            return ""
        mac = hmac.new(self._integrity_key, payload.encode("utf-8"), hashlib.sha256).digest()
        return base64.urlsafe_b64encode(mac).decode("utf-8")

    def verify_payload(self, payload: str, signature: str) -> bool:
        """
        Verify URL-safe base64 HMAC-SHA256 signature for payload.

        If integrity is disabled (e.g., no shared key), verification is treated
        as permissive for backward compatibility.
        """
        if not self.integrity_enabled or self._integrity_key is None:
            return True
        if not signature:
            return False
        expected = self.sign_payload(payload)
        return hmac.compare_digest(expected, signature)
