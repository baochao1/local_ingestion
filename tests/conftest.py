"""Shared pytest bootstrap (imported before any test module).

Several platform services validate ``CREDENTIAL_ENCRYPTION_KEY`` on first use,
and a number of test modules build the FastAPI app at import time. Without a
default the whole suite fails with ``ConfigurationError`` depending on whether
the developer happens to have a local ``.env``, so every module grew its own
``os.environ.setdefault`` copy (6 duplicates and counting). Centralise it here.

The value is a throwaway base64 32-byte key used only by tests — never a
production secret.
"""
from __future__ import annotations

import os

os.environ.setdefault(
    "CREDENTIAL_ENCRYPTION_KEY",
    "6bDIB9Fe9Wuxj51Hreoyxj8hEGZaeSbHGBlxl77er0s=",
)
