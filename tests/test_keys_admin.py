"""Tests for the API key admin command."""

import pytest

from src import keys_admin
from src.core.api_keys import KeyStore


@pytest.fixture
def database(tmp_path):
    return str(tmp_path / "keys.sqlite3")


def run(capsys, database, *args):
    code = keys_admin.main(["--database", database, *args])
    out = capsys.readouterr()
    return code, out.out, out.err


def test_issue_prints_a_working_key_once(capsys, database):
    code, out, _ = run(capsys, database, "issue", " Ada@Example.com ")
    key = out.strip().splitlines()[-1]
    assert code == 0
    assert "for ada@example.com" in out
    assert KeyStore(database).authenticate(key) is not None


def test_list_shows_prefixes_but_never_keys(capsys, database):
    _, issued, _ = run(capsys, database, "issue", "ada@example.com")
    key = issued.strip().splitlines()[-1]
    code, out, _ = run(capsys, database, "list")
    assert code == 0
    assert key[:12] in out
    assert key not in out
    assert "active" in out and "1 key(s)" in out


def test_list_filters_by_email_or_prefix(capsys, database):
    run(capsys, database, "issue", "ada@example.com")
    run(capsys, database, "issue", "grace@example.com")
    _, out, _ = run(capsys, database, "list", "grace")
    assert "grace@example.com" in out and "ada@example.com" not in out


def test_revoke_stops_a_key(capsys, database):
    _, issued, _ = run(capsys, database, "issue", "ada@example.com")
    key = issued.strip().splitlines()[-1]
    key_id = KeyStore(database).find("ada")[0].id
    assert run(capsys, database, "revoke", str(key_id))[0] == 0
    assert KeyStore(database).authenticate(key) is None
    code, _, err = run(capsys, database, "revoke", str(key_id))
    assert code == 1 and "No active key" in err


def test_reads_the_database_from_the_environment(capsys, database, monkeypatch):
    monkeypatch.setenv("API_KEY_DATABASE", database)
    assert keys_admin.main(["issue", "ada@example.com"]) == 0
    assert KeyStore(database).find("ada")


def test_needs_a_database(monkeypatch):
    monkeypatch.delenv("API_KEY_DATABASE", raising=False)
    with pytest.raises(SystemExit):
        keys_admin.main(["list"])


def test_rejects_an_invalid_email(capsys, database):
    with pytest.raises(SystemExit):
        keys_admin.main(["--database", database, "issue", "not-an-email"])
