"""Folder tree of the library.

Folders come from two places (see ``LibraryDB.folders``): Zotero collections,
which can be nested and are mirrored read-only, and the user's own folders,
which are flat. The helpers here answer the questions the library view asks
of that list.
"""
from __future__ import annotations

from typing import Sequence

from .library_db import FolderRow


def tree(folders: Sequence[FolderRow]) -> list[tuple[FolderRow, int]]:
    """Folders in display order with their depth: every folder is followed by
    its sub-folders. A folder whose parent is missing is shown at top level."""
    ids = {f.id for f in folders}
    children: dict[str, list[FolderRow]] = {}
    for f in folders:
        children.setdefault(f.parent if f.parent in ids else "", []).append(f)

    ordered: list[tuple[FolderRow, int]] = []
    seen: set[str] = set()

    def walk(parent: str, depth: int) -> None:
        for f in children.get(parent, []):
            if f.id in seen:        # a parent loop must not hang the app
                continue
            seen.add(f.id)
            ordered.append((f, depth))
            walk(f.id, depth + 1)

    walk("", 0)
    # Folders only reachable through a loop still get listed.
    ordered += [(f, 0) for f in folders if f.id not in seen]
    return ordered


def members(folders: Sequence[FolderRow], folder_id: str) -> set[str]:
    """Papers in a folder or in any of its sub-folders."""
    by_parent: dict[str, list[FolderRow]] = {}
    for f in folders:
        by_parent.setdefault(f.parent, []).append(f)
    keys: set[str] = set()
    seen: set[str] = set()
    todo = [f for f in folders if f.id == folder_id]
    while todo:
        f = todo.pop()
        if f.id in seen:
            continue
        seen.add(f.id)
        keys |= f.keys
        todo.extend(by_parent.get(f.id, []))
    return keys


def filed(folders: Sequence[FolderRow]) -> set[str]:
    """Papers that are in at least one folder."""
    return set().union(*(f.keys for f in folders))
