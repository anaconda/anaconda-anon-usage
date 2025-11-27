import base64
import datetime as dt
import json
import tempfile
import uuid
from os import mkdir
from os.path import dirname, join

import pytest
from conda.base import constants as c_constants
from conda.base.context import Context, context

from anaconda_anon_usage import tokens, utils

try:
    from anaconda_auth.token import AnacondaKeyring
except ImportError:
    AnacondaKeyring = None


def _jsond(rec, strip=True):
    result = json.dumps(rec)
    result = base64.urlsafe_b64encode(result.encode("ascii"))
    result = result.decode("ascii")
    if strip:
        result = result.rstrip("=")
    return result


def _keyring_data():
    domains = ["random.domain", "anaconda.cloud", "anaconda.com"]
    drecs, exp = {}, 0
    exp = int(dt.datetime.now(tz=dt.timezone.utc).timestamp()) + 7884000
    for dom in domains:
        exp = exp - 1
        sub = str(uuid.uuid4())
        header = {"alg": "RS256", "typ": "JWT"}
        payload = {"exp": exp, "sub": sub}
        # Not a real signature but we just need it to be a base64-encoded blob
        signature = {"fake": dom}
        api_key = ".".join(map(_jsond, (header, payload, signature)))
        rec = {"domain": dom, "api_key": api_key, "repo_tokens": [], "version": 2}
        # anaconda_auth doesn't like it when we strip the padding
        drecs[dom] = _jsond(rec, strip=False)
    result = {"Anaconda Cloud": drecs}
    return json.dumps(result), sub, api_key


@pytest.fixture
def api_key_sub(monkeypatch, aau_token_path):
    kstr, sub, _ = _keyring_data()
    keyring_path = join(dirname(aau_token_path), "keyring")
    with open(keyring_path, "w") as fp:
        fp.write(kstr)
    return sub


@pytest.fixture
def aau_token_path(monkeypatch, tmp_path):
    monkeypatch.setattr(tokens, "CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(tokens, "ANACONDA_DIR", str(tmp_path))
    keyring_path = tmp_path / "keyring"
    if AnacondaKeyring is not None:
        monkeypatch.setattr(AnacondaKeyring, "keyring_path", keyring_path)
    return str(tmp_path / "aau_token")


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


def _build_tokens(tpath, machine=True, dotted=False):
    pfx = "." if dotted else ""
    otoken = utils._random_token()
    tdir = dirname(tpath)
    with open(join(tdir, pfx + "org_token"), "w") as fp:
        fp.write(otoken + "\n# Anaconda organization token\n")
    if machine:
        mtoken = utils._random_token()
        with open(join(tdir, pfx + "machine_token"), "w") as fp:
            fp.write(mtoken + "\n# Anaconda machine token\n")
        itoken = utils._random_token()
        with open(join(tdir, pfx + "installer_token"), "w") as fp:
            fp.write(itoken + "\n# Anaconda installer token\n")
    else:
        mtoken = itoken = None
    return (otoken, mtoken, itoken)


@pytest.fixture
def no_system_tokens(aau_token_path):
    for tpath in _system_token_path(0):
        yield (None, None, None)


@pytest.fixture
def system_tokens(aau_token_path):
    for tpaths in _system_token_path(1):
        yield _build_tokens(tpaths[1], machine=True)


@pytest.fixture
def two_org_tokens(aau_token_path):
    for tpaths in _system_token_path(2):
        t1 = _build_tokens(tpaths[1], True)
        t2 = _build_tokens(tpaths[4], False)
        yield t1 + t2[:1]


@pytest.fixture
def two_dotted_org_tokens(aau_token_path):
    for tpaths in _system_token_path(2):
        t1 = _build_tokens(tpaths[1], True, dotted=True)
        t2 = _build_tokens(tpaths[4], False, dotted=True)
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
