"""Fixed-command test execution with a network-disabled Docker sandbox by default."""

from __future__ import annotations

import os
import subprocess
import threading
import uuid

from app.config import get_settings
from app.services.repository import resolve_repo


class TestRunnerError(RuntimeError):
    """Raised when a test runner cannot be started safely."""


MAX_CAPTURED_OUTPUT_BYTES = 12_000


def _run_limited(
    command: list[str],
    *,
    timeout: int,
    cwd=None,
    env=None,
) -> subprocess.CompletedProcess:
    """Run a command while draining pipes and retaining only bounded output tails."""
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
    )
    stdout_tail = bytearray()
    stderr_tail = bytearray()

    def drain(pipe, tail: bytearray) -> None:
        while True:
            chunk = pipe.read(4096)
            if not chunk:
                break
            tail.extend(chunk)
            if len(tail) > MAX_CAPTURED_OUTPUT_BYTES:
                del tail[:-MAX_CAPTURED_OUTPUT_BYTES]

    readers = [
        threading.Thread(target=drain, args=(process.stdout, stdout_tail), daemon=True),
        threading.Thread(target=drain, args=(process.stderr, stderr_tail), daemon=True),
    ]
    for reader in readers:
        reader.start()
    try:
        return_code = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
        except OSError:
            pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        for reader in readers:
            reader.join(timeout=5)
        raise subprocess.TimeoutExpired(command, timeout)
    for reader in readers:
        reader.join(timeout=5)
    # Present consistent newline conventions in API/UI output across Windows and POSIX.
    stdout_text = stdout_tail.decode("utf-8", errors="replace").replace("\r\n", "\n")
    stderr_text = stderr_tail.decode("utf-8", errors="replace").replace("\r\n", "\n")
    return subprocess.CompletedProcess(command, return_code, stdout_text, stderr_text)


def _run_docker_cleanup(docker: str, container_name: str) -> None:
    # A timed-out docker CLI does not always guarantee the daemon stopped the container.
    for action in ("kill", "rm"):
        try:
            subprocess.run(
                [docker, action, "-f", container_name] if action == "rm" else [docker, action, container_name],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
                shell=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass


def run_pytest(repo_relative: str) -> dict:
    settings = get_settings()
    repo = resolve_repo(repo_relative)
    timeout = max(5, min(settings.devagent_max_test_seconds, 300))
    docker = shutil_which("docker")

    if docker:
        try:
            image_check = subprocess.run(
                [docker, "image", "inspect", settings.devagent_docker_image],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise TestRunnerError("Timed out while checking Docker. Verify Docker Desktop is running.") from exc
        except OSError as exc:
            raise TestRunnerError(f"Could not start Docker CLI: {exc}") from exc

        if image_check.returncode != 0:
            raise TestRunnerError(
                f"Docker is available but runner image '{settings.devagent_docker_image}' was not found, "
                "or the Docker daemon is not running. From the project root run: "
                "docker build -t devagent-ai-test-runner:latest sandbox"
            )

        container_name = f"devagent-test-{uuid.uuid4().hex[:12]}"
        command = [
            docker, "run", "--rm", "--name", container_name,
            "--network", "none", "--read-only", "--user", "65534:65534", "--memory", "768m", "--memory-swap", "768m", "--cpus", "1",
            "--pids-limit", "128", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=128m,uid=65534,gid=65534",
            "-e", "HOME=/tmp", "-e", "PYTHONDONTWRITEBYTECODE=1",
            "-e", "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1",
            "--mount", f"type=bind,source={repo},target=/workspace,readonly", "-w", "/workspace",
            settings.devagent_docker_image, "python", "-m", "pytest", "-q", "-p", "no:cacheprovider",
        ]
        runner = "docker"
    elif settings.devagent_enable_local_test_runner:
        # This mode executes repository code on the host. Only enable it for trusted projects.
        command = ["python", "-m", "pytest", "-q"]
        runner = "local-opt-in"
        container_name = ""
    else:
        raise TestRunnerError(
            "Docker was not found. Install/start Docker Desktop for isolated tests. "
            "The local runner is disabled by default."
        )

    try:
        completed = _run_limited(
            command,
            cwd=repo if runner == "local-opt-in" else None,
            timeout=timeout,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
    except subprocess.TimeoutExpired:
        if runner == "docker":
            _run_docker_cleanup(docker, container_name)
        return {
            "runner": runner,
            "passed": False,
            "exit_code": None,
            "output": f"Tests exceeded timeout ({timeout}s). Docker cleanup was requested if applicable.",
        }
    except OSError as exc:
        raise TestRunnerError(f"Could not start the test runner: {exc}") from exc

    output = (completed.stdout or "") + ("\n" + completed.stderr if completed.stderr else "")
    if runner == "docker" and completed.returncode in {125, 126, 127}:
        raise TestRunnerError(
            "Docker failed before pytest could report a test result. Check Docker Desktop, "
            "the runner image, and the command configuration. Output: " + output[-2000:]
        )
    return {
        "runner": runner,
        "passed": completed.returncode == 0,
        "exit_code": completed.returncode,
        "output": output[-12000:],
    }


def shutil_which(name: str) -> str | None:
    import shutil
    return shutil.which(name)
