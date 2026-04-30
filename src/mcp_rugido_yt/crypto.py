"""Wrapper Fernet para criptografia at-rest dos refresh tokens."""

from cryptography.fernet import Fernet

from mcp_rugido_yt.config import get_settings

_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        key = get_settings().fernet_key.encode()
        _fernet = Fernet(key)
    return _fernet


def encrypt(plaintext: str) -> bytes:
    return _get_fernet().encrypt(plaintext.encode())


def decrypt(ciphertext: bytes) -> str:
    return _get_fernet().decrypt(ciphertext).decode()
