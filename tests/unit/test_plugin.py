import pytest


@pytest.fixture
def plugin_manager():
    plugin_types = pytest.importorskip("conda.plugins.types")
    if not hasattr(plugin_types, "CondaPreCommand"):
        pytest.skip("Pre-command hooks require conda >= 23.7")

    from conda.plugins.hookspec import CondaSpecs
    from conda.plugins.manager import CondaPluginManager

    from anaconda_anon_usage import plugin

    manager = CondaPluginManager()
    manager.add_hookspecs(CondaSpecs)
    manager.register(plugin)
    return manager


def test_pre_command_targets_support_set_operations(plugin_manager):
    (command_hook,) = plugin_manager.get_hook_results("pre_commands")

    assert isinstance(command_hook.run_for, set)
    assert frozenset({"info", "activate", "env_update"}) & command_hook.run_for == {
        "info",
        "activate",
        "env_update",
    }
    assert "custom-command" not in command_hook.run_for


@pytest.mark.parametrize(
    "command",
    [
        "activate",
        "config",
        "create",
        "env_config",
        "env_create",
        "env_export",
        "env_list",
        "env_remove",
        "env_update",
        "env_vars",
        "export",
        "info",
        "install",
        "remove",
        "run",
        "search",
        "update",
    ],
)
def test_pre_command_dispatch(plugin_manager, mocker, command):
    patch_main = mocker.patch("anaconda_anon_usage.patch.main")

    plugin_manager.invoke_pre_commands(command)

    patch_main.assert_called_once_with(plugin=True, command=command)


def test_unregistered_command_does_not_patch(plugin_manager, mocker):
    patch_main = mocker.patch("anaconda_anon_usage.patch.main")

    plugin_manager.invoke_pre_commands("custom-command")

    patch_main.assert_not_called()
