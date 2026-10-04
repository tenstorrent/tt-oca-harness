# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

import pytest
import testlist_adapter
import yaml
from preloaded_test_programs import PROGRAMS
from sepvp.judges import JudgeError
from sepvp.run_result import RunResult, StopReason
from testlist_loader import load_testlist

pytestmark = pytest.mark.hostonly

_ENTRY = """
[[testcase]]
name = "case"
family = "warm_reset"
classification = "partial"
image = "signed"
base_ini = "secure"
boot = "primary"
expect = ["WARM_JUMP_OK", "{{measurement_golden}}"]
expect_verdict = "PASSED"
expect_counts = {{ "{{measurement_golden}}" = 1 }}
preloaded_test_programs = ["warm_jump"]
init_writes = [{{ address = 0x10802038, value = 0xC0030000 }}]
efuse = {{ class_key = [1, 2, 3, 4, 0, 0, 0, 0] }}
measurement_golden = {{ slot = "primary", lc_state = 0x1, demotion_decision = 0x2, secure_boot = 1, sboot_dis = 0 }}
{extra}
"""


def _case(tmp_path, extra=""):
    path = tmp_path / "warm_reset.toml"
    path.write_text(_ENTRY.format(extra=extra))
    return load_testlist(path, known_programs=frozenset(PROGRAMS), known_images={"signed"})[0]


def test_programs_precede_the_entry_init_writes(tmp_path):
    case = _case(tmp_path)
    config = testlist_adapter.build_sim_config(
        case, tmp_path / "rom.elf", boot_image=tmp_path / "i.bin"
    )
    program = PROGRAMS["warm_jump"]
    assert config.init_writes[-1] == (0x10802038, 0xC0030000)
    assert config.init_writes[: len(program.words)] == program.init_writes()
    assert config.flash_image == tmp_path / "i.bin"


def test_fuse_overrides_layer_on_the_base_profile(tmp_path):
    fuse_map = testlist_adapter.materialize_fuse_map(_case(tmp_path), tmp_path)
    data = yaml.safe_load(fuse_map.read_text())
    assert data["class_key"] == [1, 2, 3, 4, 0, 0, 0, 0]
    assert data["lc_state"] == "PROD"


def test_secure_profile_leaves_the_secrets_unlocked_at_power_on():
    otp = yaml.safe_load(testlist_adapter.BASE_INIS["secure"].otp.read_text())
    assert otp["locks_lo"] == 0


def test_measurement_tokens_are_substituted(tmp_path):
    case = _case(tmp_path)
    expect, counts = testlist_adapter.resolve_expect(
        case, {"{measurement_golden}": "BL0S_BOOT_PCR=AB"}
    )
    assert expect[-1] == "BL0S_BOOT_PCR=AB" and counts == {"BL0S_BOOT_PCR=AB": 1}


def test_measurement_needs_computed_tokens(tmp_path):
    with pytest.raises(ValueError, match="measurement_golden"):
        testlist_adapter.resolve_expect(_case(tmp_path), None)


def test_expect_without_a_measurement_spec_passes_through(tmp_path):
    path = tmp_path / "warm_reset.toml"
    path.write_text(
        '[[testcase]]\nname = "plain"\nfamily = "warm_reset"\nclassification = "partial"\n'
        'expect = ["GO!"]\nexpect_counts = { "GO!" = 1 }\nexpect_verdict = "PASSED"\n'
    )
    case = load_testlist(path)[0]
    assert testlist_adapter.resolve_expect(case, None) == (("GO!",), {"GO!": 1})


def test_image_and_smc_image_must_match_the_entry(tmp_path):
    case = _case(tmp_path)
    with pytest.raises(ValueError, match="requires image"):
        testlist_adapter.build_sim_config(case, tmp_path / "rom.elf")
    with pytest.raises(ValueError, match="does not declare an SMC SRAM image"):
        testlist_adapter.build_sim_config(
            case, tmp_path / "rom.elf", boot_image=tmp_path / "i.bin", smc_sram_image=tmp_path / "s"
        )


def test_streaming_witness_matches_the_unpadded_model_format():
    assert (
        testlist_adapter.init_write_witness(0x10802038, 0xC0) == "[init_writes] 0x10802038 = 0xc0"
    )


def test_recovery_reaches_the_sim_config(tmp_path):
    case = _case(tmp_path, "recovery = true")
    config = testlist_adapter.build_sim_config(
        case, tmp_path / "rom.elf", boot_image=tmp_path / "i.bin"
    )
    assert config.recovery is True
    assert config.boot == "primary"


def test_recovery_is_off_by_default(tmp_path):
    config = testlist_adapter.build_sim_config(
        _case(tmp_path), tmp_path / "rom.elf", boot_image=tmp_path / "i.bin"
    )
    assert config.recovery is False


_SENTINEL_EXTRA = (
    'xfail_reason = "DV B7: x"\nxfail_match = "forbidden status present: \'INFO 0x0055\'"'
)


def test_sentinel_accepts_the_declared_failure(tmp_path):
    case = _case(tmp_path, _SENTINEL_EXTRA)
    error = JudgeError("forbidden status present: 'INFO 0x0055' in the console")
    assert testlist_adapter.sentinel_failure_matches(case, error)


def test_sentinel_rejects_a_different_failure(tmp_path):
    case = _case(tmp_path, _SENTINEL_EXTRA)
    assert not testlist_adapter.sentinel_failure_matches(
        case, JudgeError("firmware reported FAILED")
    )


class _CompletedRun:
    def __init__(self, output):
        self.output = output

    def run_to_completion(self, timeout):
        return RunResult(
            output=self.output,
            stop_reason=StopReason.FIRMWARE_VERDICT,
            duration=0.1,
            exit_code=None,
            signal=None,
            firmware_verdict="PASSED",
            timed_out=False,
            harness_terminated=True,
        )


_SEEDED = """
[[testcase]]
name = "seeded"
family = "platform_gating"
classification = "partial"
init_writes = [{ address = 0x4000B800, value = 0x112 }]
expect = ["GO!"]
expect_verdict = "PASSED"
"""
_BOOT = "[SIM_OUT] - GO!\n[VP] SIMULATION OF THE TEST PASSED\n"


@pytest.mark.parametrize(
    "output, passes",
    [(f"[init_writes] 0x4000b800 = 0x112\n{_BOOT}", True), (_BOOT, False)],
)
def test_a_complete_run_needs_the_init_write_witness(tmp_path, output, passes):
    path = tmp_path / "platform_gating.toml"
    path.write_text(_SEEDED)
    (case,) = load_testlist(path)

    def run():
        testlist_adapter.run_testlist_case(
            case, lambda config: _CompletedRun(output), tmp_path / "rom.elf"
        )

    if passes:
        run()
    else:
        with pytest.raises(JudgeError, match="missing liveness witness"):
            run()
