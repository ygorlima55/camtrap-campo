import pytest

from camtrap_campo.db import conectar


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    """Banco e pasta Dados isolados por teste."""
    monkeypatch.setenv("CAMTRAP_DADOS", str(tmp_path / "Dados"))
    monkeypatch.setenv("CAMTRAP_BANCO", str(tmp_path / "banco.sqlite3"))
    return {"fabrica": conectar(tmp_path / "banco.sqlite3"), "dados": tmp_path / "Dados", "tmp": tmp_path}
