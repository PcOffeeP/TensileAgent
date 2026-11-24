"""Guard tests for scripts/sync_and_clean.sh safety locks."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


SCRIPT_SRC = Path(__file__).resolve().parents[1] / "scripts" / "sync_and_clean.sh"


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def _init_fixture_repo(tmp_path: Path) -> tuple[Path, Path]:
    bare = tmp_path / "remote.git"
    _git(tmp_path, "init", "--bare", str(bare))
    _git(bare, "symbolic-ref", "HEAD", "refs/heads/main")

    main_wt = tmp_path / "main_wt"
    main_wt.mkdir()
    _git(main_wt, "init", "-b", "main")
    _git(main_wt, "config", "user.name", "Test")
    _git(main_wt, "config", "user.email", "test@example.com")
    _git(main_wt, "remote", "add", "github", str(bare))

    (main_wt / ".gitignore").write_text(
        "agent/.env\ndata/08_runtime/\ndocs/comp-mat/\n.pytest_cache/\n__pycache__/\n",
        encoding="utf-8",
    )
    (main_wt / "scripts").mkdir(parents=True, exist_ok=True)
    shutil.copy2(SCRIPT_SRC, main_wt / "scripts" / "sync_and_clean.sh")
    _git(main_wt, "add", ".gitignore", "scripts/sync_and_clean.sh")
    _git(main_wt, "commit", "-m", "init")
    _git(main_wt, "push", "-u", "github", "main")
    return bare, main_wt


def _create_merged_worktree(bare: Path, main_wt: Path, tmp_path: Path, name: str) -> Path:
    wt = tmp_path / f"wt_{name}"
    branch = f"work/{name}"
    _git(main_wt, "worktree", "add", "--no-track", str(wt), "-b", branch, "github/main")
    (wt / f"{name}.txt").write_text(f"feature {name}\n", encoding="utf-8")
    _git(wt, "add", f"{name}.txt")
    _git(wt, "commit", "-m", f"feat: {name}")
    _git(wt, "push", "github", branch)

    # Simulate GitHub "Create a merge commit" in a separate clone
    merger = tmp_path / f"merger_{name}"
    _git(tmp_path, "clone", str(bare), str(merger))
    _git(merger, "config", "user.name", "Merger")
    _git(merger, "config", "user.email", "merger@example.com")
    _git(merger, "merge", "--no-ff", f"origin/{branch}", "-m", f"Merge {branch}")
    _git(merger, "push", "origin", "main")
    return wt


def test_sync_and_clean_preserves_worktree_with_ignored_local_files_and_cleans_cache_only(
    tmp_path: Path,
) -> None:
    bare, main_wt = _init_fixture_repo(tmp_path)
    wt_secret = _create_merged_worktree(bare, main_wt, tmp_path, "keep_env")
    wt_cache = _create_merged_worktree(bare, main_wt, tmp_path, "cache_only")

    # Place gitignored local secret in wt_secret
    (wt_secret / "agent").mkdir(parents=True, exist_ok=True)
    secret_file = wt_secret / "agent" / ".env"
    secret_file.write_text("LLM_API_KEY=secret\n", encoding="utf-8")

    # Place only rebuildable cache in wt_cache
    (wt_cache / ".pytest_cache").mkdir(parents=True, exist_ok=True)
    (wt_cache / ".pytest_cache" / "README.md").write_text("cache\n", encoding="utf-8")

    proc = subprocess.run(
        ["bash", "scripts/sync_and_clean.sh"],
        cwd=main_wt,
        capture_output=True,
        text=True,
        check=True,
    )

    assert wt_secret.exists()
    assert secret_file.read_text(encoding="utf-8") == "LLM_API_KEY=secret\n"
    assert "agent/.env" in proc.stdout
    assert not wt_cache.exists()


def test_sync_and_clean_refuses_to_overwrite_ignored_file_on_main_sync(
    tmp_path: Path,
) -> None:
    bare, main_wt = _init_fixture_repo(tmp_path)

    # Local main holds a gitignored file
    ignored_doc = main_wt / "docs" / "comp-mat" / "README.md"
    ignored_doc.parent.mkdir(parents=True, exist_ok=True)
    ignored_doc.write_text("LOCAL UNTRACKED IGNORED CONTENT\n", encoding="utf-8")

    # Remote main starts tracking the same path (via git add -f in another clone)
    other = tmp_path / "other_clone"
    _git(tmp_path, "clone", str(bare), str(other))
    _git(other, "config", "user.name", "Other")
    _git(other, "config", "user.email", "other@example.com")
    remote_doc = other / "docs" / "comp-mat" / "README.md"
    remote_doc.parent.mkdir(parents=True, exist_ok=True)
    remote_doc.write_text("REMOTE TRACKED CONTENT\n", encoding="utf-8")
    _git(other, "add", "-f", "docs/comp-mat/README.md")
    _git(other, "commit", "-m", "track docs/comp-mat/README.md")
    _git(other, "push", "origin", "main")

    proc = subprocess.run(
        ["bash", "scripts/sync_and_clean.sh"],
        cwd=main_wt,
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode != 0
    assert ignored_doc.read_text(encoding="utf-8") == "LOCAL UNTRACKED IGNORED CONTENT\n"


def test_sync_and_clean_dry_run_does_not_mutate_remote_tracking_refs(
    tmp_path: Path,
) -> None:
    bare, main_wt = _init_fixture_repo(tmp_path)
    before_sha = _git(main_wt, "rev-parse", "github/main").stdout.strip()

    # Push a new commit to remote main without fetching in main_wt
    other = tmp_path / "other_clone"
    _git(tmp_path, "clone", str(bare), str(other))
    _git(other, "config", "user.name", "Other")
    _git(other, "config", "user.email", "other@example.com")
    (other / "new.txt").write_text("hello\n", encoding="utf-8")
    _git(other, "add", "new.txt")
    _git(other, "commit", "-m", "remote advance")
    _git(other, "push", "origin", "main")

    subprocess.run(
        ["bash", "scripts/sync_and_clean.sh", "--dry-run"],
        cwd=main_wt,
        capture_output=True,
        text=True,
        check=True,
    )

    after_sha = _git(main_wt, "rev-parse", "github/main").stdout.strip()
    assert after_sha == before_sha
