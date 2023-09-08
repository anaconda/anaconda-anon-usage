from os.path import exists

from anaconda_anon_usage import tokens


def test_client_token(token_cleanup, aau_token_path):
    assert not exists(aau_token_path)
    assert tokens.client_token() != ""
    assert exists(aau_token_path)


def test_environment_token_without_monkey_patching():
    assert tokens.environment_token() is not None


def test_environment_token_with_target_prefix(monkeypatch, tmpdir):
    assert tokens.environment_token(prefix=tmpdir) is not None


def test_token_string(token_cleanup):
    token_string = tokens.token_string()
    assert " c/" in token_string
    assert " s/" in token_string
    assert " e/" in token_string


def test_token_string_no_client_token(monkeypatch):
    monkeypatch.setattr(tokens, "environment_token", lambda prefix: "env_token")
    monkeypatch.setattr(tokens, "_saved_token", lambda fpath, what: "")

    token_string = tokens.token_string()
    assert " c/" not in token_string
    assert " s/" in token_string
    assert " e/env_token" in token_string


def test_token_string_no_environment_token(monkeypatch, token_cleanup):
    monkeypatch.setattr(tokens, "environment_token", lambda prefix: "")

    token_string = tokens.token_string()
    assert " c/" in token_string
    assert " s/" in token_string
    assert " e/" not in token_string
