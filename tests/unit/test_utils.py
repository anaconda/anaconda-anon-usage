import importlib
from os.path import exists, isdir

from anaconda_anon_usage import utils


def test_debug_disabled(capsys, monkeypatch):
    monkeypatch.setenv("ANACONDA_ANON_USAGE_DEBUG", "false")
    utils._debug("debug %s", "testing")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_debug_enabled(monkeypatch, capsys):
    monkeypatch.setattr(utils, "DEBUG", True)
    utils._debug("debug %s", "testing")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "debug testing\n"


def test_debug_enabled_envvar(monkeypatch, capsys):
    monkeypatch.setenv("ANACONDA_ANON_USAGE_DEBUG", "true")
    importlib.reload(utils)
    utils._debug("debug %s", "testing")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "debug testing\n"


def test_random_token():
    assert utils._random_token() != utils._random_token()
    assert len(utils._random_token()) == 22


def test_saved_token_saving(tmpdir):
    token_path = tmpdir.join("aau_token")
    token_saved = utils._saved_token(token_path, "test")
    assert exists(token_path)
    with open(token_path) as token_file:
        token_stored = token_file.read()
        assert len(token_stored) == 22
        assert token_stored == token_saved


def test_saved_token_exception(tmpdir):
    token_path = tmpdir.join("aau_token")
    # setting this up as a directory to trigger the exists
    token_path.mkdir()
    token_saved = utils._saved_token(token_path, "test")
    assert exists(token_path)
    assert isdir(token_path)
    assert token_saved == ""


def test_saved_token_existing_short(tmpdir):
    token_path = tmpdir.join("aau_token")
    # setting a token up that is shorter than the random ones
    token_path.write_text("sh0rty", "utf-8")
    token_saved = utils._saved_token(token_path, "test")
    assert exists(token_path)
    assert token_saved != ""
    assert len(token_saved) == 22


def test_saved_token_existing_long(tmpdir, token_cleanup):
    token_path = tmpdir.join("aau_token")
    # setting a token up that is longer than the random ones
    longer_token = "c" * 23
    token_path.write_text(longer_token, "utf-8")
    token_saved = utils._saved_token(token_path, "test")
    assert exists(token_path)
    assert token_saved == longer_token
    assert len(token_saved) == 23
