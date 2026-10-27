"""Strict unified-diff generation and application for existing UTF-8 text files."""

from __future__ import annotations

import difflib
import os
import re
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path

from app.config import get_settings
from app.services.repository import is_sensitive_path, resolve_file


class PatchError(ValueError):
    """Raised when a patch is malformed, unsafe, or stale."""


_HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?:.*)$")
_NO_NEWLINE_MARKER = "\\ No newline at end of file"


def validate_relative_path(path: str) -> str:
    normalized = path.replace("\\", "/").strip()
    if not normalized or normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
        raise PatchError("Patch paths must be relative.")
    if any(ord(char) < 32 for char in normalized):
        raise PatchError("Control characters are not allowed in patch paths.")
    parts = Path(normalized).parts
    if ".." in parts or is_sensitive_path(parts):
        raise PatchError("Patch targets a forbidden path.")
    if normalized == ".git" or normalized.startswith(".git/"):
        raise PatchError("Git metadata cannot be modified by the agent.")
    return normalized


def make_unified_diff(path: str, old: str, new: str) -> str:
    path = validate_relative_path(path)
    raw_lines = difflib.unified_diff(
        old.splitlines(keepends=True),
        new.splitlines(keepends=True),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
    )
    # difflib preserves missing EOF newlines, which would concatenate adjacent diff
    # records. Encode those records using the standard no-newline marker instead.
    output: list[str] = []
    for index, line in enumerate(raw_lines):
        # The first two records are file headers; hunk headers begin with @@. Diff
        # content records always begin with a context/add/remove marker, even when the
        # source text itself starts with something like "-- " or "@@".
        is_header = index < 2 or line.startswith("@@")
        if line.endswith(("\n", "\r")):
            output.append(line)
        elif is_header:
            output.append(line + "\n")
        else:
            output.append(line + "\n")
            output.append(_NO_NEWLINE_MARKER + "\n")
    return "".join(output)


@dataclass(frozen=True)
class _HunkLine:
    kind: str
    text: str


@dataclass(frozen=True)
class _Hunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: tuple[_HunkLine, ...]


@dataclass(frozen=True)
class _FilePatch:
    path: str
    hunks: tuple[_Hunk, ...]
    raw_hunks: str


def _header_path(line: str, prefix: str) -> str:
    value = line.rstrip("\r\n")[4:]
    # Unified diff timestamps are tab-separated; spaces in filenames are valid.
    value = value.split("\t", 1)[0]
    if value.startswith(prefix):
        value = value[len(prefix):]
    return validate_relative_path(value)


def _parse_unified_diff(diff_text: str) -> list[_FilePatch]:
    if not diff_text.strip():
        raise PatchError("The proposed patch is empty.")
    if len(diff_text.encode("utf-8")) > get_settings().devagent_max_patch_bytes:
        raise PatchError("Patch exceeds the configured size limit.")

    lines = diff_text.splitlines(keepends=True)
    patches: list[_FilePatch] = []
    seen_paths: set[str] = set()
    i = 0

    while i < len(lines):
        if not lines[i].strip():
            i += 1
            continue
        if not lines[i].startswith("--- "):
            raise PatchError("Unexpected content outside a unified diff file section.")
        if i + 1 >= len(lines) or not lines[i + 1].startswith("+++ "):
            raise PatchError("Malformed unified diff headers.")

        old_path = _header_path(lines[i], "a/")
        new_path = _header_path(lines[i + 1], "b/")
        if old_path != new_path:
            raise PatchError("Renames are not supported in the first release.")
        if old_path in seen_paths:
            raise PatchError(f"Duplicate file section in patch: {old_path}")
        seen_paths.add(old_path)
        i += 2
        hunks: list[_Hunk] = []
        raw_start = i

        while i < len(lines) and lines[i].startswith("@@"):
            header = lines[i].rstrip("\r\n")
            match = _HUNK_HEADER.match(header)
            if not match:
                raise PatchError("Malformed hunk header.")
            old_start = int(match.group(1))
            old_count = int(match.group(2)) if match.group(2) is not None else 1
            new_start = int(match.group(3))
            new_count = int(match.group(4)) if match.group(4) is not None else 1
            if old_count < 0 or new_count < 0 or old_count + new_count == 0:
                raise PatchError("Invalid empty or negative hunk counts.")
            if (old_count and old_start < 1) or (not old_count and old_start < 0):
                raise PatchError("Invalid old-file line number in hunk header.")
            if (new_count and new_start < 1) or (not new_count and new_start < 0):
                raise PatchError("Invalid new-file line number in hunk header.")
            i += 1
            hunk_lines: list[_HunkLine] = []
            consumed_old = consumed_new = 0

            while consumed_old < old_count or consumed_new < new_count:
                if i >= len(lines):
                    raise PatchError("Patch ended before all hunk lines were provided.")
                line = lines[i]
                if line.startswith(_NO_NEWLINE_MARKER):
                    # Remove the separator added to keep diff records parseable.
                    if not hunk_lines or not hunk_lines[-1].text.endswith("\n"):
                        raise PatchError("No-newline marker does not follow a diff line.")
                    previous = hunk_lines[-1]
                    hunk_lines[-1] = _HunkLine(previous.kind, previous.text[:-1])
                    i += 1
                    continue
                if not line:
                    raise PatchError("Malformed empty diff line.")
                kind = line[0]
                content = line[1:]
                if kind == " ":
                    consumed_old += 1
                    consumed_new += 1
                elif kind == "-":
                    consumed_old += 1
                elif kind == "+":
                    consumed_new += 1
                else:
                    raise PatchError("Unexpected line inside unified diff hunk.")
                if consumed_old > old_count or consumed_new > new_count:
                    raise PatchError("Hunk line counts do not match the hunk header.")
                hunk_lines.append(_HunkLine(kind, content))
                i += 1

            if i < len(lines) and lines[i].startswith(_NO_NEWLINE_MARKER):
                if not hunk_lines or not hunk_lines[-1].text.endswith("\n"):
                    raise PatchError("No-newline marker does not follow a diff line.")
                previous = hunk_lines[-1]
                hunk_lines[-1] = _HunkLine(previous.kind, previous.text[:-1])
                i += 1
            hunks.append(_Hunk(old_start, old_count, new_start, new_count, tuple(hunk_lines)))

        if not hunks:
            raise PatchError(f"No hunks found for {old_path}.")
        raw_hunks = "".join(lines[raw_start:i])
        patches.append(_FilePatch(old_path, tuple(hunks), raw_hunks))

    if not patches:
        raise PatchError("No file changes were found in the patch.")
    return patches


def parse_patch(diff_text: str) -> list[tuple[str, str, str]]:
    """Parse a unified diff and return (path, hunk_text, path) tuples for compatibility."""
    return [(patch.path, patch.raw_hunks, patch.path) for patch in _parse_unified_diff(diff_text)]


def _normalize_line_endings(text: str) -> str:
    """Normalize line endings for comparison without changing file contents."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _apply_file_patch(original: str, patch: _FilePatch) -> str:
    old_lines = original.splitlines(keepends=True)
    output: list[str] = []
    source_cursor = 0
    # Model-generated unified diffs commonly use LF even when a Windows workspace
    # file uses CRLF. Compare logical lines independent of EOL style, preserve each
    # unchanged source line byte-for-byte, and format inserted lines using the
    # original file's dominant newline convention.
    if "\r\n" in original:
        newline = "\r\n"
    elif "\r" in original:
        newline = "\r"
    elif "\n" in original:
        newline = "\n"
    else:
        # An empty or single-line/no-EOL source gives us no file convention to keep.
        # Infer the style from patch records so additions preserve the model's EOL.
        patch_texts = [line.text for hunk in patch.hunks for line in hunk.lines]
        sample = next((text for text in patch_texts if "\n" in text or "\r" in text), "")
        newline = "\r\n" if "\r\n" in sample else ("\r" if "\r" in sample else "\n")

    def inserted_line(text: str) -> str:
        return _normalize_line_endings(text).replace("\n", newline)

    for hunk in patch.hunks:
        old_index = hunk.old_start if hunk.old_count == 0 else hunk.old_start - 1
        if old_index < source_cursor or old_index > len(old_lines):
            raise PatchError(f"Patch hunk is outside the original file: {patch.path}")
        output.extend(old_lines[source_cursor:old_index])
        source_cursor = old_index
        consumed_old = consumed_new = 0

        for line in hunk.lines:
            if line.kind == " ":
                if (source_cursor >= len(old_lines) or
                        _normalize_line_endings(old_lines[source_cursor]) != _normalize_line_endings(line.text)):
                    raise PatchError(f"Patch context mismatch in {patch.path}; file may have changed.")
                output.append(old_lines[source_cursor])
                source_cursor += 1
                consumed_old += 1
                consumed_new += 1
            elif line.kind == "-":
                if (source_cursor >= len(old_lines) or
                        _normalize_line_endings(old_lines[source_cursor]) != _normalize_line_endings(line.text)):
                    raise PatchError(f"Patch removal mismatch in {patch.path}; file may have changed.")
                source_cursor += 1
                consumed_old += 1
            elif line.kind == "+":
                output.append(inserted_line(line.text))
                consumed_new += 1

        if consumed_old != hunk.old_count or consumed_new != hunk.new_count:
            raise PatchError(f"Hunk line counts do not match in {patch.path}.")

    output.extend(old_lines[source_cursor:])
    return "".join(output)


def _stage_bytes(target: Path, content: bytes) -> Path:
    fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.devagent-", suffix=".tmp", dir=target.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.chmod(temp_path, stat.S_IMODE(target.stat().st_mode))
        except OSError:
            pass
        return temp_path
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def apply_unified_patch(repo: Path, diff_text: str) -> list[str]:
    """Validate every hunk first, then stage writes and roll back on replacement failure."""
    parsed = _parse_unified_diff(diff_text)
    staged: list[tuple[Path, Path, bytes, str]] = []
    replaced: list[tuple[Path, bytes, str]] = []

    try:
        for file_patch in parsed:
            target = resolve_file(repo, file_patch.path)
            if not target.exists() or not target.is_file():
                raise PatchError(f"Existing-file patches only: {file_patch.path} does not exist.")
            if target.stat().st_size > get_settings().devagent_max_file_bytes:
                raise PatchError(f"File exceeds the configured size limit: {file_patch.path}")
            original_bytes = target.read_bytes()
            if len(original_bytes) > get_settings().devagent_max_file_bytes:
                raise PatchError(f"File exceeds the configured size limit: {file_patch.path}")
            try:
                original = original_bytes.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise PatchError(f"Only UTF-8 text files can be patched: {file_patch.path}") from exc
            updated = _apply_file_patch(original, file_patch)
            updated_bytes = updated.encode("utf-8")
            if len(updated_bytes) > get_settings().devagent_max_file_bytes:
                raise PatchError(f"Patched file exceeds the configured size limit: {file_patch.path}")
            staged_path = _stage_bytes(target, updated_bytes)
            staged.append((target, staged_path, original_bytes, file_patch.path))

        for target, staged_path, original_bytes, relative_name in staged:
            os.replace(staged_path, target)
            replaced.append((target, original_bytes, relative_name))
    except Exception as exc:
        # Best-effort rollback of any target already replaced in this multi-file operation.
        rollback_errors = []
        for target, original_bytes, _ in reversed(replaced):
            try:
                rollback_path = _stage_bytes(target, original_bytes)
                os.replace(rollback_path, target)
            except Exception as rollback_exc:  # pragma: no cover - catastrophic filesystem failure
                rollback_errors.append(str(rollback_exc))
        for _, staged_path, _, _ in staged:
            staged_path.unlink(missing_ok=True)
        if rollback_errors:
            raise PatchError(f"Patch failed and rollback was incomplete: {'; '.join(rollback_errors)}") from exc
        if isinstance(exc, PatchError):
            raise
        raise PatchError(f"Could not apply patch safely: {exc}") from exc

    return [name for _, _, _, name in staged]
