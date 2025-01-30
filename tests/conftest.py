import tempfile
from os import remove
from os.path import join

import pytest
from conda.base import constants as c_constants
from conda.base.context import Context, context

from anaconda_anon_usage import tokens, utils


@pytest.fixture
def aau_token_path():
    return join(tokens.CONFIG_DIR, "aau_token")


@pytest.fixture
def system_tokens():
    with tempfile.TemporaryDirectory() as tname:
        tname = tname.replace("\\", "/")
        o_path = c_constants.SEARCH_PATH
        n_path = (
            "/tmp/fake/condarc.d/",
            tname + "/.condarc",
            tname + "/condarc",
            tname + "/condarc.d/",
        )
        c_constants.SEARCH_PATH = n_path + o_path
        otoken = utils._random_token()
        mtoken = utils._random_token()
        with open(tname + "/org_token", "w") as fp:
            fp.write(otoken)
        with open(tname + "/machine_token", "w") as fp:
            fp.write(mtoken)
        yield (otoken, mtoken)
        c_constants.SEARCH_PATH = o_path


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
        from conda.cli import main_info

        for k in ("___new_user_agent", "__user_agent", "anaconda_anon_usage"):
            context._cache_.pop(k, None)
        context._aau_initialized = None
        if hasattr(Context, "anaconda_anon_usage"):
            delattr(Context, "anaconda_anon_usage")
        if hasattr(Context, "checked_prefix"):
            delattr(Context, "checked_prefix")
        Context.parameter_names = tuple(
            k for k in Context.parameter_names if k != "anaconda_anon_usage"
        )
        orig_check_prefix = getattr(Context, "_old_check_prefix", None)
        if orig_check_prefix is not None:
            cli_install.check_prefix = orig_check_prefix
            delattr(Context, "_old_check_prefix")
        orig_user_agent = getattr(Context, "_old_user_agent", None)
        if orig_user_agent is not None:
            Context.user_agent = orig_user_agent
            delattr(Context, "_old_user_agent")
        orig_get_main_info_str = getattr(main_info, "_old_get_main_info_str", None)
        if orig_get_main_info_str is not None:
            main_info.get_main_info_str = orig_get_main_info_str
            delattr(Context, "_old_get_main_info_str")

    request.addfinalizer(_resetter)
