import pytest

from app.services.patching import PatchError, apply_unified_patch, make_unified_diff, validate_relative_path


def test_path_validation_blocks_traversal():
    with pytest.raises(PatchError):
        validate_relative_path("../outside.py")
    with pytest.raises(PatchError):
        validate_relative_path(".env")


def test_patch_round_trip(test_environment):
    _, repo = test_environment
    old = (repo / "example.py").read_text(encoding="utf-8")
    new = "def add(a, b):\n    return a + b + 1\n"
    diff = make_unified_diff("example.py", old, new)
    changed = apply_unified_patch(repo, diff)
    assert changed == ["example.py"]
    assert (repo / "example.py").read_text(encoding="utf-8") == new


def test_patch_refuses_stale_context(test_environment):
    _, repo = test_environment
    diff = "--- a/example.py\n+++ b/example.py\n@@ -1,2 +1,2 @@\n-def add(a, b):\n+def add(x, y):\n-    return a - b\n+    return a + b\n"
    with pytest.raises(PatchError):
        apply_unified_patch(repo, diff)


def test_patch_path_rejects_env_secrets():
    with pytest.raises(PatchError):
        validate_relative_path("config/.env.production")


def test_patch_rejects_secret_and_control_character_paths():
    with pytest.raises(PatchError):
        validate_relative_path(".npmrc")
    with pytest.raises(PatchError):
        validate_relative_path("folder\n--- a/.env")


def test_patch_can_insert_at_start_of_file(test_environment):
    _, repo = test_environment
    target = repo / "example.py"
    old = target.read_text(encoding="utf-8")
    new = "# generated header\n" + old
    diff = make_unified_diff("example.py", old, new)
    assert apply_unified_patch(repo, diff) == ["example.py"]
    assert target.read_text(encoding="utf-8") == new


def test_patch_handles_source_lines_that_look_like_diff_headers(test_environment):
    _, repo = test_environment
    target = repo / "example.py"
    old = "-- old heading\nsecond line\n"
    new = "-- new heading\nsecond line\n"
    target.write_text(old, encoding="utf-8")
    diff = make_unified_diff("example.py", old, new)
    assert apply_unified_patch(repo, diff) == ["example.py"]
    assert target.read_text(encoding="utf-8") == new


def test_patch_preserves_crlf_line_endings(test_environment):
    _, repo = test_environment
    target = repo / "example.py"
    old = "def add(a, b):\r\n    return a + b\r\n"
    new = "def add(a, b):\r\n    return a + b + 1\r\n"
    target.write_bytes(old.encode("utf-8"))
    diff = make_unified_diff("example.py", old, new)
    apply_unified_patch(repo, diff)
    assert target.read_bytes() == new.encode("utf-8")


def test_lf_patch_applies_to_crlf_file_and_preserves_crlf(test_environment):
    _, repo = test_environment
    target = repo / "example.py"
    old_lf = "def add(a, b):\n    return a + b\n"
    new_lf = "def add(a, b):\n    return a + b + 1\n"
    target.write_bytes(old_lf.replace("\n", "\r\n").encode("utf-8"))

    diff = make_unified_diff("example.py", old_lf, new_lf)
    apply_unified_patch(repo, diff)

    assert target.read_bytes() == new_lf.replace("\n", "\r\n").encode("utf-8")


def test_patch_rejects_hunk_count_mismatch_without_writing(test_environment):
    _, repo = test_environment
    target = repo / "example.py"
    original = target.read_bytes()
    diff = (
        "--- a/example.py\n+++ b/example.py\n"
        "@@ -1,2 +1,2 @@\n"
        " def add(a, b):\n-    return a + b\n+    return a + b + 1\n"
    )
    # Header claims two removed/added lines, but only one of each is supplied.
    malformed = diff.replace("@@ -1,2 +1,2 @@", "@@ -1,3 +1,3 @@")
    with pytest.raises(PatchError, match="ended before all hunk lines"):
        apply_unified_patch(repo, malformed)
    assert target.read_bytes() == original


def test_multi_file_patch_applies_both_files(test_environment):
    _, repo = test_environment
    old_a = (repo / "example.py").read_text(encoding="utf-8")
    old_b = (repo / "test_example.py").read_text(encoding="utf-8")
    new_a = old_a.replace("a + b", "a + b + 1")
    new_b = old_b + "\ndef test_extra():\n    assert add(1, 1) == 3\n"
    diff = make_unified_diff("example.py", old_a, new_a) + "\n" + make_unified_diff("test_example.py", old_b, new_b)
    changed = apply_unified_patch(repo, diff)
    assert changed == ["example.py", "test_example.py"]
    assert (repo / "example.py").read_text(encoding="utf-8") == new_a
    assert (repo / "test_example.py").read_text(encoding="utf-8") == new_b


def test_patch_preserves_missing_final_newline(test_environment):
    _, repo = test_environment
    target = repo / "example.py"
    old = "old content"
    new = "new content"
    target.write_bytes(old.encode("utf-8"))
    diff = make_unified_diff("example.py", old, new)
    assert "\\ No newline at end of file" in diff
    apply_unified_patch(repo, diff)
    assert target.read_bytes() == new.encode("utf-8")


def test_patch_can_replace_content_of_empty_existing_file(test_environment):
    _, repo = test_environment
    target = repo / "empty.txt"
    target.write_bytes(b"")
    diff = make_unified_diff("empty.txt", "", "first line")
    apply_unified_patch(repo, diff)
    assert target.read_bytes() == b"first line"


def test_patch_preserves_no_newline_when_source_looks_like_header(test_environment):
    _, repo = test_environment
    target = repo / "example.py"
    old = "-- old heading"
    new = "-- new heading"
    target.write_bytes(old.encode("utf-8"))
    diff = make_unified_diff("example.py", old, new)
    assert "\\ No newline at end of file" in diff
    apply_unified_patch(repo, diff)
    assert target.read_bytes() == new.encode("utf-8")


def test_patch_round_trip_randomized_text_and_line_endings(test_environment):
    import random

    _, repo = test_environment
    target = repo / "example.py"
    rng = random.Random(20261012)
    lines = ["alpha", "beta", "-- header-like", "@@ odd", "", "λ unicode", "space  ", "  indent"]

    for _ in range(50):
        newline = rng.choice(["\n", "\r\n"])
        old_lines = [rng.choice(lines) for _ in range(rng.randrange(0, 12))]
        new_lines = [rng.choice(lines) for _ in range(rng.randrange(0, 12))]
        old = newline.join(old_lines) + (newline if old_lines and rng.choice([True, False]) else "")
        new = newline.join(new_lines) + (newline if new_lines and rng.choice([True, False]) else "")
        target.write_bytes(old.encode("utf-8"))
        diff = make_unified_diff("example.py", old, new)
        if diff:
            apply_unified_patch(repo, diff)
        assert target.read_bytes().decode("utf-8") == new
