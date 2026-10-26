"""Gilt für alle Tests (Integration und Add-on)."""

from __future__ import annotations

import sys

import pytest_socket

if sys.platform == "win32":
    # Nur für lokale Läufe unter Windows: Dessen Ereignisschleife legt ein lokales Socket-Paar an,
    # das die Socket-Sperre des Test-Plugins sonst blockiert. Unter Linux (CI) bleibt die Sperre aktiv.
    pytest_socket.disable_socket = lambda *args, **kwargs: None
