from argparse import Namespace
from os import remove
from os.path import exists, expanduser, isdir, join

import pytest
from conda.base.context import Context, context

from anaconda_anon_usage import patch

CONDA_CONFIG_DIR = expanduser("~/.conda")
AAU_TOKEN_PATH = join(CONDA_CONFIG_DIR, "aau_token")


def remove_token():
    remove(AAU_TOKEN_PATH)


def clear_cache():
    patch.client_token_string.cache_clear()


@pytest.fixture(autouse=True)
def client_token_string_cache_cleanup(request):
    request.addfinalizer(clear_cache)


@pytest.fixture
def token_cleanup(request):
    request.addfinalizer(remove_token)


def test_get_random_token():
    assert patch.get_random_token() != patch.get_random_token()
    assert len(patch.get_random_token()) == 22


def test_get_saved_token_saving(tmpdir):
    token_path = tmpdir.join("aau_token")
    token_saved = patch.get_saved_token(token_path, "test")
    assert exists(token_path)
    with open(token_path) as token_file:
        token_stored = token_file.read()
        assert len(token_stored) == 22
        assert token_stored == token_saved


def test_get_saved_token_exception(tmpdir):
    token_path = tmpdir.join("aau_token")
    # setting this up as a directory to trigger the exists
    token_path.mkdir()
    token_saved = patch.get_saved_token(token_path, "test")
    assert exists(token_path)
    assert isdir(token_path)
    assert token_saved == ""


def test_get_saved_token_existing_short(tmpdir):
    token_path = tmpdir.join("aau_token")
    # setting a token up that is shorter than the random ones
    token_path.write_text("shorty", "utf-8")
    token_saved = patch.get_saved_token(token_path, "test")
    assert exists(token_path)
    assert token_saved != ""
    assert len(token_saved) == 22


def test_get_saved_token_existing_long(tmpdir, token_cleanup):
    token_path = tmpdir.join("aau_token")
    # setting a token up that is longer than the random ones
    longer_token = "c" * 23
    token_path.write_text(longer_token, "utf-8")
    token_saved = patch.get_saved_token(token_path, "test")
    assert exists(token_path)
    assert token_saved == longer_token
    assert len(token_saved) == 23


def test_get_client_token(token_cleanup):
    assert not exists(AAU_TOKEN_PATH)
    assert patch.get_client_token() != ""
    assert exists(AAU_TOKEN_PATH)


def test_get_environment_token_without_monkey_patching():
    assert patch.get_environment_token() is not None


def test_get_environment_token_with_target_prefix(monkeypatch, tmpdir):
    monkeypatch.setattr(context, "_argparse_args", Namespace(prefix=tmpdir))
    assert patch.get_environment_token() is None


def test_client_token_string(token_cleanup):
    token_string = patch.client_token_string()
    assert " c/" in token_string
    assert " s/" in token_string
    assert " e/" in token_string


def test_client_token_string_no_client_token(monkeypatch):
    monkeypatch.setattr(patch, "get_saved_token", lambda fpath, what: "")
    monkeypatch.setattr(patch, "get_environment_token", lambda: "env_token")

    token_string = patch.client_token_string()
    assert " c/" not in token_string
    assert " s/" in token_string
    assert " e/env_token" in token_string


def test_client_token_string_no_environment_token(monkeypatch, token_cleanup):
    monkeypatch.setattr(patch, "get_environment_token", lambda: "")

    token_string = patch.client_token_string()
    assert " c/" in token_string
    assert " s/" in token_string
    assert " e/" not in token_string


@pytest.fixture
def reset_patch(request):
    def resetter():
        from conda.cli import install as cli_install

        for container, name, old_value in (
            (Context, "user_agent", Context._old_user_agent),
            (Context, "anaconda_anon_usage", None),
            (
                Context,
                "parameter_names",
                tuple(
                    filter(
                        lambda name: name != "anaconda_anon_usage",
                        Context.parameter_names,
                    )
                ),
            ),
            (context, "checked_prefix", None),
            (cli_install, "check_prefix", context._old_check_prefix),
        ):
            if hasattr(container, name):
                delattr(container, name)
            if old_value is None:
                continue
            setattr(container, name, old_value)

    request.addfinalizer(resetter)


def test_new_user_agent(reset_patch):
    with pytest.raises(AttributeError, match="_old_user_agent"):
        assert patch._new_user_agent(context) is not None
    patch.main(plugin=True)
    assert patch._new_user_agent(context) is not None


def test_new_user_agent_no_token(monkeypatch, reset_patch):
    monkeypatch.setattr(patch, "client_token_string", lambda: "")
    patch.main(plugin=True)
    assert patch._new_user_agent(context) is not None


def test_main_already_patched(monkeypatch, reset_patch):
    monkeypatch.setattr(Context, "_old_user_agent", "test", raising=False)
    assert not hasattr(Context, "anaconda_anon_usage")
