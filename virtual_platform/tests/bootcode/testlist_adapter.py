# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Convert SEP ROM testlist entries into sep-vp run inputs and judge the run."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import untrusted_signing_key
import yaml
from preloaded_test_programs import PROGRAMS
from sepvp.config import SMC_SRAM_DEFAULT_OFFSET, SimConfig
from sepvp.harness import SEP_STATUS_ERROR_RE
from sepvp.judges import judge
from testlist_loader import RomTestCase


@dataclass(frozen=True)
class BaseIni:
    otp: Path


_FUSE_MAP_DIR = Path(__file__).resolve().parents[1] / "fuse_maps"
BASE_INIS = {
    "secure": BaseIni(otp=_FUSE_MAP_DIR / "prod_secure.yaml"),
    "insecure": BaseIni(otp=_FUSE_MAP_DIR / "test_dev.yaml"),
}

# Fuse values that depend on a key generated on demand cannot be written in a testlist.
_EFUSE_PLACEHOLDERS = {
    "{untrusted_signing_key_digest}": untrusted_signing_key.digest_words,
}


def init_write_witness(address: int, value: int) -> str:
    """The line the model prints for one applied init write."""
    return f"[init_writes] 0x{address:x} = 0x{value:x}"


def materialize_fuse_map(testcase: RomTestCase, output_dir: Path) -> Path | None:
    """Layer a testcase's fuse overrides on its base profile map, or None if it has none."""
    if not testcase.efuse:
        return None
    if testcase.base_ini is None:
        raise ValueError(f"testcase {testcase.name!r} efuse needs a base_ini")

    base = yaml.safe_load(BASE_INIS[testcase.base_ini].otp.read_text()) or {}
    for field, value in testcase.efuse.items():
        produce = _EFUSE_PLACEHOLDERS.get(value) if isinstance(value, str) else None
        if produce is not None:
            base[field] = produce()
            continue
        base[field] = list(value) if isinstance(value, tuple) else value

    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"{testcase.name}.yaml"
    output.write_text(yaml.safe_dump(base, sort_keys=True))
    return output


def resolve_expect(
    testcase: RomTestCase, measurement: Mapping[str, str] | None
) -> tuple[tuple[str, ...], Mapping[str, int]]:
    """The entry's expected tokens and counts with computed measurement values substituted."""
    if testcase.measurement_golden is None:
        return testcase.expect, testcase.expect_counts
    if measurement is None:
        raise ValueError(
            f"testcase {testcase.name!r} declares measurement_golden but was given "
            "no computed measurement tokens"
        )
    expect = tuple(measurement.get(token, token) for token in testcase.expect)
    counts = {measurement.get(token, token): n for token, n in testcase.expect_counts.items()}
    return expect, counts


def build_sim_config(
    testcase: RomTestCase,
    bootcode_elf: Path,
    *,
    boot_image: Path | None = None,
    fuse_map: Path | None = None,
    smc_sram_image: Path | None = None,
) -> SimConfig:
    init_writes = []
    for name in testcase.preloaded_test_programs:
        init_writes.extend(PROGRAMS[name].init_writes())
    init_writes.extend((write.address, write.value) for write in testcase.init_writes)

    if testcase.image is None and boot_image is not None:
        raise ValueError(f"testcase {testcase.name!r} does not declare a boot image")
    if testcase.image is not None and boot_image is None:
        raise ValueError(f"testcase {testcase.name!r} requires image {testcase.image!r}")

    if (smc_sram_image is None) != (testcase.smc_sram_image is None):
        wanted = "requires" if testcase.smc_sram_image is not None else "does not declare"
        raise ValueError(f"testcase {testcase.name!r} {wanted} an SMC SRAM image")

    otp = None
    if testcase.base_ini is not None:
        otp = fuse_map if fuse_map is not None else BASE_INIS[testcase.base_ini].otp

    return SimConfig(
        name=testcase.name,
        elf=bootcode_elf,
        flash_image=boot_image,
        otp=otp,
        smc_sram_image=smc_sram_image,
        smc_sram_offset=testcase.smc_sram_offset if smc_sram_image is not None else None,
        boot=testcase.boot,
        rotate_update=testcase.rotate_update,
        recovery=testcase.recovery,
        boot_timeout=testcase.timeout,
        init_writes=init_writes,
    )


def sentinel_failure_matches(testcase: RomTestCase, error: Exception) -> bool:
    """Whether a judge failure is the one the testcase's xfail sentinel declares."""
    return (
        testcase.xfail_match is not None and re.search(testcase.xfail_match, str(error)) is not None
    )


def _smc_sram_judge_args(testcase: RomTestCase) -> tuple[int, int] | None:
    if testcase.smc_sram_image is None:
        return None
    low, high = testcase.smc_sram_source
    offset = (
        SMC_SRAM_DEFAULT_OFFSET if testcase.smc_sram_offset is None else testcase.smc_sram_offset
    )
    return high - low, offset


def run_testlist_case(
    testcase: RomTestCase,
    vp,
    bootcode_elf: Path,
    *,
    boot_image: Path | None = None,
    fuse_map: Path | None = None,
    smc_sram_image: Path | None = None,
    measurement: Mapping[str, str] | None = None,
) -> None:
    """Run one testcase and hold it to its declared console, status and device contract."""
    config = build_sim_config(
        testcase,
        bootcode_elf,
        boot_image=boot_image,
        fuse_map=fuse_map,
        smc_sram_image=smc_sram_image,
    )
    expect, expect_counts = resolve_expect(testcase, measurement)
    test = vp(config)

    if testcase.observation == "complete":
        result = test.run_to_completion(timeout=testcase.timeout)
        liveness = [init_write_witness(address, value) for address, value in config.init_writes]
        judge(
            result,
            expect=expect,
            forbid=testcase.forbid,
            expect_counts=expect_counts,
            terminal_token=testcase.terminal_token,
            expect_silence=testcase.expect_silence,
            liveness=liveness,
            expect_status=testcase.expect_status,
            forbid_status=testcase.forbid_status,
            spi_reads=testcase.spi_reads,
            spi_read_order=testcase.spi_read_order,
            expect_verdict=testcase.expect_verdict,
            smc_sram=_smc_sram_judge_args(testcase),
        )
        return

    test.spawn()
    errors = [SEP_STATUS_ERROR_RE, *(re.escape(token) for token in testcase.forbid)]
    if testcase.init_writes:
        final = testcase.init_writes[-1]
        witness = init_write_witness(final.address, final.value)
        test.expect(re.escape(witness), error_patterns=errors, timeout=testcase.timeout)

    for token in expect:
        test.expect(re.escape(token), error_patterns=errors, timeout=testcase.timeout)
    test.close()
