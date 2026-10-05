# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Every testcase must hold for any BL1 build, so no expected value may encode the BL1 size.

The prebuilt images are packed again with BL1 grown by 16 bytes, as a compiler change grows
it. Each testcase must still pass its image checks and resolve, and no literal it carries may
equal a value that moved with BL1.
"""

import re
from pathlib import Path

import boot_images
import oca_repack
import pytest
import yaml
from sepvp import paths
from test_sep_rom_testlist import TESTCASES
from testlist_loader import IMAGE_FACTS

pytestmark = pytest.mark.hostonly

_PAD = 16
_BL1 = "../../dv/fw/tests/bl1_pass_test/build/bl1_pass_test.bin"
# Prebuilt images that are not configs/<stem>_image.yaml packed as is.
_BUNDLE_CONFIGS = {"smc_bundle": "oca_secure_boot_test.yaml"}
_DERIVED = {"invalid_class_key": ("oca_encrypted_boot_image.yaml", 1, "oca_secure_boot_test.yaml")}
_HEX_RE = re.compile(r"=0x([0-9a-fA-F]{8})\b")


def _rewrite_configs(directory: Path, bl1: Path) -> None:
    """Copy every packer config with BL1 replaced and combo configs pointing at the copies."""
    directory.mkdir(parents=True)
    for source in sorted(paths.BOOTCODE_CONFIGS.glob("*.yaml")):
        config = yaml.safe_load(source.read_text())
        if not isinstance(config, dict):
            continue
        for combo in config.get("combos") or []:
            combo["config"] = str(directory / Path(combo["config"]).name)
        for image in config.get("payload_images") or []:
            if image.get("path") == _BL1:
                image["path"] = str(bl1)
        (directory / source.name).write_text(yaml.safe_dump(config, sort_keys=False))


def _pack_prebuilt(configs: Path, out: Path) -> dict[str, Path]:
    images = {}
    for name, built in paths.OCA_IMAGE_PATHS.items():
        stem = Path(built).stem
        if name in _BUNDLE_CONFIGS:
            config = configs / _BUNDLE_CONFIGS[name]
        elif name in _DERIVED:
            base, combo, bundle = _DERIVED[name]
            data = yaml.safe_load((configs / base).read_text())
            data["combos"][combo]["config"] = str(configs / bundle)
            config = configs / f"{stem}_image.yaml"
            config.write_text(yaml.safe_dump(data, sort_keys=False))
        else:
            config = configs / f"{stem}_image.yaml"
        images[name] = oca_repack.pack(config, out / f"{stem}.bin", out / f"{stem}.log")
    return images


@pytest.fixture(scope="module")
def grown(tmp_path_factory):
    """Prebuilt images and packer configs whose BL1 is _PAD bytes longer than the build's."""
    if not paths.MANIFEST_VENV_PYTHON.is_file():
        pytest.skip("needs the manifest venv to repack the images; see tests/bootcode/README.md")
    missing = [n for n, p in paths.OCA_IMAGE_PATHS.items() if not Path(p).is_file()]
    if missing:
        pytest.skip(f"prebuilt images not present: {missing}")
    root = tmp_path_factory.mktemp("grown_bl1")
    bl1 = root / "bl1.bin"
    bl1.write_bytes((paths.BOOTCODE_DIR / _BL1).read_bytes() + bytes(_PAD))
    configs = root / "configs"
    _rewrite_configs(configs, bl1)
    images = _pack_prebuilt(configs, root / "images")
    built = boot_images.ImageFacts(paths.OCA_IMAGE_PATHS["signed"].read_bytes())
    moved = boot_images.ImageFacts(images["signed"].read_bytes())
    assert moved["primary.bl1_len"] == built["primary.bl1_len"] + _PAD, "BL1 was not replaced"
    return configs, images


def _facts(path: Path) -> dict[str, int]:
    facts = boot_images.ImageFacts(Path(path).read_bytes())
    values = {}
    for name in IMAGE_FACTS:
        try:
            values[name] = facts[name]
        except (AssertionError, ValueError, IndexError):
            continue
    return values


def _moved(before: Path, after: Path) -> dict[int, str]:
    """The values of facts that changed with BL1, keyed by their value in the built image."""
    old, new = _facts(before), _facts(after)
    return {value: name for name, value in old.items() if name in new and new[name] != value}


def _literals(testcase):
    """Each number the testcase states outright, with where it states it."""
    for token in (*testcase.expect, *testcase.forbid, *testcase.expect_counts):
        for value in _HEX_RE.findall(token):
            yield int(value, 16), f"token {token!r}", "image"
    for span in testcase.spi_reads:
        for bound in (span.low, span.high):
            yield bound, f"spi_reads span {span.name!r}", "image"
    for bound in testcase.smc_sram_source or ():
        yield bound, "smc_sram_source", "smc"
    for index, check in enumerate(testcase.image_asserts):
        for field in (check.field, check.toc_field):
            if field is not None:
                yield field.value, f"image_asserts[{index}] {field.name}", "image"
        if check.field is None and check.toc_field is None and check.decrypt_pad is None:
            for bound in (check.low, check.high):
                yield bound, f"image_asserts[{index}] range", "image"


_IMAGE_CASES = [
    case
    for case in TESTCASES
    if case.classification != "retired" and (case.image or case.smc_sram_image)
]


@pytest.mark.parametrize("testcase", _IMAGE_CASES, ids=lambda case: case.name)
def test_the_testcase_holds_for_a_longer_bl1(testcase, grown, tmp_path, monkeypatch):
    configs, images = grown
    built = grown_image = None
    if testcase.image is not None:
        built = boot_images.materialize_boot_image(
            testcase.image, paths.OCA_IMAGE_PATHS, tmp_path / "built"
        )
        with monkeypatch.context() as patch:
            patch.setattr(paths, "BOOTCODE_CONFIGS", configs)
            grown_image = boot_images.materialize_boot_image(
                testcase.image, images, tmp_path / "grown"
            )
        boot_images.check_image_asserts(testcase, grown_image, images)
    boot_images.resolve_case(testcase, grown_image, images)

    moved = {"image": {}, "smc": {}}
    if built is not None:
        moved["image"] = _moved(built, grown_image)
    if testcase.smc_sram_image is not None:
        moved["smc"] = _moved(
            paths.OCA_IMAGE_PATHS[testcase.smc_sram_image], images[testcase.smc_sram_image]
        )
    pinned = [
        f"{where} states 0x{value:x}, which is {moved[source][value]} of this build"
        for value, where, source in _literals(testcase)
        if type(value) is int and value in moved[source]
    ]
    assert not pinned, (
        f"{testcase.name} encodes the BL1 build; name the image fact instead:\n  "
        + "\n  ".join(pinned)
    )
