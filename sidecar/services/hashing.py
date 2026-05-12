"""Source file hash tracking for incremental compilation."""

import hashlib
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

from db.database import get_connection


def compute_sha256(file_path: Path) -> str:
    """Compute SHA-256 hash of a file in 8KB chunks."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()


def has_changed(source_path: str, vault_root: Path) -> bool:
    """Return True if the source file is new or has changed since last processing."""
    full_path = vault_root / source_path
    if not full_path.exists():
        return False

    current_hash = compute_sha256(full_path)

    conn = get_connection()
    row = conn.execute(
        "SELECT sha256, status FROM source_hashes WHERE source_path = ?",
        (source_path,),
    ).fetchone()

    if row is None:
        return True  # new file
    if row["status"] == "failed":
        return True  # retry failed files
    return row["sha256"] != current_hash


def mark_processed(source_path: str, vault_root: Path, run_id: Optional[str] = None) -> None:
    """Record successful processing of a source file."""
    full_path = vault_root / source_path
    if not full_path.exists():
        return
    current_hash = compute_sha256(full_path)
    now = datetime.now(timezone.utc).isoformat()

    conn = get_connection()
    conn.execute(
        """INSERT INTO source_hashes (source_path, sha256, file_size, last_processed_at, last_run_id, status)
           VALUES (?, ?, ?, ?, ?, 'processed')
           ON CONFLICT(source_path) DO UPDATE SET
             sha256 = excluded.sha256,
             file_size = excluded.file_size,
             last_processed_at = excluded.last_processed_at,
             last_run_id = excluded.last_run_id,
             status = 'processed'""",
        (source_path, current_hash, full_path.stat().st_size, now, run_id),
    )
    conn.commit()


def mark_failed(source_path: str, run_id: Optional[str] = None) -> None:
    """Record failed processing — file will be retried on next run."""
    now = datetime.now(timezone.utc).isoformat()
    conn = get_connection()
    conn.execute(
        """INSERT INTO source_hashes (source_path, sha256, file_size, last_processed_at, last_run_id, status)
           VALUES (?, '', NULL, ?, ?, 'failed')
           ON CONFLICT(source_path) DO UPDATE SET
             status = 'failed',
             last_processed_at = excluded.last_processed_at,
             last_run_id = excluded.last_run_id""",
        (source_path, now, run_id),
    )
    conn.commit()


def get_changed_sources(source_paths: list[str], vault_root: Path) -> list[str]:
    """Filter a list of source paths to only those that have changed."""
    return [p for p in source_paths if has_changed(p, vault_root)]
