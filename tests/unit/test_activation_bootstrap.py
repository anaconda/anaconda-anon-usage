import sys

import pytest

from anaconda_anon_usage import _activation_bootstrap


@pytest.mark.parametrize(
    "argv",
    [
        ["conda"],
        ["conda", "info"],
        ["conda", "shell.posix"],
        ["conda", "shell.posix", "reactivate"],
    ],
)
def test_maybe_patch_activation_skips_non_shell_activate(mocker, argv):
    patch_main = mocker.patch("anaconda_anon_usage.patch.main")

    assert _activation_bootstrap.maybe_patch_activation(argv) is False
    patch_main.assert_not_called()


@pytest.mark.parametrize("shell", ["shell.posix", "shell.posix+json"])
def test_maybe_patch_activation_patches_shell_activate(mocker, shell):
    patch_main = mocker.patch("anaconda_anon_usage.patch.main")

    assert (
        _activation_bootstrap.maybe_patch_activation(["conda", shell, "activate"])
        is patch_main.return_value
    )

    patch_main.assert_called_once_with(plugin=True, command="activate")


def test_maybe_patch_activation_defaults_to_sys_argv(mocker, monkeypatch):
    patch_main = mocker.patch("anaconda_anon_usage.patch.main")
    monkeypatch.setattr(sys, "argv", ["conda", "shell.posix", "activate"])

    assert _activation_bootstrap.maybe_patch_activation() is patch_main.return_value

    patch_main.assert_called_once_with(plugin=True, command="activate")


def test_maybe_patch_activation_swallows_errors_by_default(mocker, monkeypatch, capsys):
    mocker.patch("anaconda_anon_usage.patch.main", side_effect=RuntimeError("failed"))
    monkeypatch.delenv("ANACONDA_ANON_USAGE_RAISE", raising=False)
    monkeypatch.delenv("ANACONDA_ANON_USAGE_DEBUG", raising=False)

    assert (
        _activation_bootstrap.maybe_patch_activation(
            ["conda", "shell.posix", "activate"]
        )
        is False
    )

    assert capsys.readouterr().err == ""


def test_maybe_patch_activation_reports_errors_in_debug(mocker, monkeypatch, capsys):
    mocker.patch("anaconda_anon_usage.patch.main", side_effect=RuntimeError("failed"))
    monkeypatch.delenv("ANACONDA_ANON_USAGE_RAISE", raising=False)
    monkeypatch.setenv("ANACONDA_ANON_USAGE_DEBUG", "1")

    assert (
        _activation_bootstrap.maybe_patch_activation(
            ["conda", "shell.posix", "activate"]
        )
        is False
    )

    assert "Error loading anaconda-anon-usage activation bootstrap: failed" in (
        capsys.readouterr().err
    )


def test_maybe_patch_activation_reraises_when_requested(mocker, monkeypatch):
    mocker.patch("anaconda_anon_usage.patch.main", side_effect=RuntimeError("failed"))
    monkeypatch.setenv("ANACONDA_ANON_USAGE_RAISE", "1")

    with pytest.raises(RuntimeError, match="failed"):
        _activation_bootstrap.maybe_patch_activation(
            ["conda", "shell.posix", "activate"]
        )
