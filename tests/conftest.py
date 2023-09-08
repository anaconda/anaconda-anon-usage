from os import rename, remove
from os.path import exists, join

import pytest

from anaconda_anon_usage import tokens


@pytest.fixture
def aau_token_path():
    return join(tokens.CONFIG_DIR, "aau_token")


@pytest.fixture
def token_cleanup(request, aau_token_path):
    test_aau_token_path = aau_token_path + ".test"
    if exists(aau_token_path):
        rename(aau_token_path, test_aau_token_path)

    def _remove():
        try:
            remove(aau_token_path)
        except FileNotFoundError:
            pass
    request.addfinalizer(_remove)

    yield

    if exists(test_aau_token_path):
        rename(test_aau_token_path, aau_token_path)


def clear_cache():
    tokens.client_token.cache_clear()
    tokens.session_token.cache_clear()
    tokens.environment_token.cache_clear()
    tokens.all_tokens.cache_clear()
    tokens.token_string.cache_clear()


@pytest.fixture(autouse=True)
def client_token_string_cache_cleanup(request):
    request.addfinalizer(clear_cache)
