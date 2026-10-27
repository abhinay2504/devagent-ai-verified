import pytest

from app.services.repository import RepositoryError, list_files, read_file, resolve_repo


def test_lists_and_reads_files(test_environment):
    _, repo = test_environment
    assert "example.py" in list_files("demo")
    assert "return a + b" in read_file("demo", "example.py")


def test_rejects_repository_escape(test_environment):
    with pytest.raises(RepositoryError):
        resolve_repo("../outside")


def test_rejects_file_escape(test_environment):
    with pytest.raises(RepositoryError):
        read_file("demo", "../secret.txt")


def test_excludes_env_files(test_environment):
    _, repo = test_environment
    (repo / ".env").write_text("SECRET=abc", encoding="utf-8")
    assert ".env" not in list_files("demo")
    with pytest.raises(RepositoryError):
        read_file("demo", ".env")


def test_excludes_env_variant_files(test_environment):
    _, repo = test_environment
    (repo / ".env.production").write_text("SECRET=abc", encoding="utf-8")
    assert ".env.production" not in list_files("demo")
    with pytest.raises(RepositoryError):
        read_file("demo", ".env.production")


def test_excludes_common_secret_files(test_environment):
    _, repo = test_environment
    (repo / ".npmrc").write_text("//registry.example/:_authToken=secret", encoding="utf-8")
    (repo / "private.pem").write_text("PRIVATE KEY", encoding="utf-8")
    files = list_files("demo")
    assert ".npmrc" not in files
    assert "private.pem" not in files
    with pytest.raises(RepositoryError):
        read_file("demo", ".npmrc")
    with pytest.raises(RepositoryError):
        read_file("demo", "private.pem")


def test_rejects_sensitive_directory_as_repository(test_environment):
    workspace, _ = test_environment
    private_repo = workspace / ".ssh"
    private_repo.mkdir()
    (private_repo / "config").write_text("Host private", encoding="utf-8")
    with pytest.raises(RepositoryError, match="excluded or sensitive"):
        resolve_repo(".ssh")


def test_context_never_truncates_editable_files(test_environment, monkeypatch):
    from app.services.repository import collect_context

    _, repo = test_environment
    # Keep the individual file under the read limit but larger than the context budget.
    (repo / "large.py").write_text("x = 1\n" + "# filler\n" * 5000, encoding="utf-8")
    names, context = collect_context("demo", max_files=20, max_chars=500)
    assert "large.py" in names
    assert "large.py" not in context
    assert all(len(content) <= 500 for content in context.values())


def test_file_access_is_not_blocked_by_absolute_parent_named_build(tmp_path, monkeypatch):
    from app.config import get_settings
    from app.services.repository import read_file

    root = tmp_path / "build" / "workspace"
    repo = root / "demo"
    repo.mkdir(parents=True)
    (repo / "example.py").write_text("answer = 42\n", encoding="utf-8")
    monkeypatch.setenv("DEVAGENT_WORKSPACE_ROOT", str(root))
    monkeypatch.setenv("DEVAGENT_DATABASE_PATH", str(tmp_path / "db.sqlite3"))
    get_settings.cache_clear()
    try:
        assert read_file("demo", "example.py").replace("\r\n", "\n") == "answer = 42\n"
    finally:
        get_settings.cache_clear()


def test_context_prioritizes_files_named_in_task(test_environment):
    from app.services.repository import collect_context

    _, repo = test_environment
    for name in ["alpha.py", "beta.py", "gamma.py", "target_feature.py"]:
        (repo / name).write_text(f"# {name}\n", encoding="utf-8")
    names, context = collect_context("demo", max_files=2, max_chars=1000, query="Update target_feature.py")
    assert "target_feature.py" in names
    assert "target_feature.py" in context


def test_symlinked_files_are_not_listed_or_read(test_environment, tmp_path):
    from app.services.repository import RepositoryError

    _, repo = test_environment
    outside = tmp_path / "outside-secret.txt"
    outside.write_text("do not read", encoding="utf-8")
    try:
        (repo / "linked.txt").symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation is not available on this platform.")
    assert "linked.txt" not in list_files("demo")
    with pytest.raises(RepositoryError, match="Symbolic links"):
        read_file("demo", "linked.txt")


def test_symlinked_repository_is_rejected(test_environment):
    from app.services.repository import RepositoryError

    workspace, repo = test_environment
    alias = workspace / "alias"
    try:
        alias.symlink_to(repo, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation is not available on this platform.")
    with pytest.raises(RepositoryError, match="Symbolic links"):
        resolve_repo("alias")


def test_repository_and_file_paths_reject_control_characters(test_environment):
    from app.services.repository import RepositoryError

    with pytest.raises(RepositoryError, match="Control characters"):
        resolve_repo("demo\x00")
    with pytest.raises(RepositoryError, match="Control characters"):
        read_file("demo", "example.py\n")


def test_staging_files_are_not_exposed_to_the_agent(test_environment):
    _, repo = test_environment
    staging = repo / ".example.py.devagent-abcd1234.tmp"
    staging.write_text("partial staged contents", encoding="utf-8")
    assert staging.name not in list_files("demo")
    with pytest.raises(RepositoryError, match="excluded"):
        read_file("demo", staging.name)


def test_excludes_envrc_git_credentials_and_secret_directories(test_environment):
    _, repo = test_environment
    (repo / ".envrc").write_text("export TOKEN=secret", encoding="utf-8")
    (repo / ".git-credentials").write_text("https://user:token@example.com", encoding="utf-8")
    secrets = repo / "secrets"
    secrets.mkdir()
    (secrets / "application.json").write_text('{"token":"secret"}', encoding="utf-8")

    files = list_files("demo")
    assert ".envrc" not in files
    assert ".git-credentials" not in files
    assert "secrets/application.json" not in files
    with pytest.raises(RepositoryError):
        read_file("demo", ".envrc")
    with pytest.raises(RepositoryError):
        read_file("demo", "secrets/application.json")


def test_repository_listing_omits_symlinked_directories(test_environment):
    workspace, repo = test_environment
    alias = workspace / "linked-repo"
    try:
        alias.symlink_to(repo, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation is not available on this platform.")
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as client:
        result = client.get("/api/repositories")
    assert result.status_code == 200
    assert "linked-repo" not in result.json()["repositories"]
