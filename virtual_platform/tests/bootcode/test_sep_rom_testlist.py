# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""SEP boot-ROM testcases declared by the per-family TOML testlists."""

import boot_image_mutations
import boot_images
import pytest
import testlist_adapter
from preloaded_test_programs import PROGRAMS
from sepvp.judges import JudgeError, UnjudgeableError
from testlist_loader import RUNNABLE_BLOCKED, load_testlist_dir

TESTLIST_DIR = boot_image_mutations.testlist_dir()
TESTCASES = load_testlist_dir(
    TESTLIST_DIR,
    known_programs=frozenset(PROGRAMS),
    known_images=boot_images.known_images(),
)


def _pytest_case(testcase):
    marks = [getattr(pytest.mark, marker) for marker in testcase.pytest_markers]
    if testcase.classification in RUNNABLE_BLOCKED:
        reason = next(
            (
                m.removeprefix("Blocked:").strip()
                for m in testcase.markers
                if m.startswith("Blocked:")
            ),
            testcase.classification,
        )
        marks.append(pytest.mark.skip(reason=reason))
    if testcase.xfail_reason is not None:
        marks.append(
            pytest.mark.xfail(strict=True, raises=JudgeError, reason=testcase.xfail_reason)
        )
    return pytest.param(testcase, id=testcase.name, marks=marks)


@pytest.mark.bootcode
@pytest.mark.parametrize(
    "rom_testcase",
    [_pytest_case(c) for c in TESTCASES if c.classification != "retired"],
)
def test_sep_rom_testlist(rom_testcase, vp, bootcode_elf, oca_images, tmp_path):
    missing = boot_images.missing_prebuilt(rom_testcase, oca_images)
    if missing:
        pytest.skip(f"prebuilt images not present: {missing}; build them or drop --no-build")
    boot_image = None
    if rom_testcase.image is not None:
        boot_image = boot_images.materialize_boot_image(rom_testcase.image, oca_images, tmp_path)
        boot_images.check_image_asserts(rom_testcase, boot_image, oca_images)
    testcase = boot_images.resolve_case(rom_testcase, boot_image, oca_images)
    try:
        testlist_adapter.run_testlist_case(
            testcase,
            vp,
            bootcode_elf,
            boot_image=boot_image,
            fuse_map=testlist_adapter.materialize_fuse_map(testcase, tmp_path),
            smc_sram_image=boot_images.materialize_smc_sram_image(testcase, oca_images, tmp_path),
        )
    except UnjudgeableError as error:
        # An xfail(raises=JudgeError) sentinel must not absorb an output-provenance failure.
        pytest.fail(f"{rom_testcase.name} cannot be judged: {error}", pytrace=False)
    except JudgeError as error:
        # A sentinel passes as XFAIL only for its declared failure; any other judge failure is real.
        if rom_testcase.xfail_reason is None or testlist_adapter.sentinel_failure_matches(
            rom_testcase, error
        ):
            raise
        pytest.fail(
            f"{rom_testcase.name} sentinel failed for an unexpected reason: expected "
            f"/{rom_testcase.xfail_match}/, got: {error}",
            pytrace=False,
        )
