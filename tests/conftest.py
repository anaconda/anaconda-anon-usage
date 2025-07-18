import base64
import json
import tempfile
import uuid
from os import mkdir
from os.path import dirname, join

import pytest
from conda.base import constants as c_constants
from conda.base.context import Context, context

from anaconda_anon_usage import tokens, utils


def _jsond(rec, urlsafe=False):
    return base64.b64encode(json.dumps(rec).encode("ascii")).decode("ascii")


def _test_keyring():
    domains = ["random.domain", "anaconda.cloud", "anaconda.com"]
    drecs, exp = {}, 0
    for dom in domains:
        exp = exp + 123456
        sub = str(uuid.uuid4())
        rec = {"exp": exp, "sub": sub}
        api_key = "xxx." + _jsond(rec) + ".xxx"
        rec = {"domain": dom, "api_key": api_key, "repo_tokens": [], "version": 2}
        drecs[dom] = _jsond(rec)
    result = {"Anaconda Cloud": drecs}
    return json.dumps(result), sub


@pytest.fixture
def aau_token_path():
    old_dir, old_adir = tokens.CONFIG_DIR, tokens.ANACONDA_DIR
    with tempfile.TemporaryDirectory() as tname:
        tokens.CONFIG_DIR = tokens.ANACONDA_DIR = tname
        yield join(tname, "aau_token")
    tokens.CONFIG_DIR = old_dir
    tokens.ANACONDA_DIR = old_adir


@pytest.fixture()
def anaconda_uid(aau_token_path):
    kpath = join(dirname(aau_token_path), "keyring")
    kstr, sub = _test_keyring()
    with open(kpath, "w") as fp:
        fp.write(kstr)
    yield sub


def _system_token_path(npaths=1):
    with tempfile.TemporaryDirectory() as tname:
        utils._cache_clear("_search_path", "organization_token", "machine_token")
        tname = tname.replace("\\", "/")
        o_path = c_constants.SEARCH_PATH
        n_path = ("/tmp/fake/condarc.d/",)
        for k in range(npaths):
            tdir = join(tname, "t%d" % k)
            mkdir(tdir)
            n_path += (tdir + "/.condarc", tdir + "/condarc", tdir + "/condarc.d/")
        c_constants.SEARCH_PATH = n_path
        yield n_path
        c_constants.SEARCH_PATH = o_path
        utils._cache_clear("_search_path", "organization_tokens", "machine_tokens")


def _build_tokens(tpath, machine=True):
    otoken = utils._random_token()
    with open(dirname(tpath) + "/org_token", "w") as fp:
        fp.write(otoken + "\n# Anaconda organization token\n")
    if machine:
        mtoken = utils._random_token()
        with open(dirname(tpath) + "/machine_token", "w") as fp:
            fp.write(mtoken + "\n# Anaconda machine token\n")
    else:
        mtoken = None
    return (otoken, mtoken)


@pytest.fixture
def no_system_tokens(aau_token_path):
    for tpath in _system_token_path(0):
        yield (None, None)


@pytest.fixture
def system_tokens(aau_token_path):
    for tpaths in _system_token_path(1):
        yield _build_tokens(tpaths[1])


@pytest.fixture
def two_org_tokens(aau_token_path):
    for tpaths in _system_token_path(2):
        t1 = _build_tokens(tpaths[1], True)
        t2 = _build_tokens(tpaths[4], False)
        yield t1 + t2[:1]


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
