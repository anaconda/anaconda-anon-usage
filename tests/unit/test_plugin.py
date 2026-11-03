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


@pytest.mark.parametrize("set_type", [set, frozenset])
@pytest.mark.parametrize("commands", [(), ("info", "custom-command")])
def test_pre_command_reflected_intersection(plugin_manager, set_type, commands):
    (command_hook,) = plugin_manager.get_hook_results("pre_commands")
    targets = set_type(commands)

    result = targets & command_hook.run_for

    assert result == targets
    assert type(result) is set_type
    assert targets == set_type(commands)
    if set_type is set:
        assert result is not targets


def test_pre_command_intersection_rejects_unsupported_operand(plugin_manager):
    (command_hook,) = plugin_manager.get_hook_results("pre_commands")
    other = ["info"]

    assert command_hook.run_for.__rand__(other) is NotImplemented
    with pytest.raises(TypeError):
        other & command_hook.run_for


@pytest.mark.parametrize(
    "command",
    ["info", "activate", "env_update", "custom-command"],
)
def test_pre_command_dispatch(plugin_manager, mocker, command):
    patch_main = mocker.patch("anaconda_anon_usage.patch.main")

    plugin_manager.invoke_pre_commands(command)

    patch_main.assert_called_once_with(plugin=True, command=command)
