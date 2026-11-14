"""One explicitly authorized DeepSeek credential, protected by Windows DPAPI.

Only the current Windows user's DPAPI scope is used. No credential discovery,
logging, UI prompts, plaintext files, or third-party packages are involved.
"""

import ctypes
import os
from pathlib import Path
import tempfile


class CredentialError(RuntimeError):
    """A fixed safe message; never includes a key or underlying OS exception."""


_FORMAT = b"LedgerGRPO:DeepSeek:v1\x00"
_UI_FORBIDDEN = 0x1


def _validated_key(key):
    if not isinstance(key, str) or not key.isascii():
        raise CredentialError("API key must be nonempty printable ASCII.")
    normalized = key.strip()
    if not normalized or any(ord(char) < 32 or ord(char) == 127 for char in normalized):
        raise CredentialError("API key must be nonempty printable ASCII.")
    return normalized


def _path(path):
    try:
        if path is not None:
            return Path(path)
        base = os.environ.get("LOCALAPPDATA")
        if not base or not Path(base).is_absolute():
            raise ValueError
        return Path(base) / "LedgerGRPO" / "deepseek-key.dpapi"
    except Exception:
        raise CredentialError("Credential storage location is unavailable.") from None


def _crypt(data, *, decrypt):
    if os.name != "nt":
        raise CredentialError("Windows user-scoped credential protection is unavailable.")
    from ctypes import wintypes

    class DataBlob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]

    crypt32 = ctypes.WinDLL("crypt32.dll", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32.dll", use_last_error=True)
    crypt32.CryptProtectData.argtypes = [ctypes.POINTER(DataBlob), wintypes.LPCWSTR,
                                        ctypes.POINTER(DataBlob), ctypes.c_void_p,
                                        ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DataBlob)]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    crypt32.CryptUnprotectData.argtypes = [ctypes.POINTER(DataBlob), ctypes.POINTER(wintypes.LPWSTR),
                                          ctypes.POINTER(DataBlob), ctypes.c_void_p,
                                          ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DataBlob)]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    buffer = ctypes.create_string_buffer(data, len(data))
    incoming = DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    outgoing = DataBlob()
    operation = crypt32.CryptUnprotectData if decrypt else crypt32.CryptProtectData
    try:
        # No LOCAL_MACHINE flag: only the current user's DPAPI scope is allowed.
        # Description, entropy, reserved pointer and prompt structure stay NULL.
        success = operation(ctypes.byref(incoming), None, None, None, None,
                            _UI_FORBIDDEN, ctypes.byref(outgoing))
        if not success or not outgoing.pbData or not outgoing.cbData:
            raise CredentialError("Credential protection operation failed.")
        return ctypes.string_at(outgoing.pbData, outgoing.cbData)
    finally:
        ctypes.memset(ctypes.addressof(buffer), 0, len(buffer))
        if outgoing.pbData:
            ctypes.memset(outgoing.pbData, 0, outgoing.cbData)
            kernel32.LocalFree(ctypes.cast(outgoing.pbData, ctypes.c_void_p))


def save_deepseek_key(key, path=None):
    """Encrypt and atomically replace this one credential; return None.

    ``path`` is only an explicit storage override, useful for isolated tests.
    The default is LOCALAPPDATA/LedgerGRPO/deepseek-key.dpapi.
    """
    normalized = _validated_key(key)
    target = _path(path)
    temporary = None
    try:
        ciphertext = _crypt(_FORMAT + normalized.encode("ascii"), decrypt=False)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=".deepseek-key-", suffix=".tmp", dir=target.parent)
        temporary = Path(name)
        with os.fdopen(fd, "wb") as stream:
            stream.write(ciphertext)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        temporary = None
    except Exception:
        raise CredentialError("Unable to save the protected credential.") from None
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def load_deepseek_key(path=None):
    """Return the saved key, None if absent, or a safe CredentialError.

    Corrupted, inaccessible, foreign-user or foreign-format files are errors;
    they are never silently treated as an absent credential.
    """
    target = _path(path)
    try:
        ciphertext = target.read_bytes()
    except FileNotFoundError:
        return None
    except Exception:
        raise CredentialError("Unable to read the protected credential.") from None
    try:
        if not ciphertext:
            raise ValueError
        plaintext = _crypt(ciphertext, decrypt=True)
        if not plaintext.startswith(_FORMAT):
            raise ValueError
        return _validated_key(plaintext[len(_FORMAT):].decode("ascii"))
    except Exception:
        raise CredentialError("Unable to decrypt the protected credential.") from None
