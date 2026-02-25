"""Tests for capture_store.py."""

import os
import tempfile

import pytest

from sigrok_logicanalyzer_mcp.capture_store import CaptureStore, CaptureNotFoundError


def test_new_capture_returns_incrementing_ids():
    store = CaptureStore()
    try:
        id1, path1 = store.new_capture()
        id2, path2 = store.new_capture()

        assert id1 == "cap_001"
        assert id2 == "cap_002"
        assert path1.endswith("cap_001.sr")
        assert path2.endswith("cap_002.sr")
    finally:
        store.cleanup()


def test_get_existing_capture():
    store = CaptureStore()
    try:
        cap_id, path = store.new_capture(description="test capture")
        info = store.get(cap_id)

        assert info.capture_id == cap_id
        assert info.file_path == path
        assert info.description == "test capture"
        assert info.created_at > 0
    finally:
        store.cleanup()


def test_get_missing_capture_raises():
    store = CaptureStore()
    try:
        with pytest.raises(CaptureNotFoundError, match="cap_999"):
            store.get("cap_999")
    finally:
        store.cleanup()


def test_list_captures_empty():
    store = CaptureStore()
    try:
        assert store.list_captures() == []
    finally:
        store.cleanup()


def test_list_captures_with_entries():
    store = CaptureStore()
    try:
        store.new_capture(description="first")
        cap_id2, path2 = store.new_capture(description="second")

        # Create a fake file for the second capture
        with open(path2, "wb") as f:
            f.write(b"fake data")

        caps = store.list_captures()
        assert len(caps) == 2
        assert caps[0]["id"] == "cap_001"
        assert caps[0]["size_bytes"] == 0  # no file created
        assert caps[1]["id"] == "cap_002"
        assert caps[1]["size_bytes"] == 9
        assert caps[1]["description"] == "second"
    finally:
        store.cleanup()


def test_cleanup_removes_directory():
    store = CaptureStore()
    base_dir = store.base_dir
    assert os.path.exists(base_dir)

    store.cleanup()
    assert not os.path.exists(base_dir)


def test_custom_base_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        custom_dir = os.path.join(tmpdir, "my_captures")
        store = CaptureStore(base_dir=custom_dir)

        assert os.path.exists(custom_dir)
        cap_id, path = store.new_capture()
        assert path.startswith(custom_dir)

        # cleanup should not remove a user-provided directory
        store.cleanup()
        assert os.path.exists(custom_dir)


def test_cache_decode_and_retrieve():
    store = CaptureStore()
    try:
        cap_id, _ = store.new_capture()
        raw_output = "i2c-1: Start\ni2c-1: Data write: FF\n"
        cache_path = store.cache_decode(cap_id, "i2c", raw_output)

        assert os.path.exists(cache_path)
        assert cache_path.endswith("cap_001_i2c_raw.txt")

        cached = store.get_cached_decode(cap_id, "i2c")
        assert cached == raw_output
    finally:
        store.cleanup()


def test_cache_decode_miss():
    store = CaptureStore()
    try:
        cap_id, _ = store.new_capture()
        assert store.get_cached_decode(cap_id, "spi") is None
        assert store.get_cached_decode("cap_999", "i2c") is None
    finally:
        store.cleanup()
