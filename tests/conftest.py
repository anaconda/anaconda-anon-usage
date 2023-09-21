from os import remove
from os.path import join

import pytest
from conda.base.context import Context

from anaconda_anon_usage import tokens, utils


@pytest.fixture
def aau_token_path():
    return join(tokens.CONFIG_DIR, "aau_token")


@pytest.fixture(autouse=True)
def token_cleanup(request, aau_token_path):
    def _remove():
        try:
            remove(aau_token_path)
        except FileNotFoundError:
            pass

    request.addfinalizer(_remove)


@pytest.fixture(autouse=True)
def client_token_string_cache_cleanup(request):
    request.addfinalizer(utils._cache_clear)


@pytest.fixture(autouse=True)
def reset_patch(request):
    def _resetter():
        from conda.cli import install as cli_install

        for container, name, old_value in (
            (Context, "user_agent", Context._old_user_agent),
            (Context, "_aau_initialized", None),
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
            (Context, "checked_prefix", None),
            (cli_install, "check_prefix", getattr(Context, "_old_check_prefix", None)),
        ):
            if hasattr(container, name):
                delattr(container, name)
            if old_value is None:
                continue
            setattr(container, name, old_value)

    request.addfinalizer(_resetter)
