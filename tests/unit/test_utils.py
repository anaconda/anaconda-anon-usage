from os.path import exists, isdir

import pytest

from anaconda_anon_usage import utils


@pytest.mark.parametrize(
    "toggle,out,err",
    [(True, "", "debug testing\n"), (False, "", "")],
)
def test_debug(monkeypatch, capsys, toggle, out, err):
    monkeypatch.setattr(utils, "DEBUG", toggle)
    utils._debug("debug %s", "testing")
    captured = capsys.readouterr()
    assert captured.out == out
    assert captured.err == err


def test_random_token():
    assert utils._random_token() != utils._random_token()
    assert len(utils._random_token()) == 22


def test_saved_token_saving(tmpdir):
    token_path = tmpdir.join("aau_token")
    token_saved = utils._saved_token(token_path, "test")
    assert len(token_saved) == 22
    token_stored = utils._read_file(token_path, "test", read_only=True)
    assert token_stored and token_stored == token_saved


def test_saved_token_newline(monkeypatch, tmpdir):
    monkeypatch.setattr(utils, "WRITE_NEWLINE", True)
    token_path = tmpdir.join("aau_token")
    token_saved = utils._saved_token(token_path, "test")
    assert len(token_saved) == 22
    token_stored = utils._read_file(token_path, "test", read_only=True)
    assert token_stored and token_stored != token_saved
    assert token_stored.splitlines()[0] == token_saved
    token_stored = utils._read_file(
        token_path, "test", read_only=True, single_line=True
    )
    assert token_stored and token_stored == token_saved


def test_saved_token_exception(tmpdir):
    token_path = tmpdir.join("aau_token")
    # setting this up as a directory to trigger the exists
    token_path.mkdir()
    token_value = utils._saved_token(token_path, "test")
    assert not token_value
    assert exists(token_path)
    assert isdir(token_path)
    assert token_value == ""


def test_read_chaos(monkeypatch, tmpdir):
    token_path = tmpdir.join("aau_token")
    token1 = utils._saved_token(token_path, "environment")
    assert token1
    monkeypatch.setattr(utils, "READ_CHAOS", "e")
    token2 = utils._saved_token(token_path, "environment")
    assert token2 and token1 != token2
    monkeypatch.setattr(utils, "READ_CHAOS", "")
    token3 = utils._saved_token(token_path, "environment")
    assert token3 == token2


def test_write_chaos(monkeypatch, tmpdir):
    token_path = tmpdir.join("aau_token")
    monkeypatch.setattr(utils, "WRITE_CHAOS", "e")
    token1 = utils._saved_token(token_path, "environment")
    assert not token1 and not token_path.exists()
    monkeypatch.setattr(utils, "WRITE_CHAOS", "")
    token2 = utils._saved_token(token_path, "environment")
    assert token2 and token_path.exists()
    monkeypatch.setattr(utils, "WRITE_CHAOS", "e")
    token3 = utils._saved_token(token_path, "environment")
    assert token3 == token2


def test_saved_token_existing_short(tmpdir):
    token_path = tmpdir.join("aau_token")
    # setting a token up that is shorter than the random ones
    token_path.write_text("sh0rty", "utf-8")
    token_saved = utils._saved_token(token_path, "test")
    assert exists(token_path)
    assert token_saved != ""
    assert len(token_saved) == 22


def test_saved_token_existing_long(tmpdir):
    token_path = tmpdir.join("aau_token")
    # setting a token up that is longer than the random ones
    longer_token = "c" * 23
    token_path.write_text(longer_token, "utf-8")
    token_saved = utils._saved_token(token_path, "test")
    assert exists(token_path)
    assert token_saved == longer_token
    assert len(token_saved) == 23


def test_return_deferred_token(tmpdir):
    """
    Tests that utils_saved_token will return the token
    if it is in a deferred write state instead of creating a new one.
    """

    token_path = tmpdir.join("aau_token")
    token1 = utils._saved_token(token_path, "test", token_path)
    token2 = utils._saved_token(token_path, "test", token_path)
    assert token1 == token2
