# Copyright 2017, Inderpreet Singh, All rights reserved.

import unittest

from controller.nested_persist import all_remote_descendants_done, apply_nested_persist_authority
from model import ModelFile


class TestAllRemoteDescendantsDone(unittest.TestCase):
    def test_deleted_file_counts_as_done(self):
        root = ModelFile("Top", True)
        leaf = ModelFile("leaf", False)
        leaf.remote_size = 100
        leaf.state = ModelFile.State.DELETED
        root.add_child(leaf)

        self.assertTrue(all_remote_descendants_done(root))

    def test_deleted_dirs_default_remote_only_children_are_skipped(self):
        root = ModelFile("Top", True)
        sub = ModelFile("Sub", True)
        sub.remote_size = 100
        sub.state = ModelFile.State.DELETED
        leaf = ModelFile("leaf", False)
        leaf.remote_size = 100
        leaf.state = ModelFile.State.DEFAULT
        sub.add_child(leaf)
        root.add_child(sub)

        self.assertTrue(all_remote_descendants_done(root))

    def test_default_remote_file_is_not_done(self):
        root = ModelFile("Top", True)
        leaf = ModelFile("leaf", False)
        leaf.remote_size = 100
        leaf.state = ModelFile.State.DEFAULT
        root.add_child(leaf)

        self.assertFalse(all_remote_descendants_done(root))

    def test_downloaded_file_is_done(self):
        root = ModelFile("Top", True)
        leaf = ModelFile("leaf", False)
        leaf.remote_size = 100
        leaf.state = ModelFile.State.DOWNLOADED
        root.add_child(leaf)

        self.assertTrue(all_remote_descendants_done(root))

    def test_local_only_file_is_done(self):
        """A remote-less child (local-only extra content) never blocks the rollup."""
        root = ModelFile("Top", True)
        leaf = ModelFile("leaf", False)
        leaf.remote_size = None
        leaf.state = ModelFile.State.DEFAULT
        root.add_child(leaf)

        self.assertTrue(all_remote_descendants_done(root))

    def test_no_children_is_done(self):
        root = ModelFile("Top", True)
        self.assertTrue(all_remote_descendants_done(root))


class TestApplyNestedPersistAuthority(unittest.TestCase):
    @staticmethod
    def _make_root_with_leaf(leaf_name="leaf", remote_size=100, local_size=None, state=ModelFile.State.DEFAULT):
        root = ModelFile("Top", True)
        leaf = ModelFile(leaf_name, False)
        leaf.remote_size = remote_size
        leaf.local_size = local_size
        leaf.state = state
        root.add_child(leaf)
        return root, leaf

    def test_keyed_local_absent_becomes_deleted(self):
        root, leaf = self._make_root_with_leaf(local_size=None)

        apply_nested_persist_authority(root, {"Top/leaf"}, set())

        self.assertEqual(ModelFile.State.DELETED, leaf.state)

    def test_keyed_local_absent_but_self_staged_stays_default(self):
        root, leaf = self._make_root_with_leaf(local_size=None)

        apply_nested_persist_authority(root, {"Top/leaf"}, {"Top/leaf"})

        self.assertEqual(ModelFile.State.DEFAULT, leaf.state)

    def test_keyed_local_absent_but_ancestor_staged_stays_default(self):
        root = ModelFile("Top", True)
        sub = ModelFile("Sub", True)
        leaf = ModelFile("leaf", False)
        leaf.remote_size = 100
        leaf.local_size = None
        sub.add_child(leaf)
        root.add_child(sub)

        apply_nested_persist_authority(root, {"Top/Sub/leaf"}, {"Top/Sub"})

        self.assertEqual(ModelFile.State.DEFAULT, leaf.state)

    def test_keyed_local_less_than_remote_stays_default(self):
        root, leaf = self._make_root_with_leaf(remote_size=100, local_size=50)

        apply_nested_persist_authority(root, {"Top/leaf"}, set())

        self.assertEqual(ModelFile.State.DEFAULT, leaf.state)

    def test_keyed_local_present_file_with_no_remote_size_becomes_downloaded(self):
        root, leaf = self._make_root_with_leaf(remote_size=None, local_size=50)

        apply_nested_persist_authority(root, {"Top/leaf"}, set())

        self.assertEqual(ModelFile.State.DOWNLOADED, leaf.state)

    def test_keyed_dir_all_descendants_done_becomes_downloaded(self):
        root = ModelFile("Top", True)
        sub = ModelFile("Sub", True)
        sub.local_size = 100
        leaf = ModelFile("leaf", False)
        leaf.remote_size = 100
        leaf.local_size = 100
        leaf.state = ModelFile.State.DOWNLOADED
        sub.add_child(leaf)
        root.add_child(sub)

        apply_nested_persist_authority(root, {"Top/Sub"}, set())

        self.assertEqual(ModelFile.State.DOWNLOADED, sub.state)

    def test_keyed_dir_partial_descendants_stays_default(self):
        root = ModelFile("Top", True)
        sub = ModelFile("Sub", True)
        sub.local_size = 100
        leaf_done = ModelFile("done", False)
        leaf_done.remote_size = 100
        leaf_done.local_size = 100
        leaf_done.state = ModelFile.State.DOWNLOADED
        leaf_pending = ModelFile("pending", False)
        leaf_pending.remote_size = 100
        leaf_pending.state = ModelFile.State.DEFAULT
        sub.add_child(leaf_done)
        sub.add_child(leaf_pending)
        root.add_child(sub)

        apply_nested_persist_authority(root, {"Top/Sub"}, set())

        self.assertEqual(ModelFile.State.DEFAULT, sub.state)

    def test_non_default_children_untouched(self):
        root = ModelFile("Top", True)
        downloading = ModelFile("downloading", False)
        downloading.remote_size = 100
        downloading.state = ModelFile.State.DOWNLOADING
        move_failed = ModelFile("stuck", False)
        move_failed.remote_size = 100
        move_failed.state = ModelFile.State.MOVE_FAILED
        root.add_child(downloading)
        root.add_child(move_failed)

        apply_nested_persist_authority(root, {"Top/downloading", "Top/stuck"}, set())

        self.assertEqual(ModelFile.State.DOWNLOADING, downloading.state)
        self.assertEqual(ModelFile.State.MOVE_FAILED, move_failed.state)

    def test_no_key_leaves_child_untouched(self):
        root, leaf = self._make_root_with_leaf(local_size=None)

        apply_nested_persist_authority(root, set(), set())

        self.assertEqual(ModelFile.State.DEFAULT, leaf.state)
