from conda import plugins


def pre_command_patcher(command):
    try:
        from . import patch  # noqa

        patch.main(plugin=True, command=command)
    except Exception as exc:  # pragma: nocover
        print("Error loading anaconda-anon-usage:", exc)


@plugins.hookimpl
def conda_pre_commands():
    yield plugins.types.CondaPreCommand(
        name="anaconda-anon-usage",
        action=pre_command_patcher,
        # Hook names follow command handlers, including env_* on older conda.
        run_for={
            "activate",
            "check",
            "clean",
            "commands",
            "compare",
            "config",
            "create",
            "deactivate",
            "doctor",
            "env",
            "env_config",
            "env_create",
            "env_export",
            "env_list",
            "env_remove",
            "env_update",
            "env_vars",
            "export",
            "hook",
            "info",
            "init",
            "install",
            "list",
            "mock_activate",
            "mock_deactivate",
            "notices",
            "package",
            "plugins",
            "reactivate",
            "remove",
            "rename",
            "run",
            "search",
            "update",
        },
    )
