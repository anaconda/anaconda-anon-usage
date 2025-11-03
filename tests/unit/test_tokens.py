import base64
import re
import uuid
from os.path import exists

import pytest

from anaconda_anon_usage import tokens, utils

try:
    import anaconda_auth
except ImportError:
    anaconda_auth = None


def test_client_token(aau_token_path):
    assert not exists(aau_token_path)
    assert tokens.client_token() != ""
    assert exists(aau_token_path)


def test_client_token_no_nodeid(aau_token_path, mocker):
    m1 = mocker.patch("anaconda_anon_usage.utils._get_node_str")
    m1.return_value = None
    node_path = aau_token_path + "_host"
    assert not exists(aau_token_path) and not exists(node_path)
    token1 = tokens.client_token()
    assert token1 != "" and exists(aau_token_path)
    with open(aau_token_path) as fp:
        token2 = fp.read()
    assert token1 == token2, (token1, token2)
    with open(node_path) as fp:
        saved_node = fp.read()
    assert not saved_node, saved_node


def test_client_token_add_hostid(aau_token_path):
    node_path = aau_token_path + "_host"
    assert not exists(aau_token_path) and not exists(node_path)
    token1 = utils._random_token()
    with open(aau_token_path, "w") as fp:
        fp.write(token1)
    token2 = tokens.client_token()
    assert token1 == token2
    with open(aau_token_path) as fp:
        token3 = fp.read()
    with open(node_path) as fp:
        saved_node = fp.read()
    assert token3 == token2, (token2, token3)
    assert saved_node == utils._get_node_str(), saved_node
    utils._cache_clear()
    token4 = tokens.client_token()
    assert token4 == token2, (token2, token4)


def test_client_token_replace_hostid(aau_token_path):
    node_path = aau_token_path + "_host"
    assert not exists(aau_token_path) and not exists(node_path)
    token1 = utils._random_token()
    with open(aau_token_path, "w") as fp:
        fp.write(token1)
    with open(node_path, "w") as fp:
        fp.write("xxxxxxxx")
    token2 = tokens.client_token()
    assert token1 != token2
    with open(aau_token_path) as fp:
        token3 = fp.read()
    with open(node_path) as fp:
        saved_node = fp.read()
    assert token3 == token2, (token2, token3)
    assert saved_node == utils._get_node_str(), saved_node
    utils._cache_clear()
    token4 = tokens.client_token()
    assert token4 == token2, (token2, token4)


def test_client_token_migrate_hostid(aau_token_path):
    node_path = aau_token_path + "_host"
    assert not exists(aau_token_path) and not exists(node_path)
    token1 = utils._random_token()
    with open(aau_token_path, "w") as fp:
        fp.write(token1 + " " + utils._get_node_str())
    token2 = tokens.client_token()
    assert token1 == token2
    with open(aau_token_path) as fp:
        token3 = fp.read()
    with open(node_path) as fp:
        saved_node = fp.read()
    assert token3 == token2, (token2, token3)
    assert saved_node == utils._get_node_str(), saved_node
    utils._cache_clear()
    token4 = tokens.client_token()
    assert token4 == token2, (token2, token4)


def test_environment_token_without_monkey_patching():
    assert tokens.environment_token() is not None


def test_environment_token_with_target_prefix(tmpdir):
    prefix_token = tokens.environment_token(prefix=tmpdir)
    assert prefix_token is not None
    assert prefix_token != tokens.environment_token()


def test_token_string(no_system_tokens):
    token_string = tokens.token_string()
    assert "aau/" in token_string
    assert "c/" in token_string
    assert "s/" in token_string
    assert "e/" in token_string
    assert "a/" not in token_string
    assert "i/" not in token_string
    assert "o/" not in token_string
    assert "m/" not in token_string


def test_token_string_disabled(no_system_tokens):
    token_string = tokens.token_string(enabled=False)
    assert "aau/" in token_string
    assert "c/" not in token_string
    assert "s/" not in token_string
    assert "e/" not in token_string
    assert "a/" not in token_string
    assert "i/" not in token_string
    assert "o/" not in token_string
    assert "m/" not in token_string


def test_token_string_with_system(system_tokens):
    org_token, mch_token, ins_token = system_tokens
    token_string = tokens.token_string()
    assert "i/" + ins_token in token_string
    assert "o/" + org_token in token_string
    assert "m/" + mch_token in token_string
    assert token_string.count(" o/") == 1


def test_token_string_with_two_org_tokens(two_org_tokens):
    org_token, mch_token, ins_token, org_token2 = two_org_tokens
    token_string = tokens.token_string()
    assert "i/" + ins_token in token_string
    assert "o/" + org_token in token_string
    assert "m/" + mch_token in token_string
    assert "o/" + org_token2 in token_string
    assert token_string.count(" o/") == 2


def test_token_string_with_two_dotted_org_tokens(two_dotted_org_tokens):
    org_token, mch_token, ins_token, org_token2 = two_dotted_org_tokens
    token_string = tokens.token_string()
    assert "i/" + ins_token in token_string
    assert "o/" + org_token in token_string
    assert "m/" + mch_token in token_string
    assert "o/" + org_token2 in token_string
    assert token_string.count(" o/") == 2


def test_token_string_with_env_org_token(monkeypatch, no_system_tokens):
    org_token_e = utils._random_token()
    mch_token_e = utils._random_token()
    ins_token_e = utils._random_token()
    monkeypatch.setenv("ANACONDA_ANON_USAGE_ORG_TOKEN", org_token_e)
    monkeypatch.setenv("ANACONDA_ANON_USAGE_MACHINE_TOKEN", mch_token_e)
    monkeypatch.setenv("ANACONDA_ANON_USAGE_INSTALLER_TOKEN", ins_token_e)
    token_string = tokens.token_string()
    assert "o/" + org_token_e in token_string
    assert "m/" + mch_token_e in token_string


def test_token_string_with_system_and_env(monkeypatch, system_tokens):
    org_token, mch_token = system_tokens
    org_token_e = utils._random_token()
    mch_token_e = utils._random_token()
    ins_token_e = utils._random_token()
    monkeypatch.setenv("ANACONDA_ANON_USAGE_ORG_TOKEN", org_token_e)
    monkeypatch.setenv("ANACONDA_ANON_USAGE_MACHINE_TOKEN", mch_token_e)
    monkeypatch.setenv("ANACONDA_ANON_USAGE_INSTALLER_TOKEN", ins_token_e)
    token_string = tokens.token_string()
    assert "i/" + ins_token in token_string
    assert "i/" + ins_token_e in token_string
    assert "i/" + ins_token_e in token_string
    assert "o/" + org_token in token_string
    assert "o/" + org_token_e in token_string
    assert "m/" + mch_token in token_string
    assert "m/" + mch_token_e in token_string
    assert token_string.count(" o/") == 2
    assert token_string.count(" m/") == 2
    assert token_string.count(" i/") == 2


def test_token_string_with_invalid_tokens(monkeypatch, no_system_tokens):
    org_token_e = "invalid token"
    mch_token_e = "superlongtokenthathasnobusinessbeinganactualtoken"
    ins_token_e = "fake installer"
    monkeypatch.setenv("ANACONDA_ANON_USAGE_ORG_TOKEN", org_token_e)
    monkeypatch.setenv("ANACONDA_ANON_USAGE_MACHINE_TOKEN", mch_token_e)
    monkeypatch.setenv("ANACONDA_ANON_USAGE_INSTALLER_TOKEN", ins_token_e)
    token_string = tokens.token_string()
    assert "o/" not in token_string
    assert "m/" not in token_string
    assert "i/" not in token_string


def test_token_string_no_client_token(monkeypatch, no_system_tokens):
    def _mock_saved_token(*args, **kwargs):
        return ""

    monkeypatch.setattr(tokens, "environment_token", lambda prefix: "env_token")
    monkeypatch.setattr(tokens, "_saved_token", _mock_saved_token)

    token_string = tokens.token_string()
    assert "c/" not in token_string
    assert "s/" in token_string
    assert "e/env_token" in token_string
    assert "i/" not in token_string
    assert "o/" not in token_string
    assert "m/" not in token_string


def test_token_string_no_environment_token(monkeypatch, no_system_tokens):
    monkeypatch.setattr(tokens, "environment_token", lambda prefix: "")

    token_string = tokens.token_string()
    assert "c/" in token_string
    assert "s/" in token_string
    assert "e/" not in token_string
    assert "i/" not in token_string
    assert "o/" not in token_string
    assert "m/" not in token_string


def test_token_string_full_readonly(monkeypatch, no_system_tokens):
    monkeypatch.setattr(utils, "READ_CHAOS", "ce")
    monkeypatch.setattr(utils, "WRITE_CHAOS", "ce")
    token_string = tokens.token_string()
    assert "c/" not in token_string
    assert "s/" in token_string
    assert "e/" not in token_string
    assert "i/" not in token_string
    assert "o/" not in token_string
    assert "m/" not in token_string


def test_token_string_env_readonly(monkeypatch, no_system_tokens):
    monkeypatch.setattr(utils, "READ_CHAOS", "e")
    monkeypatch.setattr(utils, "WRITE_CHAOS", "e")

    token_string = tokens.token_string()
    assert "c/" in token_string
    assert "s/" in token_string
    assert "e/" not in token_string
    assert "i/" not in token_string
    assert "o/" not in token_string
    assert "m/" not in token_string


@pytest.mark.skipif(anaconda_auth is None, reason="Requires the anaconda_auth module")
def test_keyring_in_module(api_key_sub):
    token_string = tokens.token_string()
    assert "a/" in token_string
    expected = uuid.UUID(api_key_sub).bytes
    expected = base64.urlsafe_b64encode(expected).decode("ascii").rstrip("=")
    aval = re.sub("^.*a/", "", token_string).split(" ", 1)[0]
    assert aval == expected
