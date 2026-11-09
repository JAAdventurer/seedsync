# Copyright 2017, Inderpreet Singh, All rights reserved.

"""Persist authority for nested rows.

The nested counterpart of ModelBuilder._check_persist_authority: a nested
full_path in downloaded_file_names marks a row that was downloaded (its own
nested job finished, or it was deleted locally while downloaded), so once its
local copy is gone it reads DELETED rather than DEFAULT.
"""

from collections import deque

from model import ModelFile


def all_remote_descendants_done(model_file: ModelFile) -> bool:
    """Check whether every remote descendant file (not dir) of model_file is done.

    Done means Downloaded, or Deleted: a row the user deleted locally after
    downloading it doesn't hold its parent back. A Deleted dir's subtree is
    skipped, since its remote-only children are Default.
    """
    frontier: deque[ModelFile] = deque(model_file.iter_children())
    while frontier:
        child = frontier.popleft()
        if child.state == ModelFile.State.DELETED:
            continue
        if not child.is_dir and child.remote_size is not None and child.state != ModelFile.State.DOWNLOADED:
            return False
        frontier.extend(child.iter_children())
    return True


def apply_nested_persist_authority(root: ModelFile, downloaded_names: set[str], staged_names: set[str]) -> None:
    """Settle Default nested rows under root that persist says were downloaded.

    Walks bottom-up so a dir sees its children's final states. A row (or an
    ancestor) still in staging has no local presence but isn't deleted: it's
    mid-move, waiting for one after a restart, or a stopped partial.
    """
    order: list[ModelFile] = []
    frontier: deque[ModelFile] = deque(root.iter_children())
    while frontier:
        child = frontier.popleft()
        order.append(child)
        frontier.extend(child.iter_children())
    for child in reversed(order):
        if child.state != ModelFile.State.DEFAULT or child.full_path not in downloaded_names:
            continue
        if child.local_size is None:
            if not _is_staged(child, staged_names):
                child.state = ModelFile.State.DELETED
        elif child.is_dir:
            if all_remote_descendants_done(child):
                child.state = ModelFile.State.DOWNLOADED
        elif child.remote_size is None or child.local_size >= child.remote_size:
            child.state = ModelFile.State.DOWNLOADED


def _is_staged(model_file: ModelFile, staged_names: set[str]) -> bool:
    node = model_file
    while node.parent is not None:
        if node.full_path in staged_names:
            return True
        node = node.parent
    return False
