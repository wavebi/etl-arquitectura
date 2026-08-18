"""Configuración de pytest: hace importable `src/` como si estuviera instalado.

También aísla los tests del `.env` real: sin esto, un `.env` con credenciales de
producción en la máquina del dev cambiaría el resultado de los tests.
"""

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))


@pytest.fixture(autouse=True)
def _isolate_settings(monkeypatch):
    """Fuerza valores de test en settings, sin importar el entorno de la máquina."""
    from shared.settings import settings

    monkeypatch.setattr(settings, "ENV", "dev")
    monkeypatch.setattr(settings, "APP_NAME", "etl-arquitectura-test")
