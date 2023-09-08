import pytest
from conda.base.context import Context, context

from anaconda_anon_usage import patch


@pytest.fixture
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
            (cli_install, "check_prefix", context._old_check_prefix),
        ):
            if hasattr(container, name):
                delattr(container, name)
            if old_value is None:
                continue
            setattr(container, name, old_value)

    request.addfinalizer(_resetter)


def test_new_user_agent(reset_patch):
    patch.main(plugin=True)
    assert context.user_agent is not None
    for term in ["conda/", "aau/", " e/", " c/", " s/"]:
        assert term in context.user_agent


def test_user_agent_no_token(monkeypatch, reset_patch):
    monkeypatch.setattr(patch, "token_string", lambda prefix: "")
    patch.main(plugin=True)
    assert "conda/" in context.user_agent
    assert "aau/" not in context.user_agent


def test_main_already_patched(reset_patch):
    Context._aau_initialized = True
    response = patch.main(plugin=True)
    assert not response
