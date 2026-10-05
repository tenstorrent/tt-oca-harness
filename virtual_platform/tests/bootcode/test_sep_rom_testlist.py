# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""SEP boot-ROM testcases declared by the per-family TOML testlists."""

import boot_image_mutations
import boot_images
import pytest
import testlist_adapter
import testlist_audit
from preloaded_test_programs import PROGRAMS
from sepvp.judges import JudgeError, UnjudgeableError
from testlist_loader import load_testlist_dir

TESTLIST_DIR = boot_image_mutations.testlist_dir()
TESTCASES = load_testlist_dir(
    TESTLIST_DIR,
    known_programs=frozenset(PROGRAMS),
    known_images=boot_images.known_images(),
)


def _run(rom_testcase, vp, bootcode_elf, oca_images, tmp_path):
    missing = boot_images.missing_prebuilt(rom_testcase, oca_images)
    if missing:
        pytest.skip(f"prebuilt images not present: {missing}; build them or drop --no-build")
    boot_image = None
    if rom_testcase.image is not None:
        boot_image = boot_images.materialize_boot_image(rom_testcase.image, oca_images, tmp_path)
        boot_images.check_image_asserts(rom_testcase, boot_image, oca_images)
    testcase = boot_images.resolve_case(rom_testcase, boot_image, oca_images)
    testlist_adapter.run_testlist_case(
        testcase,
        vp,
        bootcode_elf,
        boot_image=boot_image,
        fuse_map=testlist_adapter.materialize_fuse_map(testcase, tmp_path),
        smc_sram_image=boot_images.materialize_smc_sram_image(testcase, oca_images, tmp_path),
    )


def _pytest_case(testcase):
    marks = [getattr(pytest.mark, marker) for marker in testcase.pytest_markers]
    if testcase.xfail_reason is not None:
        marks.append(
            pytest.mark.xfail(strict=True, raises=JudgeError, reason=testcase.xfail_reason)
        )
    return pytest.param(testcase, id=testcase.name, marks=marks)


@pytest.mark.bootcode
@pytest.mark.parametrize(
    "rom_testcase",
    [_pytest_case(c) for c in TESTCASES],
)
def test_sep_rom_testlist(rom_testcase, vp, bootcode_elf, oca_images, tmp_path):
    try:
        _run(rom_testcase, vp, bootcode_elf, oca_images, tmp_path)
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


def _resolved(testcase, oca_images, tmp_path):
    """The testcase with its image facts filled in from the image it boots."""
    if testlist_adapter.unresolved(testcase) is None:
        return testcase
    image = None
    if testcase.image is not None:
        image = boot_images.materialize_boot_image(
            testcase.image, oca_images, tmp_path / testcase.name
        )
    return boot_images.resolve_case(testcase, image, oca_images)


@pytest.mark.bootcode
def test_no_testcase_passes_for_the_wrong_reason(vp, bootcode_elf, oca_images, tmp_path):
    runs = []

    def recording_vp(config):
        runs.append(vp(config))
        return runs[-1]

    golden = next(c for c in TESTCASES if c.name == testlist_audit.GOLDEN_TESTCASE)
    golden_dir = tmp_path / "golden_run"
    golden_dir.mkdir()
    _run(golden, recording_vp, bootcode_elf, oca_images, golden_dir)
    golden_output = runs[-1].log_path.read_text(errors="replace")

    findings = [
        finding
        for testcase in TESTCASES
        for finding in testlist_audit.audit(
            _resolved(testcase, oca_images, tmp_path), golden_output
        )
        if not (
            finding.kind == "shares_golden_stimulus"
            and finding.testcase in testlist_audit.SHARES_GOLDEN_STIMULUS
        )
    ]

    assert findings == [], "\n".join(f"{f.testcase}: {f.kind}: {f.detail}" for f in findings)
