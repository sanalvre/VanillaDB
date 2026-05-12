"""
Git-based vault sync service.

Uses subprocess to drive git — no Python git library needed.
The vault root becomes a git repo; users point it at any remote
(GitHub, GitLab, Gitea, Codeberg, self-hosted, etc.)

Operations:
  - init_repo: git init + .gitignore if not already tracked
  - set_remote: update or add origin remote URL
  - get_status: last commit, dirty files, ahead/behind count
  - push: stage all + commit (if dirty) + push origin main
  - pull: git pull --rebase origin main
"""

import subprocess
import shutil
import time
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Files/dirs to exclude from the vault repo
_GITIGNORE_TEMPLATE = """\
# VanillaDB generated
.staging/
__pycache__/
*.pyc
.DS_Store
Thumbs.db
"""


def _git(args: list[str], cwd: str, check: bool = True) -> subprocess.CompletedProcess:
    """Run a git command in the given directory."""
    if not shutil.which("git"):
        raise RuntimeError("git is not installed or not on PATH")
    return subprocess.run(
        ["git"] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=check,
        timeout=60,
    )


def init_repo(vault_root: str) -> dict:
    """
    Ensure vault_root is a git repo. Idempotent.
    Creates .gitignore if missing.
    Returns {"initialized": bool, "already_existed": bool}
    """
    root = Path(vault_root)
    git_dir = root / ".git"
    already = git_dir.exists()

    if not already:
        _git(["init", "-b", "main"], cwd=str(root))
        logger.info("Initialized git repo at %s", root)

    # Write .gitignore if missing
    gitignore = root / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text(_GITIGNORE_TEMPLATE, encoding="utf-8")

    return {"initialized": True, "already_existed": already}


def set_remote(vault_root: str, remote_url: str) -> dict:
    """
    Set or update the origin remote URL.
    Returns {"success": bool, "error": str|None}
    """
    cwd = vault_root
    try:
        # Check if origin exists
        result = _git(["remote", "get-url", "origin"], cwd=cwd, check=False)
        if result.returncode == 0:
            _git(["remote", "set-url", "origin", remote_url], cwd=cwd)
        else:
            _git(["remote", "add", "origin", remote_url], cwd=cwd)
        return {"success": True, "error": None}
    except subprocess.CalledProcessError as e:
        return {"success": False, "error": e.stderr.strip()}
    except RuntimeError as e:
        return {"success": False, "error": str(e)}


def get_status(vault_root: str) -> dict:
    """
    Return sync status for the vault.

    Returns:
        {
          "is_repo": bool,
          "has_remote": bool,
          "remote_url": str | None,
          "last_commit_hash": str | None,
          "last_commit_message": str | None,
          "last_commit_time": int | None,  # unix timestamp
          "dirty_files": int,
          "ahead": int,
          "behind": int,
          "branch": str | None,
          "error": str | None,
        }
    """
    cwd = vault_root
    git_dir = Path(vault_root) / ".git"

    if not git_dir.exists():
        return {
            "is_repo": False,
            "has_remote": False,
            "remote_url": None,
            "last_commit_hash": None,
            "last_commit_message": None,
            "last_commit_time": None,
            "dirty_files": 0,
            "ahead": 0,
            "behind": 0,
            "branch": None,
            "error": None,
        }

    try:
        # Branch name
        branch_result = _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=cwd, check=False)
        branch = branch_result.stdout.strip() if branch_result.returncode == 0 else "main"

        # Remote URL
        remote_result = _git(["remote", "get-url", "origin"], cwd=cwd, check=False)
        has_remote = remote_result.returncode == 0
        remote_url = remote_result.stdout.strip() if has_remote else None

        # Last commit
        log_result = _git(
            ["log", "-1", "--format=%H%n%s%n%ct"], cwd=cwd, check=False
        )
        last_hash = last_msg = last_time = None
        if log_result.returncode == 0 and log_result.stdout.strip():
            parts = log_result.stdout.strip().split("\n", 2)
            last_hash = parts[0] if len(parts) > 0 else None
            last_msg = parts[1] if len(parts) > 1 else None
            last_time = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None

        # Dirty files (unstaged + staged)
        status_result = _git(["status", "--porcelain"], cwd=cwd, check=False)
        dirty = len([l for l in status_result.stdout.splitlines() if l.strip()]) if status_result.returncode == 0 else 0

        # Ahead/behind (only if remote exists and has been fetched)
        ahead = behind = 0
        if has_remote and last_hash:
            ab_result = _git(
                ["rev-list", "--left-right", "--count", f"HEAD...origin/{branch}"],
                cwd=cwd,
                check=False,
            )
            if ab_result.returncode == 0 and ab_result.stdout.strip():
                parts = ab_result.stdout.strip().split()
                if len(parts) == 2:
                    ahead, behind = int(parts[0]), int(parts[1])

        return {
            "is_repo": True,
            "has_remote": has_remote,
            "remote_url": remote_url,
            "last_commit_hash": last_hash[:8] if last_hash else None,
            "last_commit_message": last_msg,
            "last_commit_time": last_time,
            "dirty_files": dirty,
            "ahead": ahead,
            "behind": behind,
            "branch": branch,
            "error": None,
        }

    except Exception as e:
        logger.exception("git status failed")
        return {
            "is_repo": True,
            "has_remote": False,
            "remote_url": None,
            "last_commit_hash": None,
            "last_commit_message": None,
            "last_commit_time": None,
            "dirty_files": 0,
            "ahead": 0,
            "behind": 0,
            "branch": None,
            "error": str(e),
        }


def push(vault_root: str, message: Optional[str] = None) -> dict:
    """
    Stage all changes, commit (if dirty), push to origin.

    Returns {"success": bool, "committed": bool, "pushed": bool, "error": str|None}
    """
    cwd = vault_root
    committed = pushed = False

    try:
        # Ensure repo exists
        if not (Path(vault_root) / ".git").exists():
            init_repo(vault_root)

        # Stage everything
        _git(["add", "-A"], cwd=cwd)

        # Check if there's anything to commit
        status = _git(["status", "--porcelain"], cwd=cwd)
        if status.stdout.strip():
            commit_msg = message or f"Vault sync — {time.strftime('%Y-%m-%d %H:%M')}"
            _git(["commit", "-m", commit_msg], cwd=cwd)
            committed = True

        # Check if remote exists
        remote = _git(["remote", "get-url", "origin"], cwd=cwd, check=False)
        if remote.returncode != 0:
            return {
                "success": False,
                "committed": committed,
                "pushed": False,
                "error": "No remote configured — add a remote URL in Settings → Sync",
            }

        # Get current branch
        branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=cwd).stdout.strip()

        # Push (set upstream on first push)
        push_result = _git(
            ["push", "--set-upstream", "origin", branch], cwd=cwd, check=False
        )
        if push_result.returncode == 0:
            pushed = True
        else:
            return {
                "success": False,
                "committed": committed,
                "pushed": False,
                "error": push_result.stderr.strip() or "Push failed",
            }

        return {"success": True, "committed": committed, "pushed": pushed, "error": None}

    except subprocess.CalledProcessError as e:
        return {"success": False, "committed": committed, "pushed": pushed, "error": e.stderr.strip()}
    except Exception as e:
        logger.exception("git push failed")
        return {"success": False, "committed": committed, "pushed": pushed, "error": str(e)}


def pull(vault_root: str) -> dict:
    """
    Pull latest changes from origin (rebase strategy to avoid merge commits).

    Returns {"success": bool, "files_changed": int, "error": str|None}
    """
    cwd = vault_root
    try:
        if not (Path(vault_root) / ".git").exists():
            return {"success": False, "files_changed": 0, "error": "Not a git repo — push first to initialise"}

        remote = _git(["remote", "get-url", "origin"], cwd=cwd, check=False)
        if remote.returncode != 0:
            return {"success": False, "files_changed": 0, "error": "No remote configured"}

        branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=cwd).stdout.strip()
        result = _git(["pull", "--rebase", "origin", branch], cwd=cwd, check=False)

        if result.returncode != 0:
            return {"success": False, "files_changed": 0, "error": result.stderr.strip() or "Pull failed"}

        # Count changed files from output
        changed = 0
        for line in result.stdout.splitlines():
            if "file" in line and ("changed" in line or "insertion" in line or "deletion" in line):
                try:
                    changed = int(line.strip().split()[0])
                except (ValueError, IndexError):
                    pass

        return {"success": True, "files_changed": changed, "error": None}

    except subprocess.CalledProcessError as e:
        return {"success": False, "files_changed": 0, "error": e.stderr.strip()}
    except Exception as e:
        logger.exception("git pull failed")
        return {"success": False, "files_changed": 0, "error": str(e)}
