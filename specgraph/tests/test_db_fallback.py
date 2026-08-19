from specgraph.db import SQLITE_FALLBACK, _make_engine, _switch_sqlite


def test_switch_sqlite_rebinds_session(monkeypatch):
    from specgraph import config
    from specgraph import db as dbmod

    monkeypatch.setattr(config.settings, "database_url", "postgresql+psycopg://x:x@127.0.0.1:1/x")
    _switch_sqlite()
    assert config.settings.database_url == SQLITE_FALLBACK
    assert str(dbmod.engine.url).startswith("sqlite")
