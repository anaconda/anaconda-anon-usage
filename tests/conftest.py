import base64
import datetime as dt
import json
import tempfile
import uuid
from os import environ, mkdir
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


# These features are chained together in order to test that
# the API key search priority is correct.


@pytest.fixture
def keyring_in_file(aau_token_path):
    kstr, sub, _ = _keyring_data()
    with open(environ["ANACONDA_KEYRING_PATH"], "w") as fp:
        fp.write(kstr)
    return sub


@pytest.fixture
def keyring_in_secret(aau_token_path, keyring_in_file):
    fpath = join(environ["ANACONDA_SECRETS_DIR"], "anaconda_auth_keyring")
    kstr, sub, _ = _keyring_data()
    with open(fpath, "w") as fp:
        fp.write(kstr)
    return sub


@pytest.fixture
def keyring_in_env(monkeypatch, keyring_in_secret):
    kstr, sub, _ = _keyring_data()
    monkeypatch.setenv("ANACONDA_AUTH_KEYRING", kstr)
    return sub


@pytest.fixture
def keyring_in_module(monkeypatch, keyring_in_file):
    monkeypatch.setenv("ANACONDA_ANON_USAGE_STANDALONE", "")
    return keyring_in_file


@pytest.fixture
def api_key_in_secret(keyring_in_env):
    fpath = join(environ["ANACONDA_SECRETS_DIR"], "anaconda_auth_api_key")
    _, sub, api_key = _keyring_data()
    with open(fpath, "w") as fp:
        fp.write(api_key)
    return sub


@pytest.fixture
def api_key_in_env(monkeypatch, api_key_in_secret):
    _, sub, api_key = _keyring_data()
    monkeypatch.setenv("ANACONDA_AUTH_API_KEY", api_key)
    return sub


@pytest.fixture
def aau_token_path(monkeypatch, tmp_path):
    monkeypatch.setattr(tokens, "CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(tokens, "ANACONDA_DIR", str(tmp_path))
    keyring_dir = tmp_path / "anaconda"
    secret_dir = tmp_path / "secrets"
    keyring_dir.mkdir()
    secret_dir.mkdir()
    keyring_path = keyring_dir / "keyring"
    if AnacondaKeyring is not None:
        monkeypatch.setattr(AnacondaKeyring, "keyring_path", keyring_path)
    monkeypatch.setenv("ANACONDA_KEYRING_PATH", str(keyring_path))
    monkeypatch.setenv("ANACONDA_SECRETS_DIR", str(secret_dir))
    monkeypatch.setenv("ANACONDA_ANON_USAGE_STANDALONE", "1")
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
