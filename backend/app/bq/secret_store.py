"""Secrets of the Windows user that runs the app, kept in Windows Credential Manager (generic credentials, protected
with DPAPI for that Windows account, persisted on this machine only). Never written to the DB, logs or the frontend.

Only two items are stored: the OAuth client secret entered by the administrator and the user's OAuth refresh token.
Tests replace the store with an in-memory one via `set_store`.
"""
from __future__ import annotations

import sys

PREFIX = "DemandForecast/"
_MAX_BLOB = 2560          # CRED_MAX_CREDENTIAL_BLOB_SIZE


class SecretStoreError(Exception):
    pass


class MemoryStore:
    def __init__(self):
        self.items: dict[str, str] = {}

    def get(self, name: str) -> str | None:
        return self.items.get(name)

    def set(self, name: str, value: str) -> None:
        self.items[name] = value

    def delete(self, name: str) -> None:
        self.items.pop(name, None)


class WindowsCredentialStore:
    CRED_TYPE_GENERIC = 1
    CRED_PERSIST_LOCAL_MACHINE = 2
    ERROR_NOT_FOUND = 1168

    def __init__(self):
        import ctypes
        from ctypes import wintypes as wt

        class CREDENTIAL(ctypes.Structure):
            _fields_ = [("Flags", wt.DWORD), ("Type", wt.DWORD), ("TargetName", wt.LPWSTR), ("Comment", wt.LPWSTR),
                        ("LastWritten", wt.FILETIME), ("CredentialBlobSize", wt.DWORD),
                        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)), ("Persist", wt.DWORD),
                        ("AttributeCount", wt.DWORD), ("Attributes", ctypes.c_void_p), ("TargetAlias", wt.LPWSTR),
                        ("UserName", wt.LPWSTR)]
        self._ct = ctypes
        self._C = CREDENTIAL
        adv = ctypes.WinDLL("advapi32", use_last_error=True)
        self._write = adv.CredWriteW
        self._write.argtypes = [ctypes.POINTER(CREDENTIAL), wt.DWORD]
        self._write.restype = wt.BOOL
        self._read = adv.CredReadW
        self._read.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.POINTER(ctypes.POINTER(CREDENTIAL))]
        self._read.restype = wt.BOOL
        self._del = adv.CredDeleteW
        self._del.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD]
        self._del.restype = wt.BOOL
        self._free = adv.CredFree
        self._free.argtypes = [ctypes.c_void_p]

    def get(self, name: str) -> str | None:
        ct = self._ct
        p = ct.POINTER(self._C)()
        if not self._read(PREFIX + name, self.CRED_TYPE_GENERIC, 0, ct.byref(p)):
            err = ct.get_last_error()
            if err == self.ERROR_NOT_FOUND:
                return None
            raise SecretStoreError(f"CredReadW failed ({err})")
        try:
            c = p.contents
            return bytes(c.CredentialBlob[:c.CredentialBlobSize]).decode("utf-8")
        finally:
            self._free(p)

    def set(self, name: str, value: str) -> None:
        ct = self._ct
        blob = value.encode("utf-8")
        if len(blob) > _MAX_BLOB:
            raise SecretStoreError("secret too large for Windows Credential Manager")
        buf = (ct.c_ubyte * len(blob)).from_buffer_copy(blob)
        c = self._C()
        c.Type = self.CRED_TYPE_GENERIC
        c.TargetName = PREFIX + name
        c.Comment = "Demand Forecasting - BigQuery sign-in"
        c.CredentialBlobSize = len(blob)
        c.CredentialBlob = ct.cast(buf, ct.POINTER(ct.c_ubyte))
        c.Persist = self.CRED_PERSIST_LOCAL_MACHINE
        c.UserName = "DemandForecast"
        if not self._write(ct.byref(c), 0):
            raise SecretStoreError(f"CredWriteW failed ({ct.get_last_error()})")

    def delete(self, name: str) -> None:
        ct = self._ct
        if not self._del(PREFIX + name, self.CRED_TYPE_GENERIC, 0):
            err = ct.get_last_error()
            if err != self.ERROR_NOT_FOUND:
                raise SecretStoreError(f"CredDeleteW failed ({err})")


_store = None


def store():
    global _store
    if _store is None:
        _store = WindowsCredentialStore() if sys.platform == "win32" else MemoryStore()
    return _store


def set_store(s) -> None:
    """Tests inject a MemoryStore (or None to go back to the real store)."""
    global _store
    _store = s
