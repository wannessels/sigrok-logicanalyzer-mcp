"""Shared fixtures for integration tests."""

import os
import shutil

import pytest

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


@pytest.fixture
def fixtures_dir():
    return FIXTURES_DIR


def has_sigrok_cli():
    return shutil.which("sigrok-cli") is not None


skip_no_sigrok = pytest.mark.skipif(
    not has_sigrok_cli(), reason="sigrok-cli not installed"
)
