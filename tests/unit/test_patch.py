import pytest
from conda.base.context import Context, context

from anaconda_anon_usage import patch


@pytest.fixture
def reset_patch(request):
    def resetter():
        from conda.cli import install as cli_install

        for container, name, old_value in (
            (Context, "user_agent", Context._old_user_agent),
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

    request.addfinalizer(resetter)


def test_new_user_agent(reset_patch):
    with pytest.raises(AttributeError, match="_old_user_agent"):
        assert patch._new_user_agent(context) is not None
    patch.main(plugin=True)
    assert patch._new_user_agent(context) is not None


def test_new_user_agent_no_token(monkeypatch, reset_patch):
    monkeypatch.setattr(patch, "token_string", lambda prefix: "")
    patch.main(plugin=True)
    user_agent = patch._new_user_agent(context)
    assert user_agent is not None
    assert " c/" not in user_agent


def test_main_already_patched(monkeypatch, reset_patch):
    monkeypatch.setattr(Context, "_old_user_agent", "test", raising=False)
    assert not hasattr(Context, "anaconda_anon_usage")
