import pytest

from foodvision.data.object_store import REPO_ROOT, LocalObjectStore, UnsafeStorageRoot


def test_store_root_inside_repo_is_refused_except_ignored_data_dir():
    with pytest.raises(UnsafeStorageRoot):
        LocalObjectStore(REPO_ROOT / "images")
    with pytest.raises(UnsafeStorageRoot):
        LocalObjectStore(REPO_ROOT / "src")
    LocalObjectStore(REPO_ROOT / "data" / "images")  # git-ignored /data/


def test_object_keys_cannot_escape_root(tmp_path):
    store = LocalObjectStore(tmp_path / "store")
    with pytest.raises(UnsafeStorageRoot):
        store.write("../outside", b"x")


def test_write_read_remove(tmp_path):
    store = LocalObjectStore(tmp_path / "store")
    store.write("ab/abc", b"SYNTHETIC")
    assert store.read("ab/abc") == b"SYNTHETIC" and store.exists("ab/abc")
    store.remove("ab/abc")
    assert not store.exists("ab/abc")
    store.remove("ab/abc")  # idempotent
