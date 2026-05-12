"""
Path normalization utilities.

All paths stored in frontmatter, graph.json, and SQLite must use forward slashes
regardless of operating system. Paths are stored relative to the Vanilla root
(the parent of both clean-vault and wiki-vault).

This module is the SINGLE source of truth for path normalization on the Python side.
A matching TypeScript implementation exists at src/api/paths.ts.
"""

import os
from pathlib import Path, PurePosixPath


def normalize_path(path: str) -> str:
    """
    Normalize a file path to use forward slashes.

    This is used on every path before storing to SQLite, frontmatter, or graph.json.

    Examples:
        >>> normalize_path("clean-vault\\raw\\paper.md")
        'clean-vault/raw/paper.md'
        >>> normalize_path("clean-vault/raw/paper.md")
        'clean-vault/raw/paper.md'
    """
    return path.replace("\\", "/")


def to_relative(absolute_path: str, vault_root: str) -> str:
    """
    Convert an absolute path to a vault-relative path with forward slashes.

    Args:
        absolute_path: The full path (e.g., C:\\Users\\User\\Vanilla\\clean-vault\\raw\\paper.md)
        vault_root: The Vanilla root directory (parent of both vaults)

    Returns:
        Relative path with forward slashes (e.g., clean-vault/raw/paper.md)

    Examples:
        >>> to_relative("C:\\\\Users\\\\User\\\\Vanilla\\\\clean-vault\\\\raw\\\\paper.md", "C:\\\\Users\\\\User\\\\Vanilla")
        'clean-vault/raw/paper.md'
    """
    try:
        rel = os.path.relpath(absolute_path, vault_root)
    except ValueError:
        # On Windows, relpath raises ValueError if paths are on different drives
        rel = absolute_path
    return normalize_path(rel)


def to_absolute(relative_path: str, vault_root: str) -> str:
    """
    Convert a vault-relative path back to an absolute OS path.

    Args:
        relative_path: Forward-slash relative path (e.g., clean-vault/raw/paper.md)
        vault_root: The Vanilla root directory

    Returns:
        Absolute path using OS-native separators
    """
    return str(Path(vault_root) / PurePosixPath(relative_path))


def is_clean_vault_path(relative_path: str) -> bool:
    """Check if a relative path belongs to the clean vault."""
    normalized = normalize_path(relative_path)
    return normalized.startswith("clean-vault/")


def is_wiki_vault_path(relative_path: str) -> bool:
    """Check if a relative path belongs to the wiki vault."""
    normalized = normalize_path(relative_path)
    return normalized.startswith("wiki-vault/")
