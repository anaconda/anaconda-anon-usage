from conda.base.context import Context, context

from anaconda_anon_usage import patch


def test_new_user_agent():
    patch.main(plugin=True)
    assert context.user_agent is not None
    for term in ["conda/", "aau/", "e/", "c/", "s/"]:
        assert term in context.user_agent


def test_user_agent_no_token(monkeypatch):
    monkeypatch.setattr(patch, "token_string", lambda prefix: "")
    patch.main(plugin=True)
    assert "conda/" in context.user_agent
    assert "aau/" not in context.user_agent


def test_main_already_patched():
    Context._aau_initialized = True
    response = patch.main(plugin=True)
    assert not response
