"""Tests for kani API key management."""

from __future__ import annotations

import pytest

from kani.api_keys import generate_key, has_keys, list_keys, remove_key, validate_key


@pytest.fixture(autouse=True)
def isolate_data_dir(tmp_path, monkeypatch):
    """Redirect data dir to tmp so tests don't touch real keys."""
    monkeypatch.setenv("KANI_DATA_DIR", str(tmp_path))


class TestApiKeyLifecycle:
    def test_no_keys_initially(self):
        assert has_keys() is False
        assert list_keys() == []

    def test_generate_and_validate(self):
        raw = generate_key("test-key")
        assert raw.startswith("kani-")
        assert has_keys() is True
        assert validate_key(raw) is True

    def test_invalid_key_rejected(self):
        generate_key("test-key")
        assert validate_key("bogus-key") is False

    def test_list_keys(self):
        generate_key("alpha")
        generate_key("beta")
        entries = list_keys()
        assert len(entries) == 2
        names = {e.name for e in entries}
        assert names == {"alpha", "beta"}

    def test_remove_by_name(self):
        raw = generate_key("removable")
        assert remove_key("removable") is True
        assert validate_key(raw) is False
        assert has_keys() is False

    def test_remove_by_prefix(self):
        raw = generate_key("prefixed")
        prefix = raw[:8]
        assert remove_key(prefix) is True
        assert validate_key(raw) is False

    def test_remove_nonexistent(self):
        assert remove_key("nope") is False

    def test_multiple_keys_independent(self):
        raw1 = generate_key("key1")
        raw2 = generate_key("key2")
        assert validate_key(raw1) is True
        assert validate_key(raw2) is True

        remove_key("key1")
        assert validate_key(raw1) is False
        assert validate_key(raw2) is True
