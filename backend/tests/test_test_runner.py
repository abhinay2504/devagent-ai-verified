import pytest

from app.services.test_runner import TestRunnerError as RunnerError, run_pytest


def test_test_runner_does_not_fall_back_to_host_execution_by_default(test_environment, monkeypatch):
    monkeypatch.setattr("app.services.test_runner.shutil_which", lambda name: None)
    with pytest.raises(RunnerError, match="local runner is disabled"):
        run_pytest("demo")


def test_docker_runner_uses_restricted_fixed_command(test_environment, monkeypatch):
    import subprocess
    import app.services.test_runner as runner

    calls = []
    monkeypatch.setattr(runner, "shutil_which", lambda _name: "/usr/bin/docker")

    def fake_run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "[]", "")

    def fake_limited(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "2 passed", "")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    monkeypatch.setattr(runner, "_run_limited", fake_limited)
    result = runner.run_pytest("demo")
    assert result["passed"] is True
    assert result["runner"] == "docker"
    command = calls[1]
    assert "--network" in command and "none" in command
    assert "--read-only" in command
    assert "--user" in command and command[command.index("--user") + 1] == "65534:65534"
    assert "--cap-drop" in command and "ALL" in command
    assert "--mount" in command
    mount_arg = command[command.index("--mount") + 1]
    assert mount_arg.startswith("type=bind,source=") and mount_arg.endswith(",target=/workspace,readonly")
    assert "-p" in command and "no:cacheprovider" in command
    assert command[-4:] == ["pytest", "-q", "-p", "no:cacheprovider"]


def test_docker_inspect_timeout_is_reported_safely(test_environment, monkeypatch):
    import subprocess
    import app.services.test_runner as runner

    monkeypatch.setattr(runner, "shutil_which", lambda _name: "/usr/bin/docker")
    monkeypatch.setattr(
        runner.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(subprocess.TimeoutExpired("docker", 15)),
    )
    with pytest.raises(RunnerError, match="Timed out while checking Docker"):
        runner.run_pytest("demo")


def test_docker_timeout_requests_container_cleanup(test_environment, monkeypatch):
    import subprocess
    import app.services.test_runner as runner

    calls = []
    monkeypatch.setattr(runner, "shutil_which", lambda _name: "/usr/bin/docker")

    def fake_run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "[]", "")

    def fake_limited(command, **kwargs):
        calls.append(command)
        raise subprocess.TimeoutExpired(command, kwargs.get("timeout", 1))

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    monkeypatch.setattr(runner, "_run_limited", fake_limited)
    result = runner.run_pytest("demo")
    assert result["passed"] is False
    assert result["exit_code"] is None
    assert any(len(call) > 1 and call[1] == "kill" for call in calls)
    assert any(len(call) > 1 and call[1] == "rm" for call in calls)


def test_test_runner_bounds_captured_output():
    import os
    import sys
    import app.services.test_runner as runner

    result = runner._run_limited(
        [sys.executable, "-c", "print('x' * 100000)"],
        timeout=10,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert result.returncode == 0
    assert len(result.stdout.encode("utf-8")) <= runner.MAX_CAPTURED_OUTPUT_BYTES
    assert result.stdout.endswith("x\n")


def test_docker_infrastructure_exit_is_not_reported_as_test_failure(test_environment, monkeypatch):
    import subprocess
    import app.services.test_runner as runner

    monkeypatch.setattr(runner, "shutil_which", lambda _name: "/usr/bin/docker")
    monkeypatch.setattr(
        runner.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 0, "[]", ""),
    )
    monkeypatch.setattr(
        runner,
        "_run_limited",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 125, "docker daemon error", ""),
    )
    with pytest.raises(RunnerError, match="failed before pytest"):
        runner.run_pytest("demo")
