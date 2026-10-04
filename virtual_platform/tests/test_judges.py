# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

import importlib
import importlib.util

import pytest
from sepvp.run_result import RunResult, StopReason

pytestmark = pytest.mark.hostonly


def _judges():
    assert importlib.util.find_spec("sepvp.judges") is not None
    return importlib.import_module("sepvp.judges")


def _result(
    output,
    *,
    reason=StopReason.FIRMWARE_VERDICT,
    verdict="PASSED",
    timed_out=False,
):
    return RunResult(
        output=output,
        stop_reason=reason,
        duration=0.1,
        exit_code=None,
        signal=None,
        firmware_verdict=verdict,
        timed_out=timed_out,
        harness_terminated=True,
    )


def test_extracts_tagged_and_bare_console_without_status_or_model_noise():
    judges = _judges()
    raw = """
SystemC 3.0.2-Accellera
[1 ns] [INFO 1] [och_sep_ss1.bus] - model noise
och_sep_ss: smc_global window [0x40000000, 0x400fffff]
smc_global: staged 4096 bytes at offset 0x2000
och_sep_ss: SEP_GLOBAL_BASE_ADDR 0x10000000
[2 ns] [INFO 2] [SIM_OUT] - FIRST
BL0 INFO     0x0031 SEP_MSG_PLL_CLK_INIT
FIRMWARE Copyright TOKEN
SECOND
[VP] SIMULATION OF THE TEST PASSED
"""

    assert judges.console_tokens(raw) == ["FIRST", "FIRMWARE Copyright TOKEN", "SECOND"]


def test_ordered_expect_and_full_window_forbid():
    judges = _judges()
    result = _result(
        """
[1 ns] [INFO 2] [SIM_OUT] - FIRST
[2 ns] [INFO 2] [SIM_OUT] - DONE
[3 ns] [INFO 2] [SIM_OUT] - MANIFEST_ERR=0x0003000b
[VP] SIMULATION OF THE TEST PASSED
"""
    )

    with pytest.raises(judges.JudgeError, match="MANIFEST_ERR"):
        judges.judge(result, expect=["FIRST", "DONE"], forbid=["MANIFEST_ERR"])


def test_ordered_expect_can_include_the_firmware_verdict():
    judges = _judges()
    result = _result("[1 ns] [INFO 2] [SIM_OUT] - DONE\n[VP] SIMULATION OF THE TEST PASSED\n")

    judges.judge(
        result,
        expect=["DONE", "[VP] SIMULATION OF THE TEST PASSED"],
    )


def test_bare_positive_console_match_is_unjudgeable():
    judges = _judges()
    result = _result("DONE\n[VP] SIMULATION OF THE TEST PASSED\n")

    with pytest.raises(judges.UnjudgeableError, match="bare output"):
        judges.judge(result, expect=["DONE"])


def test_ordered_expect_rejects_reverse_order():
    judges = _judges()
    result = _result(
        "[1 ns] [INFO 2] [SIM_OUT] - SECOND\n"
        "[2 ns] [INFO 2] [SIM_OUT] - FIRST\n"
        "[VP] SIMULATION OF THE TEST PASSED\n"
    )

    with pytest.raises(judges.JudgeError, match="SECOND"):
        judges.judge(result, expect=["FIRST", "SECOND"])


def test_exact_counts_reject_missing_occurrence():
    judges = _judges()
    result = _result(
        "[1 ns] [INFO 2] [SIM_OUT] - RETRY\n"
        "[2 ns] [INFO 2] [SIM_OUT] - DONE\n"
        "[VP] SIMULATION OF THE TEST PASSED\n"
    )

    with pytest.raises(judges.JudgeError, match="expected exactly 2"):
        judges.judge(result, expect=["DONE"], expect_counts={"RETRY": 2})


def test_bare_expect_prefix_is_reported_as_an_authoring_error():
    judges = _judges()
    result = _result("VALUE=0x00000001\n[VP] SIMULATION OF THE TEST PASSED\n")

    with pytest.raises(judges.JudgeError, match="bare prefix"):
        judges.judge(result, expect=["VALUE"])


def test_terminal_token_requires_liveness_and_last_position():
    judges = _judges()
    crashed = RunResult(
        output="HALT\n",
        stop_reason=StopReason.SIMULATOR_CRASH,
        duration=0.1,
        exit_code=None,
        signal=11,
        firmware_verdict=None,
        timed_out=False,
        harness_terminated=False,
    )

    with pytest.raises(judges.JudgeError, match="simulator crashed"):
        judges.judge(crashed, expect=["HALT"], terminal_token="HALT")

    timed_out = _result(
        "[1 ns] [INFO 2] [SIM_OUT] - HALT\n",
        reason=StopReason.TIMEOUT,
        verdict=None,
        timed_out=True,
    )
    judges.judge(timed_out, expect=["HALT"], terminal_token="HALT")

    carried_on = _result(
        "[1 ns] [INFO 2] [SIM_OUT] - HALT\n"
        "[2 ns] [INFO 2] [SIM_OUT] - GO!\n"
        "[VP] SIMULATION OF THE TEST PASSED\n"
    )
    with pytest.raises(judges.JudgeError, match="after terminal"):
        judges.judge(carried_on, expect=["HALT"], terminal_token="HALT")


def test_expect_silence_requires_timeout_liveness_and_no_console():
    judges = _judges()
    witness = "[init_writes] 0x10802038 = 0xc0030000"
    timed_out = _result(
        f"SystemC 3.0.2-Accellera\n{witness}\n",
        reason=StopReason.TIMEOUT,
        verdict=None,
        timed_out=True,
    )

    judges.judge(
        timed_out,
        expect_silence=True,
        forbid=["GO!"],
        liveness=[witness],
    )

    with pytest.raises(judges.JudgeError, match="missing liveness"):
        judges.judge(
            _result("", reason=StopReason.TIMEOUT, verdict=None, timed_out=True),
            expect_silence=True,
            forbid=["GO!"],
            liveness=[witness],
        )

    with pytest.raises(judges.JudgeError, match="liveness witness"):
        judges.judge(
            timed_out,
            expect_silence=True,
            forbid=["GO!"],
        )

    with pytest.raises(judges.JudgeError, match="must end at the run timeout"):
        judges.judge(
            _result(witness),
            expect_silence=True,
            forbid=["GO!"],
            liveness=[witness],
        )


def test_status_judges_are_ordered_and_channel_aware():
    judges = _judges()
    result = _result(
        """
[1 ns] [INFO 2] [SEP_STATUS] - BL0 INFO     0x0031 SEP_MSG_PLL_CLK_INIT
[2 ns] [INFO 2] [SEP_STATUS] - BL0 ERROR    0x005f SEP_MSG_SPI_NOT_DETECTED
[3 ns] [INFO 2] [SIM_OUT] - SPI_NOT_DETECTED
[VP] SIMULATION OF THE TEST PASSED
"""
    )

    assert judges.status_tokens(result.output) == ["INFO 0x0031", "ERROR 0x005f"]
    judges.judge(
        result,
        expect=["SPI_NOT_DETECTED"],
        expect_status=["INFO 0x0031", "ERROR 0x005f"],
    )

    with pytest.raises(judges.JudgeError, match="forbidden status"):
        judges.judge(
            result,
            expect=["SPI_NOT_DETECTED"],
            forbid_status=["ERROR 0x005f"],
        )

    with pytest.raises(judges.JudgeError, match="expected status"):
        judges.judge(
            result,
            expect=["SPI_NOT_DETECTED"],
            expect_status=["ERROR 0x005f", "INFO 0x0031"],
        )


def test_bare_positive_status_match_is_unjudgeable():
    judges = _judges()
    result = _result(
        "BL0 INFO     0x0031 SEP_MSG_PLL_CLK_INIT\n"
        "[1 ns] [INFO 2] [SIM_OUT] - DONE\n"
        "[VP] SIMULATION OF THE TEST PASSED\n"
    )

    with pytest.raises(judges.UnjudgeableError, match="bare output"):
        judges.judge(
            result,
            expect=["DONE"],
            expect_status=["INFO 0x0031"],
        )


def test_bare_forbid_only_status_channel_is_unjudgeable():
    judges = _judges()
    result = _result(
        "BL0 INFO     0x0031 SEP_MSG_PLL_CLK_INIT\n"
        "[1 ns] [INFO 2] [SIM_OUT] - DONE\n"
        "[VP] SIMULATION OF THE TEST PASSED\n"
    )

    with pytest.raises(judges.UnjudgeableError, match="status channel"):
        judges.judge(
            result,
            expect=["DONE"],
            forbid_status=["ERROR 0x005f"],
        )


def test_status_assertion_fails_closed_when_channel_is_absent():
    judges = _judges()

    with pytest.raises(judges.JudgeError, match="status channel"):
        judges.judge(
            _result("[1 ns] [INFO 2] [SIM_OUT] - DONE\n[VP] SIMULATION OF THE TEST PASSED\n"),
            expect=["DONE"],
            forbid_status=["ERROR 0x005f"],
        )


def test_nonzero_process_exit_after_verdict_cannot_pass():
    judges = _judges()
    result = RunResult(
        output=("[1 ns] [INFO 2] [SIM_OUT] - DONE\n[VP] SIMULATION OF THE TEST PASSED\n"),
        stop_reason=StopReason.PROCESS_EXIT,
        duration=0.1,
        exit_code=7,
        signal=None,
        firmware_verdict="PASSED",
        timed_out=False,
        harness_terminated=False,
    )

    with pytest.raises(judges.JudgeError, match="exit code 7"):
        judges.judge(result, expect=["DONE"])


def test_failed_firmware_verdict_cannot_pass():
    judges = _judges()
    result = _result(
        "[SIM_OUT] - DONE\n[VP] SIMULATION OF THE TEST FAILED\n",
        verdict="FAILED",
    )

    with pytest.raises(judges.JudgeError, match="firmware reported FAILED"):
        judges.judge(result, expect=["DONE"])


def test_failed_verdict_is_allowed_when_the_contract_expects_it():
    judges = _judges()
    result = _result(
        "[1 ns] [INFO 2] [SIM_OUT] - MANIFEST_BOOT_FAIL=0x00030002\n"
        "[VP] SIMULATION OF THE TEST FAILED\n",
        verdict="FAILED",
    )

    judges.judge(
        result,
        expect=[
            "MANIFEST_BOOT_FAIL=0x00030002",
            "[VP] SIMULATION OF THE TEST FAILED",
        ],
        forbid=["GO!", "[VP] SIMULATION OF THE TEST PASSED"],
        terminal_token="MANIFEST_BOOT_FAIL=0x00030002",
        expect_verdict="FAILED",
    )


def test_expected_pass_verdict_must_actually_arrive():
    judges = _judges()
    reached_the_end = _result(
        "[1 ns] [INFO 2] [SIM_OUT] - GO!\n",
        reason=StopReason.TIMEOUT,
        verdict=None,
        timed_out=True,
    )

    # Firmware that prints its last milestone and then spins never declared
    # itself finished, so the run proves less than the contract claims.
    with pytest.raises(judges.JudgeError, match="no terminal verdict"):
        judges.judge(reached_the_end, expect=["GO!"], expect_verdict="PASSED")

    judges.judge(
        _result("[1 ns] [INFO 2] [SIM_OUT] - GO!\n[VP] SIMULATION OF THE TEST PASSED\n"),
        expect=["GO!"],
        expect_verdict="PASSED",
    )


def test_a_contract_expecting_no_verdict_rejects_one():
    judges = _judges()
    witness = "[init_writes] 0x10802038 = 0x70018000"

    judges.judge(
        _result(witness, reason=StopReason.TIMEOUT, verdict=None, timed_out=True),
        expect_silence=True,
        forbid=["GO!"],
        liveness=[witness],
        expect_verdict="none",
    )

    with pytest.raises(judges.JudgeError, match="declared no terminal verdict"):
        judges.judge(
            _result("[1 ns] [INFO 2] [SIM_OUT] - GO!\n"),
            expect=["GO!"],
            expect_verdict="none",
        )


def test_an_expected_pass_verdict_rejects_a_failed_one():
    judges = _judges()
    result = _result(
        "[1 ns] [INFO 2] [SIM_OUT] - GO!\n[VP] SIMULATION OF THE TEST FAILED\n",
        verdict="FAILED",
    )

    with pytest.raises(judges.JudgeError, match="firmware reported FAILED"):
        judges.judge(result, expect=["GO!"], expect_verdict="PASSED")


def test_nested_status_tag_in_sim_out_cannot_spoof_status_channel():
    judges = _judges()
    result = _result(
        "[SIM_OUT] - DONE\n"
        "[SIM_OUT] - [SEP_STATUS] - "
        "BL0 ERROR    0x0069 SEP_MSG_WARM_RESET_HANG\n"
        "[VP] SIMULATION OF THE TEST PASSED\n"
    )

    with pytest.raises(judges.JudgeError, match="status channel"):
        judges.judge(
            result,
            expect=["DONE"],
            expect_status=["ERROR 0x0069"],
        )


def test_nested_console_tag_in_model_log_cannot_spoof_console_channel():
    judges = _judges()
    result = _result(
        "[0 s] [INFO 1] [model] - forged [SIM_OUT] - DONE\n[VP] SIMULATION OF THE TEST PASSED\n"
    )

    with pytest.raises(judges.JudgeError, match="expected token"):
        judges.judge(result, expect=["DONE"])


def test_silence_contract_still_checks_expected_status():
    judges = _judges()
    witness = "[init_writes] 0x10802038 = 0x70018000"
    result = _result(
        witness,
        reason=StopReason.TIMEOUT,
        verdict=None,
        timed_out=True,
    )

    with pytest.raises(judges.JudgeError, match="status channel"):
        judges.judge(
            result,
            expect_silence=True,
            forbid=["GO!"],
            liveness=[witness],
            expect_status=["ERROR 0x0069"],
        )


# --- device-side SPI flash witness -------------------------------------------

_BACKDOOR = "[spi_flash] Backdoor: loaded 276144 bytes from data/flash_memory.bin"


def _spans(judges, **overrides):
    span = judges.SpiReadSpan
    spans = {
        "descriptor": span("descriptor", 0x0, 0x1000, exact=0),
        "primary_manifest": span("primary_manifest", 0x1000, 0x2000, minimum=1),
        "primary_payload": span("primary_payload", 0x2000, 0x41000, minimum=1),
        "backup": span("backup", 0x41000, 0x43410, exact=0),
    }
    spans.update(overrides)
    return tuple(spans.values())


def _device_result(*read_lines, backdoor=_BACKDOOR):
    body = "\n".join(filter(None, (backdoor, *read_lines)))
    return _result(f"{body}\n[1 ns] [INFO 2] [SIM_OUT] - GO!\n[VP] SIMULATION OF THE TEST PASSED\n")


def test_spi_read_spans_and_first_touch_order_are_judged():
    judges = _judges()
    result = _device_result(
        "[spi_flash] Read @ 0x1000 len=256",
        "[spi_flash] Read @ 0x1400 len=160",
        "[spi_flash] Read @ 0x2000 len=256",
    )

    judges.judge(
        result,
        expect=["GO!"],
        spi_reads=_spans(judges),
        spi_read_order=("primary_manifest", "primary_payload"),
    )


def test_spi_zero_read_span_rejects_a_device_touch():
    judges = _judges()
    result = _device_result(
        "[spi_flash] Read @ 0x1000 len=256",
        "[spi_flash] Read @ 0x2000 len=256",
        "[spi_flash] Read @ 0x41000 len=256",
    )

    with pytest.raises(judges.JudgeError, match="backup.*exactly 0"):
        judges.judge(result, expect=["GO!"], spi_reads=_spans(judges))


def test_spi_read_assertions_require_a_backdoor_load_fence():
    judges = _judges()

    with pytest.raises(judges.JudgeError, match="backdoor load"):
        judges.judge(
            _device_result("[spi_flash] Read @ 0x1000 len=256", backdoor=None),
            expect=["GO!"],
            spi_reads=_spans(judges),
        )

    with pytest.raises(judges.JudgeError, match="backdoor load"):
        judges.judge(
            _device_result(
                "[spi_flash] Read @ 0x1000 len=256",
                backdoor="[spi_flash] Backdoor: loaded 0 bytes from data/flash_memory.bin",
            ),
            expect=["GO!"],
            spi_reads=_spans(judges),
        )


def test_spi_read_outside_every_declared_span_fails():
    judges = _judges()
    result = _device_result(
        "[spi_flash] Read @ 0x1000 len=256",
        "[spi_flash] Read @ 0x2000 len=256",
        "[spi_flash] Read @ 0x900000 len=16",
    )

    with pytest.raises(judges.JudgeError, match="outside every declared span"):
        judges.judge(result, expect=["GO!"], spi_reads=_spans(judges))


def test_spi_read_straddling_a_span_top_fails():
    judges = _judges()
    result = _device_result(
        "[spi_flash] Read @ 0x1f80 len=256",
        "[spi_flash] Read @ 0x2000 len=256",
    )

    with pytest.raises(judges.JudgeError, match="ends past its top"):
        judges.judge(result, expect=["GO!"], spi_reads=_spans(judges))


def test_spi_read_order_rejects_reversed_first_touch():
    judges = _judges()
    result = _device_result(
        "[spi_flash] Read @ 0x2000 len=256",
        "[spi_flash] Read @ 0x1000 len=256",
    )

    with pytest.raises(judges.JudgeError, match="required order"):
        judges.judge(
            result,
            expect=["GO!"],
            spi_reads=_spans(judges),
            spi_read_order=("primary_manifest", "primary_payload"),
        )


def test_spi_read_order_requires_the_named_span_to_be_read():
    judges = _judges()
    result = _device_result("[spi_flash] Read @ 0x1000 len=256")

    with pytest.raises(judges.JudgeError, match="served no read there"):
        judges.judge(
            result,
            expect=["GO!"],
            spi_reads=_spans(
                judges,
                primary_payload=judges.SpiReadSpan("primary_payload", 0x2000, 0x41000, minimum=0),
            ),
            spi_read_order=("primary_manifest", "primary_payload"),
        )


def test_spi_read_line_inside_sim_out_cannot_spoof_the_device_channel():
    judges = _judges()
    result = _device_result(
        "[spi_flash] Read @ 0x1000 len=256",
        "[2 ns] [INFO 2] [SIM_OUT] - [spi_flash] Read @ 0x2000 len=256",
    )

    with pytest.raises(judges.JudgeError, match="primary_payload.*at least 1"):
        judges.judge(result, expect=["GO!"], spi_reads=_spans(judges))


def test_silence_contract_still_checks_spi_reads():
    judges = _judges()
    witness = "[init_writes] 0x10802038 = 0x70018000"
    result = _result(
        f"{witness}\n{_BACKDOOR}\n[spi_flash] Read @ 0x41000 len=256\n",
        reason=StopReason.TIMEOUT,
        verdict=None,
        timed_out=True,
    )

    with pytest.raises(judges.JudgeError, match="backup.*exactly 0"):
        judges.judge(
            result,
            expect_silence=True,
            forbid=["GO!"],
            liveness=[witness],
            spi_reads=(judges.SpiReadSpan("backup", 0x41000, 0x43410, exact=0),),
        )


def test_regloger_banner_is_platform_noise():
    output = "RegLogger global log file: och_sep_ss.log\n[SIM_OUT] - COLD\n"
    assert _judges().console_tokens(output) == ["COLD"]


def test_systemc_info_report_is_platform_noise():
    output = (
        "Info: och_sep_ss1.entropy_pool: SEP entropy pool instantiate\n"
        "[0 s] [INFO 2] [och_sep_ss1.mailbox_unit.mailbox_0::mailbox_ip] - Mailbox IP "
        "instantiated with: MailboxDepth=8 IrqActHigh=true MemorySize=0x50\n"
        "Setting: och_sep_ss1.aes.verbosity = 1\n"
        "[SIM_OUT] - COLD\n"
    )
    assert _judges().console_tokens(output) == ["COLD"]


def test_forbidden_value_prefix_matches_any_value():
    judges = _judges()
    tokens = ["MANIFEST_ERR=0x00030015", "MANIFEST_ERR_X", "MANIFEST_ERR"]
    assert judges._forbidden_hits(tokens, "MANIFEST_ERR=") == ["MANIFEST_ERR=0x00030015"]
    assert judges._forbidden_hits(["STATUS: 3", "STATUS_X"], "STATUS:") == ["STATUS: 3"]


def test_bare_forbid_matches_exact_and_equals_value_only():
    judges = _judges()
    tokens = ["MANIFEST_ERR", "MANIFEST_ERR=0x1", "MANIFEST_ERR_X"]
    assert judges._forbidden_hits(tokens, "MANIFEST_ERR") == ["MANIFEST_ERR", "MANIFEST_ERR=0x1"]


def test_forbid_with_value_prefix_fails_the_judge():
    judges = _judges()
    result = _result(
        "[1 ns] [INFO 2] [SIM_OUT] - MANIFEST_ERR=0x00030015\n[VP] SIMULATION OF THE TEST PASSED\n"
    )
    with pytest.raises(judges.JudgeError, match="MANIFEST_ERR"):
        judges.judge(result, expect=["MANIFEST_ERR=0x00030015"], forbid=["MANIFEST_ERR="])


def test_failed_verdict_message_quotes_the_console_tail():
    judges = _judges()
    count = judges._TAIL_ENTRIES + 8
    lines = "".join(f"[SIM_OUT] - T{i}\n" for i in range(count))
    result = _result(lines + "[VP] SIMULATION OF THE TEST FAILED\n", verdict="FAILED")

    with pytest.raises(judges.JudgeError) as caught:
        judges.judge(result, expect=["DONE"])

    message = str(caught.value)
    assert message == "firmware reported FAILED; console tail: " + " | ".join(
        f"T{i}" for i in range(8, count)
    )


def test_verdict_mismatch_message_quotes_the_console_tail():
    judges = _judges()
    result = _result("[SIM_OUT] - A\n[SIM_OUT] - GO!\n[VP] SIMULATION OF THE TEST PASSED\n")

    with pytest.raises(judges.JudgeError) as caught:
        judges.judge(result, expect=["GO!"], expect_verdict="FAILED")

    assert str(caught.value) == "firmware reported PASSED, expected FAILED; console tail: A | GO!"


_STATUS_RUN = (
    "[1 ns] [INFO 2] [SEP_STATUS] - BL0 INFO     0x0212 SEP_MSG_MANIFEST_LOAD_START\n"
    "[2 ns] [INFO 2] [SEP_STATUS] - BL0 INFO     0x0055 SEP_MSG_PAYLOAD_VALIDATED\n"
    "[3 ns] [INFO 2] [SIM_OUT] - GO!\n"
    "[VP] SIMULATION OF THE TEST PASSED\n"
)


def test_missing_expected_status_message_quotes_the_status_tail():
    judges = _judges()

    with pytest.raises(judges.JudgeError) as caught:
        judges.judge(_result(_STATUS_RUN), expect=["GO!"], expect_status=["WARN 0x000f"])

    assert str(caught.value) == (
        "expected status not found in order: 'WARN 0x000f'; status tail: INFO 0x0212 | INFO 0x0055"
    )


def test_forbidden_status_message_quotes_the_status_tail():
    judges = _judges()

    with pytest.raises(judges.JudgeError) as caught:
        judges.judge(_result(_STATUS_RUN), expect=["GO!"], forbid_status=["INFO 0x0055"])

    assert str(caught.value) == (
        "forbidden status present: 'INFO 0x0055'; status tail: INFO 0x0212 | INFO 0x0055"
    )


def test_status_tail_is_bounded():
    judges = _judges()
    count = judges._TAIL_ENTRIES + 3
    lines = "".join(f"[SEP_STATUS] - BL0 INFO     0x{i:04x} SEP_MSG_X\n" for i in range(count))
    result = _result(lines + "[SIM_OUT] - GO!\n[VP] SIMULATION OF THE TEST PASSED\n")

    with pytest.raises(judges.JudgeError) as caught:
        judges.judge(result, expect=["GO!"], expect_status=["WARN 0x000f"])

    tail = str(caught.value).split("status tail: ")[1].split(" | ")
    assert tail == [f"INFO 0x{i:04x}" for i in range(3, count)]


def test_a_complete_run_requires_every_liveness_witness():
    judges = _judges()
    witness = "[init_writes] 0x10802038 = 0xc0030000"
    run = "[1 ns] [INFO 2] [SIM_OUT] - GO!\n[VP] SIMULATION OF THE TEST PASSED\n"

    judges.judge(_result(f"{witness}\n{run}"), expect=["GO!"], liveness=[witness])
    with pytest.raises(judges.JudgeError, match="missing liveness witness"):
        judges.judge(_result(run), expect=["GO!"], liveness=[witness])


def test_a_liveness_witness_matches_a_whole_line():
    judges = _judges()
    run = "[init_writes] 0x4000b800 = 0x112\n[SIM_OUT] - GO!\n[VP] SIMULATION OF THE TEST PASSED\n"

    with pytest.raises(judges.JudgeError, match="missing liveness witness"):
        judges.judge(_result(run), expect=["GO!"], liveness=["[init_writes] 0x4000b800 = 0x1"])
