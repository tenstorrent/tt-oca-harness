# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

import importlib
import os
from pathlib import Path

import pytest
from sepvp import paths

pytestmark = pytest.mark.hostonly
pytest_plugins = ["pytester"]


def test_every_oca_image_in_the_rom_makefile_is_reachable():
    text = (paths.BOOTCODE_DIR / "Makefile").read_text()
    block = text.split("OCA_IMAGES := \\", 1)[1].split("\n\n", 1)[0]
    names = {line.strip(" \t\\") for line in block.splitlines() if line.strip(" \t\\")}
    files = {p.name for p in paths.OCA_IMAGE_PATHS.values()}
    assert {f"oca_{n}.bin" for n in names} <= files
    assert "invalid_class_key.bin" in files and "oca_smc_bundle.bin" in files


@pytest.fixture
def reloadable_paths(monkeypatch):
    """Let a test reload paths, then reload it again under the original environment."""
    yield monkeypatch
    monkeypatch.undo()
    importlib.reload(paths)


def test_logs_dir_env_override(reloadable_paths, tmp_path):
    reloadable_paths.setenv("SEPVP_LOGS_DIR", str(tmp_path))
    assert importlib.reload(paths).LOGS_DIR == tmp_path


def test_logs_dir_defaults_under_the_vp_dir(reloadable_paths):
    reloadable_paths.delenv("SEPVP_LOGS_DIR", raising=False)
    reloaded = importlib.reload(paths)
    assert reloaded.LOGS_DIR == reloaded.VP_DIR / "logs" / "sepvp"


@pytest.mark.skipif("SEPVP_LOGS_DIR" not in os.environ, reason="SEPVP_LOGS_DIR is not set")
def test_reload_tests_leave_logs_dir_at_the_environment_value():
    assert paths.LOGS_DIR == Path(os.environ["SEPVP_LOGS_DIR"])


def test_testlist_only_images_are_prebuilt_images():
    assert paths.TESTLIST_ONLY_IMAGES <= set(paths.OCA_IMAGE_PATHS)
    assert "signed" not in paths.TESTLIST_ONLY_IMAGES


@pytest.mark.parametrize("missing, outcome", [("toc_cap", "passed"), ("signed", "skipped")])
def test_oca_images_skips_only_for_a_missing_shared_image(
    pytester, monkeypatch, tmp_path, missing, outcome
):
    present = tmp_path / "present.bin"
    present.write_bytes(b"\0")
    images = {"signed": present, "toc_cap": present, missing: tmp_path / "absent.bin"}
    monkeypatch.setattr(paths, "OCA_IMAGE_PATHS", images)
    pytester.makeconftest('pytest_plugins = ["sepvp.pytest_plugin"]')
    pytester.makepyfile(
        "def test_images(oca_images):\n    assert set(oca_images) == {'signed', 'toc_cap'}\n"
    )
    pytester.runpytest("--no-build").assert_outcomes(**{outcome: 1})
