from conda.base.context import context

from anaconda_anon_usage import patch, tokens

BASIC = {"aau", "c", "s", "e"}
SYSTEM = {"o", "m"}
OPTIONAL = {"a"} | SYSTEM
ALL = BASIC | OPTIONAL


def _assert_has_expected_tokens(must=BASIC, mustnot=()):
    patch.main(plugin=True)
    assert context.user_agent is not None
    tokens = {
        tok.split("/", 1)[0] for tok in context.user_agent.split(" ") if "/" in tok
    }
    mustnot = set(mustnot)
    must = ({"conda"} | BASIC | set(must)) - mustnot
    missing = must - tokens
    extras = tokens & mustnot
    assert not missing, "MISSING: %s" % missing
    assert not extras, "EXTRAS: %s" % extras


def test_user_agent_basic_tokens():
    _assert_has_expected_tokens()


def test_user_agent_no_system_tokens(no_system_tokens):
    _assert_has_expected_tokens(mustnot=SYSTEM)


def test_user_agent_system_tokens(system_tokens):
    _assert_has_expected_tokens(must=SYSTEM)


def test_user_agent_local_tokens():
    token_names = ("anaconda_cloud", "organization", "machine")
    expected = [
        tname[0] for tname in token_names if getattr(tokens, tname + "_token")()
    ]
    _assert_has_expected_tokens(expected)


def test_user_agent_no_token(monkeypatch):
    monkeypatch.setattr(patch, "token_string", lambda prefix: "")
    _assert_has_expected_tokens(mustnot=ALL)


def test_main_already_patched():
    response = patch.main(plugin=True)
    assert response
    response = patch.main(plugin=True)
    assert not response


def test_main_info():
    patch.main(plugin=True)
    tokens = dict(t.split("/", 1) for t in context.user_agent.split(" "))
    for tok in ALL - {"aau"}:
        if tok in tokens:
            tokens[tok] = "."
    from conda.cli import main_info

    info_dict = main_info.get_info_dict()
    assert info_dict["user_agent"] == context.user_agent
    info_str = main_info.get_main_info_str(info_dict)
    ua_strs = [
        x.strip().split(" : ", 1)[-1]
        for x in info_str.splitlines()
        if x.lstrip().startswith("user-agent : ")
    ]
    assert ua_strs
    token2 = dict(t.split("/", 1) for t in ua_strs[0].split(" "))
    assert token2 == tokens
