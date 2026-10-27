import re
from pathlib import Path

from app.config import get_settings

IGNORED_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", "dist", "build", ".next", ".ssh", ".aws", ".azure", ".kube", ".gnupg", ".config", ".terraform", "secrets", "secret", "credentials"}
IGNORED_NAMES = {
    ".env", ".env.local", ".npmrc", ".pypirc", ".netrc", ".pgpass", ".my.cnf",
    ".htpasswd", ".envrc", ".git-credentials", "id_rsa", "id_ed25519", "credentials", "credentials.json",
    "service-account.json", "secrets.json", "token.json",
}
SENSITIVE_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".jks", ".keystore"}


def is_sensitive_path(parts) -> bool:
    """Return True for common local secrets and private-key paths."""
    normalized = [str(part).lower() for part in parts]
    name = normalized[-1] if normalized else ""
    return (
        any(part in IGNORED_DIRS for part in normalized)
        or name in IGNORED_NAMES
        or name.startswith(("id_rsa_", "id_ed25519_"))
        or name.startswith(".env.")
        or (".devagent-" in name and name.endswith(".tmp"))
        or any(name.endswith(suffix) for suffix in SENSITIVE_SUFFIXES)
    )


class RepositoryError(ValueError):
    pass


def resolve_repo(repo_relative: str) -> Path:
    root = get_settings().workspace_root.resolve()
    normalized = repo_relative.replace("\\", "/")
    if any(ord(char) < 32 for char in normalized):
        raise RepositoryError("Control characters are not allowed in repository paths.")
    requested = Path(normalized)
    if requested.is_absolute() or ".." in requested.parts:
        raise RepositoryError("Repository path must be a relative path without traversal components.")
    cursor = root
    for part in requested.parts:
        if part in {"", "."}:
            continue
        cursor = cursor / part
        if cursor.is_symlink():
            raise RepositoryError("Symbolic links are not supported for repository access.")
    candidate = (root / requested).resolve()
    if candidate == root or root not in candidate.parents:
        raise RepositoryError("Repository path must point to a subdirectory inside the configured workspace root.")
    relative_parts = candidate.relative_to(root).parts
    if is_sensitive_path(relative_parts):
        raise RepositoryError("Repository path points to an excluded or sensitive directory.")
    if not candidate.exists() or not candidate.is_dir():
        raise RepositoryError("Repository directory does not exist inside the configured workspace root.")
    return candidate


def resolve_file(repo: Path, relative_path: str) -> Path:
    normalized = relative_path.replace("\\", "/")
    if any(ord(char) < 32 for char in normalized):
        raise RepositoryError("Control characters are not allowed in file paths.")
    requested = Path(normalized)
    if not relative_path or requested.is_absolute() or ".." in requested.parts:
        raise RepositoryError("A relative file path without traversal components is required.")
    # Symlinks can make a harmless-looking repository path target a different file.
    # Keep the first release simple: repository reads/edits through symlinks are refused.
    cursor = repo
    for part in requested.parts:
        if part in {"", "."}:
            continue
        cursor = cursor / part
        if cursor.is_symlink():
            raise RepositoryError("Symbolic links are not supported for agent file access.")
    candidate = (repo / requested).resolve()
    if candidate != repo and repo not in candidate.parents:
        raise RepositoryError("File path escapes the repository.")
    # Check only the path relative to the repository, not absolute parent directories
    # such as a user's folder being named "build" or ".ssh".
    relative_parts = candidate.relative_to(repo).parts
    if is_sensitive_path(relative_parts):
        raise RepositoryError("This file or directory is excluded from agent access.")
    return candidate


def list_files(repo_relative: str, max_items: int = 250) -> list[str]:
    repo = resolve_repo(repo_relative)
    result = []
    for path in sorted(repo.rglob("*")):
        if len(result) >= max_items:
            break
        if path.is_symlink() or not path.is_file():
            continue
        rel = path.relative_to(repo)
        if is_sensitive_path(rel.parts):
            continue
        try:
            if path.stat().st_size > get_settings().devagent_max_file_bytes:
                continue
        except OSError:
            continue
        result.append(rel.as_posix())
    return result


def read_file(repo_relative: str, relative_path: str) -> str:
    repo = resolve_repo(repo_relative)
    path = resolve_file(repo, relative_path)
    if not path.is_file():
        raise RepositoryError("File does not exist.")
    if path.stat().st_size > get_settings().devagent_max_file_bytes:
        raise RepositoryError("File exceeds the configured size limit.")
    try:
        # Expose stable LF text to the agent/API on every OS. The patch applier
        # separately preserves the repository file's original newline convention.
        return path.read_bytes().decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    except UnicodeDecodeError as exc:
        raise RepositoryError("Only UTF-8 text files can be read.") from exc


def collect_context(
    repo_relative: str,
    max_files: int = 12,
    max_chars: int = 24000,
    query: str = "",
) -> tuple[list[str], dict[str, str]]:
    """Collect complete files, prioritizing paths relevant to the task description."""
    names = list_files(repo_relative)
    query_tokens = set(re.findall(r"[a-z0-9]+", query.lower()))

    def rank(path: str) -> tuple[int, int, str]:
        path_lower = path.lower()
        path_tokens = set(re.findall(r"[a-z0-9]+", path_lower))
        relevance = len(query_tokens & path_tokens)
        # An explicitly named file (including an extension) gets a strong boost.
        explicit = 2 if path_lower in query.lower() else 0
        conventional = 1 if path in {"README.md", "pyproject.toml", "requirements.txt"} else 0
        return (-(relevance + explicit), -conventional, path)

    priority = sorted(names, key=rank)
    contents: dict[str, str] = {}
    used = 0
    for name in priority:
        if len(contents) >= max_files or used >= max_chars:
            break
        try:
            text = read_file(repo_relative, name)
        except RepositoryError:
            continue
        remaining = max_chars - used
        if len(text) > remaining:
            # Never give the model a truncated file as the basis for a full-file replacement:
            # doing so could delete the unseen suffix when a patch is applied. Keep looking for
            # smaller relevant files rather than ending context collection at this file.
            continue
        contents[name] = text
        used += len(text)
    return names, contents
