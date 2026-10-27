# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Graded-window gate of the FCOV sampler (docs/SEP_FCOV.adoc).

The sampler ``u_sep_fcov`` (cov/sv/sep_fcov.sv) samples a graded bin only
while its variable ``graded_owner`` holds the code of an owning test. A leaf
writes its own code at the first step of its graded stimulus and 0 before a
control leg, a bring-up or clean-up step, a reset that is not graded, and at
the end of the leaf.

The codes come from one table, ``tb/sep_fcov_owner_codes.svh``, which the
sampler includes. This module reads the same file, so the leaf and the sampler
cannot disagree on a code.

``u_sep_fcov`` exists on every simulator except Verilator (``tb/tb_top.sv``
instantiates it under ``ifndef VERILATOR``). On Verilator every call here is a
no-op and returns False; a check of a leaf never depends on the gate. On any
other simulator a missing sampler or ``graded_owner`` is a testbench error, so a
build that lost the sampler fails instead of leaving the owner-gated bins empty.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import cocotb

_CODES_SVH = Path(__file__).resolve().parents[2] / "tb" / "sep_fcov_owner_codes.svh"
_LINE = re.compile(r"^\s*localparam\s+int\s+unsigned\s+FcovOwn(\w+)\s*=\s*(\d+)\s*;", re.M)
_CAMEL_BREAK = re.compile(r"(?<!^)(?=[A-Z])")


@lru_cache(maxsize=1)
def owner_codes() -> dict[str, int]:
    """Map test name (lower case) to its owner code; ``none`` maps to 0."""
    text = _CODES_SVH.read_text()
    codes = {_CAMEL_BREAK.sub("_", name).lower(): int(code) for name, code in _LINE.findall(text)}
    if codes.get("none") != 0:
        raise RuntimeError(f"{_CODES_SVH}: FcovOwnNone must be 0")
    if len(set(codes.values())) != len(codes):
        raise RuntimeError(f"{_CODES_SVH}: an owner code is used twice")
    return codes


def owner_code(test_name: str) -> int:
    """The owner code of ``test_name``. A missing name is a testbench error."""
    try:
        return owner_codes()[test_name.lower()]
    except KeyError as exc:
        raise KeyError(
            f"{test_name} has no FcovOwn line in {_CODES_SVH.name}; add one before it opens a window"
        ) from exc


def _sampler_expected() -> bool:
    return "verilator" not in str(getattr(cocotb, "SIM_NAME", "") or "").lower()


def _gate_handle():
    if not _sampler_expected():
        return None
    dut = cocotb.top
    if not hasattr(dut, "u_sep_fcov"):
        raise AttributeError(
            f"{cocotb.SIM_NAME}: tb_top has no u_sep_fcov; the FCOV sampler must exist on "
            "every simulator except Verilator (tb/tb_top.sv, cov/sv/sep_fcov.sv)"
        )
    fcov = dut.u_sep_fcov
    if not hasattr(fcov, "graded_owner"):
        raise AttributeError("u_sep_fcov has no graded_owner variable (cov/sv/sep_fcov.sv)")
    return fcov.graded_owner


def fcov_present() -> bool:
    """True when the build carries the sampler (every simulator except Verilator)."""
    return _gate_handle() is not None


def open_graded_window(test_name: str, log=None) -> bool:
    """Write the owner code of ``test_name``. Returns True when written."""
    code = owner_code(test_name)
    gate = _gate_handle()
    if gate is None:
        return False
    gate.value = code
    if log is not None:
        log.info("FCOV-GATE open owner=%s code=%d", test_name, code)
    return True


def set_quiet_window(on: bool, log=None) -> bool:
    """Write ``u_sep_fcov.quiet_win`` (1 inside a quiet window, else 0).

    The mailbox leaf sets it at the end of the settle wait of a check cycle and
    clears it before the next access to the mailbox unit (docs/SEP_FCOV.adoc,
    mailbox, IRQ and PIC sampling rules). Same rules as ``graded_owner``: a
    no-op that returns False on Verilator. On VCS a sampler without the
    variable is a testbench error.
    """
    if _gate_handle() is None:
        return False
    fcov = cocotb.top.u_sep_fcov
    if not hasattr(fcov, "quiet_win"):
        raise AttributeError("u_sep_fcov has no quiet_win variable (cov/sv/sep_fcov.sv)")
    fcov.quiet_win.value = 1 if on else 0
    if log is not None:
        log.info("FCOV-QUIET %s", "open" if on else "closed")
    return True


def set_abr_reject_class(reason_class: int, log=None) -> bool:
    """Write ``u_sep_fcov.abr_reject_class`` (1 to 4, or 0 for none).

    The stimulus label of ``sep_abr_completion_cg.cp_verify_outcome``: the ACVP
    reason class of the sigVer reject row that the ABR leaf writes to the DUT
    (1 modified message, 2 modified signature - commitment, 3 modified
    signature - hint, 4 modified signature - z). The leaf sets it before the
    reject verify and writes 0 after the last ``MLDSA_VERIFY_RES`` read of that
    verify. Same rules as ``graded_owner``: a no-op that returns False on
    Verilator. On VCS a sampler without the variable is a testbench error.
    """
    if not 0 <= reason_class <= 4:
        raise ValueError(f"abr_reject_class {reason_class} is not 0 to 4")
    if _gate_handle() is None:
        return False
    fcov = cocotb.top.u_sep_fcov
    if not hasattr(fcov, "abr_reject_class"):
        raise AttributeError("u_sep_fcov has no abr_reject_class variable (cov/sv/sep_fcov.sv)")
    fcov.abr_reject_class.value = reason_class
    if log is not None:
        log.info("FCOV-ABR-REJECT-CLASS %d", reason_class)
    return True


# First bit of each point of ``sep_crypto_bus_access_cg`` in
# ``u_sep_fcov.crypto_bus_pass``: bin value v of the point passes on bit
# offset + v. Bits 15 and 26 to 30 are unused.
CRYPTO_BUS_PASS_ABR_ACCESS = 0  # x_abr_access, v 0 to 14
CRYPTO_BUS_PASS_DRBG_LANE = 16  # x_drbg_lane, v 0 to 7
CRYPTO_BUS_PASS_LANE_REFUSE = 24  # cp_lane_refuse, v 0 to 1
CRYPTO_BUS_PASS_LANE_ARB = 31  # x_drbg_lane_arb legal cell, v = lane 0 to 1
CRYPTO_BUS_PASS_ABR_CONCURRENT = 33  # x_abr_concurrent, v 0 to 5
CRYPTO_BUS_PASS_BITS = 39


def set_crypto_bus_pass(cells: int, log=None) -> bool:
    """Write ``u_sep_fcov.crypto_bus_pass`` (the passed cells, or 0).

    The pass label of ``x_drbg_lane``, ``cp_lane_refuse``, ``x_abr_access``,
    ``x_abr_concurrent`` and the legal cells of ``x_drbg_lane_arb``
    (``sep_crypto_bus_access_cg``); the ``CRYPTO_BUS_PASS_*`` offsets give the
    bit of each cell. The sampler holds a cell as seen at its DUT event inside
    the window of its owner, and samples it only when the bit of that cell
    rises inside that window; the window close drops the cells not sampled.
    An owner writes the cells a check graded after that check passes, holds
    them for at least one clk_i edge, and writes 0 before the next check
    writes its cells. Same rules as ``graded_owner``: a no-op that returns
    False on Verilator. On VCS a sampler without the variable is a testbench
    error.
    """
    if cells < 0 or cells >> CRYPTO_BUS_PASS_BITS:
        raise ValueError(f"crypto_bus_pass cells {cells:#x} are out of range")
    if _gate_handle() is None:
        return False
    fcov = cocotb.top.u_sep_fcov
    if not hasattr(fcov, "crypto_bus_pass"):
        raise AttributeError("u_sep_fcov has no crypto_bus_pass variable (cov/sv/sep_fcov.sv)")
    fcov.crypto_bus_pass.value = cells
    if log is not None:
        log.info("FCOV-CRYPTO-BUS-PASS 0x%010x", cells)
    return True


def set_otbn_sw_err_pass(kind: int, log=None) -> bool:
    """Write ``u_sep_fcov.otbn_sw_err_pass`` (1 to 4, or 0 for none).

    The pass label of ``sep_otbn_err_lock_cg.cp_sw_err_kind``: the software error
    whose check passed in the OTBN command-status leaf (1 ``bad_data_addr``, 2
    ``bad_insn_addr``, 3 ``call_stack``, 4 ``loop``). The sampler holds the kind
    bits of the first ``ERR_BITS`` read after an EXECUTE that ended at IDLE, and
    samples the kind of this label only when the label rises and that kind bit is
    held. The leaf writes it after its check of that error passes, and 0 after.
    Same rules as ``graded_owner``: a no-op that returns False on Verilator. On
    VCS a sampler without the variable is a testbench error.
    """
    if not 0 <= kind <= 4:
        raise ValueError(f"otbn_sw_err_pass {kind} is not 0 to 4")
    if _gate_handle() is None:
        return False
    fcov = cocotb.top.u_sep_fcov
    if not hasattr(fcov, "otbn_sw_err_pass"):
        raise AttributeError("u_sep_fcov has no otbn_sw_err_pass variable (cov/sv/sep_fcov.sv)")
    fcov.otbn_sw_err_pass.value = kind
    if log is not None:
        log.info("FCOV-OTBN-SW-ERR-PASS %d", kind)
    return True


def set_aes_busy_write_pass(kind: int, log=None) -> bool:
    """Write ``u_sep_fcov.aes_busy_write_pass`` (1 to 3, or 0 for none).

    The pass label of ``sep_aes_op_status_cg.cp_busy_write``: 1 key_ignored, 2
    iv_ignored, 3 partial_iv_no_start. The sampler holds the bin of a busy KEY_SHARE0
    or IV write, or of a partial IV, as pending at the next OUTPUT_VALID rise, and
    samples it only when this value rises to that bin. The AES stream-status leaf
    writes 0 at the start of each case and the bin value after the check of that case
    passes. Same rules as ``graded_owner``: a no-op that returns False on Verilator. On
    VCS a sampler without the variable is a testbench error.
    """
    if not 0 <= kind <= 3:
        raise ValueError(f"aes_busy_write_pass {kind} is not 0 to 3")
    return _set_bound("aes_busy_write_pass", kind, "FCOV-AES-BUSY-WRITE-PASS", log)


def set_kmac_stream_pass(passed: bool, log=None) -> bool:
    """Write ``u_sep_fcov.kmac_stream_pass`` (1 after a passed cell, or 0).

    The pass label of the owner cells of the KMAC stream-config leaf in
    ``sep_kmac_cfg_cmd_cg`` (``x_cmd_stage`` legal cells, ``x_endian``,
    ``x_len_corner``, ``cp_run_block``) and of its ``kmac_done`` cells of
    ``sep_crypto_intr_cg``. The sampler holds those cells for the command cycle
    of one cell and samples them only when this value rises; the next
    ``CMD.start`` and the window close drop them. The leaf writes 1 after every
    check and control of a cell passed, holds it for at least one clk_i edge,
    and writes 0 before the next cell starts. Same rules as ``graded_owner``: a
    no-op that returns False on Verilator. On VCS a sampler without the variable
    is a testbench error.
    """
    return _set_bound("kmac_stream_pass", int(bool(passed)), "FCOV-KMAC-STREAM-PASS", log)


# Bits of ``u_sep_fcov.hmac_fifo_pass``: one per held cell of the HMAC FIFO leaf.
HMAC_FIFO_PASS_LEN_CLASS = 1 << 0  # x_len_class
HMAC_FIFO_PASS_FIFO_STATE = 1 << 1  # x_fifo_state_mode
HMAC_FIFO_PASS_BACKPRESSURE = 1 << 2  # cp_backpressure
HMAC_FIFO_PASS_EMPTY_AFTER_FULL = 1 << 3  # cp_hmac_fifo_empty_qual empty_after_full
HMAC_FIFO_PASS_EMPTY_NOT_FULL = 1 << 4  # cp_hmac_fifo_empty_qual empty_not_full
HMAC_FIFO_PASS_HW_RAISE = 1 << 5  # cp_hw_raise hmac_fifo_empty
HMAC_FIFO_PASS_WIPE_DIGEST = 1 << 6  # cp_wipe_secret digest_reads_w
HMAC_FIFO_PASS_WIPE_KEY = 1 << 7  # cp_wipe_secret next_hmac_all_w_key
HMAC_FIFO_PASS_BITS = 8


def set_hmac_fifo_pass(bits: int, log=None) -> bool:
    """Write ``u_sep_fcov.hmac_fifo_pass`` (a mask of ``HMAC_FIFO_PASS_*``, or 0).

    The pass label of the points of ``sep_hmac_fifo_stream_rand_test``: the sampler
    holds a legal cell as pending at its DUT event inside the owner window and samples
    it only when its bit rises inside that window; the window close drops the pending
    cells. The leaf writes the bits of the cells a check graded after that check passes,
    holds them for at least one clk_i edge, and writes 0. Same rules as
    ``graded_owner``: a no-op that returns False on Verilator. On VCS a sampler without
    the variable is a testbench error.
    """
    if bits < 0 or bits >> HMAC_FIFO_PASS_BITS:
        raise ValueError(f"hmac_fifo_pass bits {bits:#x} are out of range")
    return _set_bound("hmac_fifo_pass", bits, "FCOV-HMAC-FIFO-PASS", log)


def set_kmac_unsup_pass(check: int, log=None) -> bool:
    """Write ``u_sep_fcov.kmac_unsup_pass`` (1 to 3, or 0 for none).

    The pass label of the bins of the KMAC unsupported-configuration leaf: 1 the
    blocked cell passed its blocked-start and error-code checks, 2 its recovery
    passed, 3 the enabled cell passed its absorb check. The sampler holds a legal
    outcome as pending at its DUT event and samples it only when this value rises
    from 0 to the check that grades it; illegal outcomes sample at once. The leaf
    writes the value after that check passes, holds it, then writes 0. Same rules
    as ``graded_owner``: a no-op that returns False on Verilator. On VCS a sampler
    without the variable is a testbench error.
    """
    if not 0 <= check <= 3:
        raise ValueError(f"kmac_unsup_pass {check} is not 0 to 3")
    return _set_bound("kmac_unsup_pass", check, "FCOV-KMAC-UNSUP-PASS", log)


def set_abr_cmd_pass(kind: int, log=None) -> bool:
    """Write ``u_sep_fcov.abr_cmd_pass`` (1 to 6, or 0 for none).

    The pass label of the ABR command matrix leaf for ``sep_abr_completion_cg``:
    1 / 2 CHK-ABR-COMBO passed on ML-DSA / ML-KEM (``cp_combined_cmd``), 3 / 4
    CHK-ABR-PARK passed on the single-step cell of ML-DSA / ML-KEM with its result
    windows equal to the vector (``x_op_protocol`` single-step cells), 5 / 6
    CHK-ABR-REARM passed on ML-DSA / ML-KEM (``x_op_protocol`` ready-after-zeroize
    and ready-after-reset cells). The sampler holds each of these outcomes as
    pending at its DUT event and samples it only when this value rises to its
    value. The leaf writes the value after the check passes, holds it, then writes
    0. Same rules as ``graded_owner``: a no-op that returns False on Verilator. On VCS
    a sampler without the variable is a testbench error.
    """
    if not 0 <= kind <= 6:
        raise ValueError(f"abr_cmd_pass {kind} is not 0 to 6")
    return _set_bound("abr_cmd_pass", kind, "FCOV-ABR-CMD-PASS", log)


# Bits of ``u_sep_fcov.aes_shadow_pass`` (owner sep_crypto_shadow_update_err_rand_test).
AES_SHADOW_PASS_SP_MISMATCHED = 0  # x_shadow_pair_aes.mismatched, CHK-SHADOW-ERR
AES_SHADOW_PASS_SP_MATCHED = 1  # x_shadow_pair_aes.matched, CHK-SHADOW-CTRL
AES_SHADOW_PASS_RECOVERY = 2  # cp_update_err_recovery, CHK-SHADOW-RESTART
AES_SHADOW_PASS_AUX_MISMATCHED = 3  # x_shadow_pair_aux.mismatched, CHK-AUX-SHADOW-ERR
AES_SHADOW_PASS_AUX_MATCHED = 4  # x_shadow_pair_aux.matched, CHK-AUX-SHADOW-WRITE
AES_SHADOW_PASS_GCM_MISMATCHED = 5  # x_shadow_pair_gcm.mismatched, CHK-GCM-SHADOW-ERR
AES_SHADOW_PASS_GCM_MATCHED = 6  # x_shadow_pair_gcm.matched, CHK-GCM-SHADOW-WRITE
AES_SHADOW_PASS_AUX_REGWEN = 7  # cp_aux_regwen (both cells), CHK-AUX-REGWEN
AES_SHADOW_PASS_RESET_RESTORE = 8  # cp_reset_restore (both cells), CHK-AUX-RESET
AES_SHADOW_PASS_ALERT = 9  # x_alert_source cell of block b on bit 9 + b, CHK-ALERT-MALFORMED
AES_SHADOW_PASS_BITS = 15


def set_aes_shadow_pass(bits: int, log=None) -> bool:
    """Write ``u_sep_fcov.aes_shadow_pass`` (the passed cells, or 0).

    The pass label of the owner-134 bins (``sep_aes_fault_cg``, ``cp_aux_regwen``
    of ``sep_crypto_reg_lock_cg`` and ``x_alert_source`` of
    ``sep_crypto_alert_cg``); the ``AES_SHADOW_PASS_*`` constants give the bit of
    each cell. The sampler holds a legal cell as seen at its DUT event inside the
    owner window and samples it only on the rise of its bit; the window close
    drops it. The shadow update-error leaf writes the bits of the cells a check
    graded after that check passes, holds them for at least one clk_i edge, and
    writes 0. Same rules as ``graded_owner``: a no-op that returns False on
    Verilator. On VCS a sampler without the variable is a testbench error.
    """
    if bits < 0 or bits >> AES_SHADOW_PASS_BITS:
        raise ValueError(f"aes_shadow_pass bits {bits:#x} are out of range")
    return _set_bound("aes_shadow_pass", bits, "FCOV-AES-SHADOW-PASS", log)


# Bits of ``u_sep_fcov.otbn_cmd_pass`` (owner sep_otbn_cmd_status_rand_test): one per
# check; the bins each bit releases are in cov/sv/sep_fcov.sv (CyOcp*).
OTBN_CMD_PASS_CMD_BUSY = 1 << 0  # cp_cmd, x_cmd_first_busy: CHK-OTBN-CMD-BUSY
OTBN_CMD_PASS_CMD_END = 1 << 1  # cp_done_event: CHK-OTBN-CMD-END
OTBN_CMD_PASS_IGNORE = 1 << 2  # cp_cmd_ignored: CHK-OTBN-CMD-IGNORE
OTBN_CMD_PASS_IGN_ERR = 1 << 3  # cp_cmd_ignored_err: CHK-OTBN-CMDIGN-ERR
OTBN_CMD_PASS_INSN = 1 << 4  # cp_insn_cnt, cp_post_reset_arc: CHK-OTBN-INSN
OTBN_CMD_PASS_BUSYWR = 1 << 5  # cp_ctrl_write_legality: CHK-OTBN-BUSYWR
OTBN_CMD_PASS_SWERR_FATAL = 1 << 6  # cp_sw_error_end fatal: CHK-OTBN-SWERR-FATAL
OTBN_CMD_PASS_LOCKED_HOLD = 1 << 7  # cp_locked_hold_exit: CHK-OTBN-LOCKED-HOLD
OTBN_CMD_PASS_SWERR_RECOV = 1 << 8  # cp_sw_error_end recoverable: CHK-OTBN-SWERR-RECOV
OTBN_CMD_PASS_ERRCLR = 1 << 9  # cp_err_bits_clear: CHK-OTBN-ERRCLR
OTBN_CMD_PASS_IMEM_INTG = 1 << 10  # cp_intg_violation_end imem: CHK-OTBN-IMEM-INTG
OTBN_CMD_PASS_DMEM_INTG = 1 << 11  # cp_intg_violation_end dmem: CHK-OTBN-DMEM-INTG
OTBN_CMD_PASS_ILLEGAL_BUS = 1 << 12  # cp_fatal_cause: CHK-OTBN-ILLEGAL-BUS
# sep_crypto_intr_cg otbn_done x_line_gate, cp_w1c_clear, cp_enable_flip: CHK-OTBN-DONE-LINE
OTBN_CMD_PASS_DONE_LINE = 1 << 13
OTBN_CMD_PASS_BITS = 14


def set_otbn_cmd_pass(bits: int, log=None) -> bool:
    """Write ``u_sep_fcov.otbn_cmd_pass`` (a mask of ``OTBN_CMD_PASS_*``, or 0).

    The pass label of the owner bins of the OTBN command-status leaf in
    ``sep_otbn_op_cg`` and ``sep_otbn_err_lock_cg`` (all but ``cp_sw_err_kind``,
    ``cp_rnd_clean`` and the ignored ``cp_post_reset_done``), and of its legal
    ``otbn_done`` cells of ``sep_crypto_intr_cg`` (``cp_hw_raise``,
    ``x_line_gate``, ``cp_w1c_clear``, ``cp_enable_flip``). The sampler holds a
    legal outcome as pending at its DUT event inside the owner window, also across
    a window close, and samples it only when the bit of the check that grades it
    rises inside the owner window. The pending ``x_line_gate``, ``cp_w1c_clear``
    and ``cp_enable_flip`` cells are dropped at an OTBN reset and outside the owner
    window, so each graded done-line run releases only its own cells.
    The leaf writes the bit after that check passes, only while no check or
    control of the run failed, holds it for at least one clk_i edge, and writes 0.
    Same rules as ``graded_owner``: a no-op that returns False on Verilator. On VCS
    a sampler without the variable is a testbench error.
    """
    if bits < 0 or bits >> OTBN_CMD_PASS_BITS:
        raise ValueError(f"otbn_cmd_pass bits {bits:#x} are out of range")
    return _set_bound("otbn_cmd_pass", bits, "FCOV-OTBN-CMD-PASS", log)


# Bits of ``u_sep_fcov.aes_stream_pass`` (owner sep_aes_stream_status_rand_test): one
# per check; the bins each bit releases are in cov/sv/sep_fcov.sv (CyAsp*).
AES_STREAM_PASS_STALL = 1 << 0  # x_mode_status automatic cells, cp_nonidle_cause stall
AES_STREAM_PASS_LOST = 1 << 1  # x_mode_status manual_output_lost, cp_lost_clear
AES_STREAM_PASS_START_AUTO = 1 << 2  # cp_start_suppress automatic_no_start
AES_STREAM_PASS_START_MANUAL = 1 << 3  # cp_start_suppress manual_legal_idle_falls
AES_STREAM_PASS_INPUT_READY = 1 << 4  # cp_input_ready_hold legal cells
AES_STREAM_PASS_IDLE = 1 << 5  # cp_nonidle_cause core_running
AES_STREAM_PASS_BITS = 6


def set_aes_stream_pass(bits: int, log=None) -> bool:
    """Write ``u_sep_fcov.aes_stream_pass`` (a mask of ``AES_STREAM_PASS_*``, or 0).

    The pass label of the owner bins of the AES stream-status leaf in
    ``sep_aes_op_status_cg`` other than ``cp_busy_write`` (``x_mode_status``,
    ``cp_lost_clear``, ``cp_nonidle_cause``, ``cp_start_suppress`` kinds 0 and 2,
    ``cp_input_ready_hold``). The sampler holds a legal outcome as pending at its
    DUT event inside the owner window, also across a window close and an AES
    reset, and samples it only when the bit of the check that grades it rises
    inside the owner window. The leaf writes the bit after that check passes,
    only while no check or control of the run failed, holds it for at least one
    clk_i edge, and writes 0. Same rules as ``graded_owner``: a no-op that returns
    False on Verilator. On VCS a sampler without the variable is a testbench error.
    """
    if bits < 0 or bits >> AES_STREAM_PASS_BITS:
        raise ValueError(f"aes_stream_pass bits {bits:#x} are out of range")
    return _set_bound("aes_stream_pass", bits, "FCOV-AES-STREAM-PASS", log)


def _set_bound(var: str, value: int, tag: str, log=None) -> bool:
    if value < 0:
        raise ValueError(f"{var} {value} is negative")
    if _gate_handle() is None:
        return False
    fcov = cocotb.top.u_sep_fcov
    if not hasattr(fcov, var):
        raise AttributeError(f"u_sep_fcov has no {var} variable (cov/sv/sep_fcov.sv)")
    getattr(fcov, var).value = value
    if log is not None:
        log.info("%s %d", tag, value)
    return True


def set_esrc_af_clear_bound(strobes: int, log=None) -> bool:
    """Write ``u_sep_fcov.esrc_af_clear_bound`` (strobes, or 0 for none).

    The persistent-alert leaf writes its count-clear bound (2W strobes of
    ``esrc_decor_valid_o``) after the last failing word of a burst and 0 when its
    polls end. ``cp_any_fail`` "falls to 0" samples only a fall of
    ``ANY_FAIL_COUNT`` to 0 at most that many strobes after the write, the bound
    the leaf grades (docs/SEP_FCOV.adoc). Same rules as ``graded_owner``: a no-op
    that returns False on Verilator. On VCS a sampler without the variable is a
    testbench error.
    """
    return _set_bound("esrc_af_clear_bound", strobes, "FCOV-ESRC-AF-CLEAR-BOUND", log)


def set_rel_terms_pass(bits: int, log=None) -> bool:
    """Write ``u_sep_fcov.rel_terms_pass`` (pass bits of the boot release leaf).

    The pass label of ``sep_reset_source_cg.cp_release_order``
    ``release_after_sense_rise`` (bit 0) under ``sep_boot_release_terms_test``.
    The sampler holds the event as pending and samples it only when bit 0
    rises. The leaf writes 0 at the start of each epoch and sets bit 0 after
    ``CHK-REL-GATE`` of the epoch passes. Same rules as ``graded_owner``: a no-op that
    returns False on Verilator. On VCS a sampler without the variable is a
    testbench error.
    """
    return _set_bound("rel_terms_pass", bits, "FCOV-REL-TERMS-PASS", log)


def set_alert_rise_bound(clocks: int, log=None) -> bool:
    """Write ``u_sep_fcov.alert_rise_bound`` (clk_i clocks, or 0 for none).

    The shadow-update leaf writes the rise bound of a malformed-alert trial
    (WINDOW_FACTOR x the ``ALERT_TEST`` delay c of the block) together with the
    inject and 0 when the rise wait ends. ``x_alert_source`` samples only a rise of
    vector bit 32 on a clock 2 to bound - 1 (inclusive) after the leaf's watcher
    mark, the window the leaf grades (docs/SEP_FCOV.adoc). Same rules as
    ``graded_owner``: a no-op that returns False on Verilator. On VCS a sampler
    without the variable is a testbench error.
    """
    return _set_bound("alert_rise_bound", clocks, "FCOV-ALERT-RISE-BOUND", log)


def set_efuse_sdis_hold_bound(clocks: int, log=None) -> bool:
    """Write ``u_sep_fcov.efuse_sdis_hold_bound`` (clk_i clocks, or 0 for none).

    The SEC_DIS timing leaf writes its hold window W (a multiple of the sense time
    it measures) before the hold under the SEC_DIS match and 0 when the wait ends.
    ``sep_sec_dis_robustness_cg.cp_stops_sense`` samples only a hold of exactly that
    many clocks with the sensed shadow unchanged, the window the leaf grades
    (docs/SEP_FCOV.adoc). Same rules as ``graded_owner``: a no-op that returns False
    on Verilator. On VCS a sampler without the variable is a testbench error.
    """
    return _set_bound("efuse_sdis_hold_bound", clocks, "FCOV-EFUSE-SDIS-HOLD-BOUND", log)


def set_otbn_cap_kind(kind: int, log=None) -> bool:
    """Write ``u_sep_fcov.otbn_cap_kind`` (1 to 5, or 0 for none).

    The stimulus label of ``sep_otbn_op_cg.cp_capability``: the program class
    that the OTBN compute leaf runs (1 loop, 2 branch, 3 call and return, 4
    ``bn.addc`` carry, 5 ``bn.addm`` reduction). The leaf sets it only after
    the check of that program passed (after its ``ERR_BITS`` read and DMEM
    compare) and writes 0 at least one clock later. Same rules as ``graded_owner``: a no-op that returns False on
    Verilator. On VCS a sampler without the variable is a testbench error.
    """
    if not 0 <= kind <= 5:
        raise ValueError(f"otbn_cap_kind {kind} is not 0 to 5")
    return _set_bound("otbn_cap_kind", kind, "FCOV-OTBN-CAP-KIND", log)


def set_rom_flip_bits(bits: int, log=None) -> bool:
    """Write ``u_sep_fcov.rom_flip_bits`` (1 or 2, or 0 for none).

    The stimulus label of ``sep_mem_aperture_cg.cp_rom_noecc``: the number of
    flipped bits of the stored boot ROM word that the leaf reads next. The leaf
    sets it before the load and writes 0 after it. Same rules as
    ``graded_owner``: a no-op that returns False on Verilator. On VCS a sampler
    without the variable is a testbench error.
    """
    if not 0 <= bits <= 2:
        raise ValueError(f"rom_flip_bits {bits} is not 0 to 2")
    return _set_bound("rom_flip_bits", bits, "FCOV-ROM-FLIP-BITS", log)


def set_rom_noecc_pass(passed: bool, log=None) -> bool:
    """Write ``u_sep_fcov.rom_noecc_pass`` (1 after the check passes, else 0).

    The pass label of ``sep_mem_aperture_cg.cp_rom_noecc``. The sampler holds
    each labelled ROM load outcome inside the window of the boot ROM leaf as
    pending and samples the pending outcomes only when this value rises. The
    leaf writes 1 after CHK-ROM-NOECC of the graded instance passes and 0 after
    it. Same rules as ``graded_owner``: a no-op that returns False on
    Verilator. On VCS a sampler without the variable is a testbench error.
    """
    return _set_bound("rom_noecc_pass", int(bool(passed)), "FCOV-ROM-NOECC-PASS", log)


def set_rom_ap_pass(passed: bool, log=None) -> bool:
    """Write ``u_sep_fcov.rom_ap_pass`` (1 after the checks of a leg pass, else 0).

    The pass label of the other points of the boot ROM leaf (``cp_mem_x_class``
    and ``cp_macro_if`` ROM cells, ``cp_access_size``,
    ``cp_otf_reset_x_path[rom_read]``, ``cp_rom_write_master`` and
    ``cp_rom_write_response``). The sampler counts each legal outcome inside the
    window of that leaf as pending and samples the counts only when this value
    rises; the next window open drops them. The leaf writes 1 after the checks
    of a graded leg pass and 0 after it. Same rules as ``graded_owner``: a
    no-op that returns False on Verilator. On VCS a sampler without the
    variable is a testbench error.
    """
    return _set_bound("rom_ap_pass", int(bool(passed)), "FCOV-ROM-AP-PASS", log)


def set_test_en_pin_pass(cells: int, log=None) -> bool:
    """Write ``u_sep_fcov.te_pin_pass`` (a 4-bit cell mask, or 0 for none).

    The pass label of ``sep_static_tieoff_cg.cp_test_en_consumer``. Bit
    ``2 * test_en_i + class`` (class 0 clock gater, 1 AXI cell) set means that
    every graded pin of the class equaled ``test_en_i`` after that edge. The
    sampler samples a cell on the rise of its bit inside the window of
    ``sep_test_en_pin_reach_test``. The leaf writes 0 when it opens and before
    it closes its window, and the passed cells only after ``CHK-TEST-EN-PINS``
    passes. Same rules as ``graded_owner``: a no-op that returns False on
    Verilator. On VCS a sampler without the variable is a testbench error.
    """
    if not 0 <= cells <= 0xF:
        raise ValueError(f"te_pin_pass {cells:#x} is not a 4-bit mask")
    return _set_bound("te_pin_pass", cells, "FCOV-TEST-EN-PIN-PASS", log)


def set_dbg_axprot_pass(passed: bool, log=None) -> bool:
    """Write ``u_sep_fcov.dbg_axprot_pass`` (1 after the check passes, else 0).

    The pass label of ``sep_master_axprot_cg`` channels 5 and 6. The sampler
    holds each AxPROT value of a debug system-bus handshake inside the window
    of the debug master leaf, and samples them only when this value rises. The
    leaf writes 0 at the start of a leg and 1 after its AxPROT check of
    PR-DBG-SB passes. Same rules as ``graded_owner``: a no-op that returns False
    on Verilator. On VCS a sampler without the variable is a testbench error.
    """
    return _set_bound("dbg_axprot_pass", int(bool(passed)), "FCOV-DBG-AXPROT-PASS", log)


def set_rstvec_persist_pass(passed: bool, log=None) -> bool:
    """Write ``u_sep_fcov.rstvec_persist_pass`` (1 after the check passes, else 0).

    The pass label of ``sep_debug_trace_cg.cp_rstvec_persist``. The sampler
    holds the reset class of the latest CPU reset release whose first retired
    PC is the programmed vector as pending, and samples it only when this value
    rises. The reset entry leaf writes 0 at the start of a persistence leg and
    1 after that leg's persistence check passes. Same rules as
    ``graded_owner``: a no-op that returns False on Verilator. On VCS a sampler
    without the variable is a testbench error.
    """
    return _set_bound("rstvec_persist_pass", int(bool(passed)), "FCOV-RSTVEC-PERSIST-PASS", log)


def set_efimg_pass(passed: bool, log=None) -> bool:
    """Write ``u_sep_fcov.efimg_pass`` (1 after the check passes, else 0).

    The pass label of ``sep_lc_feat_ctrl_profile_cg.cp_presense_feat`` and
    ``sep_boot_milestone_cg.cp_sense_surface[status1_port1]``. The sampler holds
    each legal outcome inside the window of the eFuse image leaf and samples it
    only when this value rises. The leaf writes 0 before a graded step and 1
    after its check passes. Same rules as ``graded_owner``: a no-op that returns
    False on Verilator. On VCS a sampler without the variable is a testbench
    error.
    """
    return _set_bound("efimg_pass", int(bool(passed)), "FCOV-EFIMG-PASS", log)


def set_tch_overlap_pass(passed: bool, log=None) -> bool:
    """Write ``u_sep_fcov.tch_overlap_pass`` (1 after the check passes, else 0).

    The pass label of ``sep_token_channel_cg`` ``cp_token_hmac_overlap`` and
    ``cp_go_while_busy``. The sampler holds each event of those points inside
    the window of the token-channel leaf as pending, and samples it only when
    this value rises. The leaf writes 0 at the start of a leg and 1 after the
    check of that leg passes. Same rules as ``graded_owner``: a no-op that
    returns False on Verilator. On VCS a sampler without the variable is a
    testbench error.
    """
    return _set_bound("tch_overlap_pass", int(bool(passed)), "FCOV-TCH-OVERLAP-PASS", log)


def set_stm_shadow_wr_pass(cell: int | None, log=None) -> bool:
    """Write ``u_sep_fcov.stm_shadow_wr_pass`` (``cell`` + 1 after the check passes, else 0).

    The pass label of ``sep_efuse_secure_tm_cg.x_shadow_wr_block``. ``cell`` is
    ``target * 4 + source * 2 + strap`` (target 0 ``LOCKS``, 1 ``LOCKS_SPARE``, 2
    ``SIP_DIS``, 3 ``SYS_DIS``; source 0 frontdoor, 1 JTAG). The sampler holds the
    readback outcome of each protection-shadow write per cell inside the window
    of the secure test mode leaf, and samples a held cell only when this value
    changes to its code. The leaf writes the code after the check of that cell
    passes and 0 after. Same rules as ``graded_owner``: a no-op that returns
    False on Verilator. On VCS a sampler without the variable is a testbench
    error.
    """
    if cell is not None and not 0 <= cell < 16:
        raise ValueError(f"x_shadow_wr_block cell {cell} is outside 0..15")
    value = 0 if cell is None else cell + 1
    return _set_bound("stm_shadow_wr_pass", value, "FCOV-STM-SHADOW-WR-PASS", log)


def set_ef_hold_tag(tag: int, log=None) -> bool:
    """Write ``u_sep_fcov.ef_hold_tag`` (the tag of the graded step, or 0 for none).

    The held samples of the interface status, lock slot, token channel, secure
    test mode and shim response leaves (``sep_efuse_if_status_cg``,
    ``sep_efuse_lock_policy_cg``, ``sep_token_channel_cg``,
    ``sep_efuse_secure_tm_cg``, ``sep_efuse_jtag_policy_cg``,
    ``sep_efuse_field_value_cg``, ``sep_efuse_map_geometry_cg``,
    ``sep_sec_dis_robustness_cg``), and of the token fault leaf
    (``sep_token_fault_cg`` and the error value of ``sep_token_channel_cg``
    ``cp_code``), and of the locked-field leaf (the legal values of
    ``sep_efuse_lock_policy_cg.cp_locked_field_irq`` and
    ``sep_pic_source_map_cg.cp_src_exclusive_other`` bin ``s34``; an access
    of that leaf with tag 0 samples nothing). Inside the window of one of
    those leaves the sampler holds each event with the tag written here, and
    drops an event while the tag is 0. The leaf writes a new tag before each graded step and
    0 after it. Same rules as ``graded_owner``: a no-op that returns False on
    Verilator. On VCS a sampler without the variable is a testbench error.
    """
    return _set_bound("ef_hold_tag", tag, "FCOV-EF-HOLD-TAG", log)


def set_ef_hold_pass(tag: int, log=None) -> bool:
    """Write ``u_sep_fcov.ef_hold_pass`` (a passed step tag, or 0).

    The pass label of the held samples of ``set_ef_hold_tag``. When this value
    changes to a tag inside the window of the leaf, the sampler samples every
    event held with that tag and drops it from the hold. The leaf writes the tag
    after every check of that step passed, and 0 at least one ``clk_i`` cycle
    later. A window close of the locked-field leaf drops its held samples.
    Same rules as ``graded_owner``: a no-op that returns False on Verilator.
    On VCS a sampler without the variable is a testbench error.
    """
    return _set_bound("ef_hold_pass", tag, "FCOV-EF-HOLD-PASS", log)


def set_lock_exempt_pass(passed: bool, log=None) -> bool:
    """Write ``u_sep_fcov.lock_exempt_pass`` (1 after the check passes, else 0).

    The pass label of ``sep_efuse_lock_policy_cg.x_exempt_write`` bins
    ``bit0_prog_prod`` and ``bit3_prog_prod_end``. The sampler holds a PROD or
    PROD_END ``LC_STATE`` read after the resense that follows a landed
    ``LC_STATE`` program, and samples it only when this value rises. The lock
    slot leaf writes 0 before the program and 1 after ``CHK-LOCK-EXEMPT-PROG``
    passes. Same rules as ``graded_owner``: a no-op that returns False on
    Verilator. On VCS a sampler without the variable is a testbench error.
    """
    return _set_bound("lock_exempt_pass", int(bool(passed)), "FCOV-LOCK-EXEMPT-PASS", log)


def set_dma_smc_cpu_pass(passed: bool, log=None) -> bool:
    """Write ``u_sep_fcov.dma_smc_cpu_pass`` (1 after the check passes, else 0).

    The pass label of ``sep_dma_endpoint_cg.cp_dma_smc_beat`` bins
    ``cpu_sep_id_prot001_r`` and ``cpu_sep_id_prot001_w``. The sampler holds a
    CPU LSU beat on PR-SMC with the LSU source ID in AxUSER and AxPROT 0b001 as
    pending, and samples it only when this value rises. The leaf writes 0 at
    the start of the SMC leg and 1 after ``CHK-DMA-SMC`` grades that AxUSER and
    that AxPROT. Same rules as ``graded_owner``: a no-op that returns False on
    Verilator. On VCS a sampler without the variable is a testbench error.
    """
    return _set_bound("dma_smc_cpu_pass", int(bool(passed)), "FCOV-DMA-SMC-CPU-PASS", log)


def set_km_strm_pass(passed: bool, log=None) -> bool:
    """Write ``u_sep_fcov.km_strm_pass`` (1 after the check passes, else 0).

    The pass label of ``sep_km_drbg_fault_cg.cp_df_offset_race`` and of the
    ``first_active_cycle_tready_low`` bin of ``cp_df_stream_violation``. The
    sampler holds a first-active-cycle withdrawal whose read ended with SLVERR,
    data 0, STREAM_ERR 1, IRQ_STATUS.drbg_err 1 and a COUNT_BAD increment as
    pending, and samples it only when this value rises. The DRBG sampler leaf writes 0 at the
    start of each stream-error case and 1 after ``CHK-SMP-STRM`` passes on that
    case. Same rules as ``graded_owner``: a no-op that returns False on
    Verilator. On VCS a sampler without the variable is a testbench error.
    """
    return _set_bound("km_strm_pass", int(bool(passed)), "FCOV-KM-STRM-PASS", log)


def set_km_pwd_pass(passed: bool, log=None) -> bool:
    """Write ``u_sep_fcov.km_pwd_pass`` (1 after the check passes, else 0).

    The pass label of the ``withdraw_discards_prefetch`` bin of
    ``sep_km_drbg_sampler_cg.cp_smp_prefetch_active_read``. The sampler holds a
    withdrawal of a partial prefetch word whose next OKAY DATA read returned the
    first full beat after it as pending, and samples it only when this value
    rises. The DRBG sampler leaf writes 0 before its withdrawal leg and 1 after
    ``CHK-SMP-PRE-WITHDRAW`` passes (the next prefetched word is the second live
    beat, with no byte of the partial beat). Same rules as ``graded_owner``: a
    no-op that returns False on Verilator. On VCS a sampler without the variable
    is a testbench error.
    """
    return _set_bound("km_pwd_pass", int(bool(passed)), "FCOV-KM-PWD-PASS", log)


def set_km_efw_tm_pass(passed: bool, log=None) -> bool:
    """Write ``u_sep_fcov.km_efw_tm_pass`` (1 after the check passes, else 0).

    The pass label of the ``km_strap_set`` and ``host_strap_set`` cells of
    ``sep_km_otp_readout_cg.cp_efw_program``. The sampler holds each program
    in secure test mode as pending when the program interface is idle again,
    and samples it only when this value rises inside the owner window. The
    crossbar leaf writes 0 before its secure test programs and 1 after
    ``CHK-EFW-TM`` passes (equal KM and host results, no fuse change and a zero
    read word). Same rules as ``graded_owner``: a no-op that returns False on
    Verilator. On VCS a sampler without the variable is a testbench error.
    """
    return _set_bound("km_efw_tm_pass", int(bool(passed)), "FCOV-KM-EFW-TM-PASS", log)


# Bits of ``km_efw_prog_pass``: the ``km_unlocked_spare`` and ``km_write_locked``
# cells of ``sep_km_otp_readout_cg.cp_efw_program``.
KM_EFW_PROG_PASS_SPARE = 1 << 0
KM_EFW_PROG_PASS_DENY = 1 << 1


def set_km_efw_prog_pass(bits: int, log=None) -> bool:
    """Write ``u_sep_fcov.km_efw_prog_pass`` (the passed program checks, or 0).

    The pass label of the ``km_unlocked_spare`` (bit 0,
    ``KM_EFW_PROG_PASS_SPARE``) and ``km_write_locked`` (bit 1,
    ``KM_EFW_PROG_PASS_DENY``) cells of
    ``sep_km_otp_readout_cg.cp_efw_program``. The sampler holds a KM program as
    pending when the program interface is idle again with the result of its
    class, and samples it only when this value rises inside the owner window
    with the bit of that cell set. The crossbar leaf writes bit 0 after
    ``CHK-EFW-PROG`` passes and bit 1 after ``CHK-EFW-DENY`` passes, each alone
    and then 0. Same rules as ``graded_owner``: a no-op that returns False on
    Verilator. On VCS a sampler without the variable is a testbench error.
    """
    if bits >> 2:
        raise ValueError(f"km_efw_prog_pass bits {bits:#x} are not 0 to 3")
    return _set_bound("km_efw_prog_pass", bits, "FCOV-KM-EFW-PROG-PASS", log)


def set_km_xbar_pass(cells: int, windows: int, log=None, outcomes: int = 0) -> bool:
    """Write ``u_sep_fcov.km_xbar_pass`` (the graded decode cells, or 0).

    The pass label of ``sep_km_integrity_fault_cg`` (``cp_if_window``,
    ``cp_if_offset_class``, ``cp_if_decode_outcome``, ``cp_if_efuse_remap``,
    ``cp_if_vrom_outcome``) and of ``sep_km_otp_readout_cg.cp_efw_read_class``.
    Bit ``8 * row + class`` of ``cells`` is a graded offset cell of
    ``cp_if_offset_class``; bit ``w`` of ``windows`` is a graded window ``w``
    (0 to 23) of ``cp_if_window``. ``outcomes`` holds one bit per graded value:
    bit ``v`` (0 to 5) a ``cp_if_decode_outcome`` value, bit ``6 + v`` a
    ``cp_if_vrom_outcome`` value (and the ``vrom`` bin of ``cp_if_window``),
    bit ``8 + v`` a ``cp_if_efuse_remap`` value, bit ``10 + v`` (``v`` 0 to 11)
    a ``cp_efw_read_class`` value. The sampler holds each cell or value that a
    KM access completed with as seen, and samples the seen ones whose bit is
    set only when this value rises inside the owner window. The crossbar leaf
    writes 0 before its decode walk and the masks after ``CHK-XBAR``,
    ``CHK-XBAR-RSV``, ``CHK-XBAR-EFUSE``, ``CHK-XBAR-SIZE``, ``CHK-EFW-RD``
    and ``CHK-REMAP-BUS`` pass. Same rules as ``graded_owner``: a no-op that
    returns False on Verilator. On VCS a sampler without the variable is a
    testbench error.
    """
    if cells < 0 or cells >> 128 or windows < 0 or windows >> 24 or outcomes < 0 or outcomes >> 22:
        raise ValueError(
            f"km_xbar_pass masks out of range: cells={cells:#x} windows={windows:#x} "
            f"outcomes={outcomes:#x}"
        )
    if _gate_handle() is None:
        return False
    fcov = cocotb.top.u_sep_fcov
    if not hasattr(fcov, "km_xbar_pass"):
        raise AttributeError("u_sep_fcov has no km_xbar_pass variable (cov/sv/sep_fcov.sv)")
    fcov.km_xbar_pass.value = (outcomes << 152) | (windows << 128) | cells
    if log is not None:
        log.info(
            "FCOV-KM-XBAR-PASS cells=0x%032x windows=0x%06x outcomes=0x%06x",
            cells,
            windows,
            outcomes,
        )
    return True


def set_stitch_state_pass(passed: bool, log=None) -> bool:
    """Write ``u_sep_fcov.stitch_state_pass`` (1 after a state check passes, else 0).

    The pass label of the LC_STATE stitch leaf bins ``cp_stm_event_x_strap``
    ``sense_done_strap0`` / ``sense_done_strap1`` and ``cp_transition``
    ``test_dev_to_prod_prog``. The sampler holds each of those events inside
    the window of that leaf as pending, and samples it only when this value
    rises. The leaf writes 0 at the start of each state check and 1 after every
    check of that state passed. Same rules as ``graded_owner``: a no-op that
    returns False on Verilator. On VCS a sampler without the variable is a
    testbench error.
    """
    return _set_bound("stitch_state_pass", int(bool(passed)), "FCOV-STITCH-STATE-PASS", log)


# Bits of ``tr_pass``: the points of the transient RMA leaf.
TR_PASS_TRANSIENT = 1 << 0
TR_PASS_SIMUL = 1 << 1
TR_PASS_RESET = 1 << 2
TR_PASS_PROG_LC = 1 << 3


def set_transient_pass(bits: int, log=None) -> bool:
    """Write ``u_sep_fcov.tr_pass`` (the passed checks of the transient RMA leaf, or 0).

    The pass label of ``sep_lc_illegal_transition_cg`` ``x_transient`` (bit 0,
    ``TR_PASS_TRANSIENT``), ``cp_simultaneous_match`` (bit 1, ``TR_PASS_SIMUL``)
    and ``cp_reset_restore`` (bit 2, ``TR_PASS_RESET``), and of
    ``sep_efuse_lock_policy_cg.x_lc_prog_gate`` (bit 3, ``TR_PASS_PROG_LC``).
    The sampler holds each legal outcome of those points inside the window of
    the transient RMA leaf as pending, and samples it only when its bit rises.
    The leaf writes a bit after the check that grades that point passes
    (CHK-TRANSIENT, CHK-TRANSIENT-SIMUL, CHK-TRANSIENT-RESET, CHK-PROG-LC) and
    0 after. Same rules as ``graded_owner``: a no-op that returns False on
    Verilator. On VCS a sampler without the variable is a testbench error.
    """
    if bits >> 4 or bits < 0:
        raise ValueError(f"tr_pass bits {bits:#x} are not 0 to 15")
    return _set_bound("tr_pass", bits, "FCOV-TR-PASS", log)


def set_demote_pass(passed: bool, log=None) -> bool:
    """Write ``u_sep_fcov.dem_pass`` (1 after the checks of a cell pass, else 0).

    The pass label of ``sep_dtp_gating_ladder_cg`` ``x_path_case`` and
    ``x_prod_demote_case3``. The sampler holds the legal cells of each
    ``FEAT_CTRL`` read inside the window of the demote leaf as pending, and
    samples them only when this value rises. The leaf writes 1 after every
    check of a cell on the ``FEAT_CTRL`` value it read passed, and 0 after.
    Same rules as ``graded_owner``: a no-op that returns False on Verilator.
    On VCS a sampler without the variable is a testbench error.
    """
    return _set_bound("dem_pass", int(bool(passed)), "FCOV-DEM-PASS", log)


# Bits of ``ovr_pass``: the points of the SEC_DIS override leaf.
OVR_PASS_ALONE_OPEN = 1 << 0
OVR_PASS_STM0 = 1 << 1


def set_override_pass(bits: int, log=None) -> bool:
    """Write ``u_sep_fcov.ovr_pass`` (the passed checks of the SEC_DIS override leaf, or 0).

    The pass label of ``sep_sec_dis_boot_cg.cp_alone[override_open]`` (bit 0,
    ``OVR_PASS_ALONE_OPEN``) and ``sep_sec_dis_robustness_cg``
    ``x_secdis_stm_feat[secure_tm_0]`` (bit 1, ``OVR_PASS_STM0``). The sampler
    holds each event of those cells inside the window of the override leaf as
    pending, and samples it only when its bit rises. The leaf writes bit 0
    after CHK-OVR-AFTER passes and bit 1 after CHK-OVERRIDE-TM0 passes, and 0
    after. Same rules as ``graded_owner``: a no-op that returns False on
    Verilator. On VCS a sampler without the variable is a testbench error.
    """
    if bits >> 2 or bits < 0:
        raise ValueError(f"ovr_pass bits {bits:#x} are not 0 to 3")
    return _set_bound("ovr_pass", bits, "FCOV-OVR-PASS", log)


def close_graded_window(log=None) -> bool:
    """Write 0 (no window open). Returns True when written."""
    gate = _gate_handle()
    if gate is None:
        return False
    gate.value = 0
    if log is not None:
        log.info("FCOV-GATE closed")
    return True


def set_esrc_e2e_pass(passed: bool, log=None) -> bool:
    """Write ``u_sep_fcov.esrc_e2e_pass`` (1 after every check passed, else 0).

    The pass label of the end-to-end entropy leaf, both entries:
    ``sep_esrc_conditioning_cg`` ``cp_biw_scored``, ``cp_seed_handshake``,
    ``cp_genbits_fips[fips_1]``, ``cp_esrc_sink`` and ``cp_fifo_closed_seed``,
    and ``sep_esrc_fault_alert_cg.cp_fifo_flags[underflow_set]``. The sampler
    holds each event of those points inside the window of that leaf as
    pending, and samples it only when this value rises. The leaf writes 0
    before its window opens and 1 after every check of the run, the strict
    scoreboard report included, passed. Same rules as ``graded_owner``: a
    no-op that returns False on Verilator. On VCS a sampler without the
    variable is a testbench error.
    """
    return _set_bound("esrc_e2e_pass", int(bool(passed)), "FCOV-ESRC-E2E-PASS", log)


def set_trng_drain_pass(passed: bool, log=None) -> bool:
    """Write ``u_sep_fcov.trng_drain_pass`` (1 after the check passes, else 0).

    The pass label of ``sep_reset_scope_retention_cg.cp_trng_drain`` and of
    ``cp_iso_order_per_domain[trng_fall]``. The sampler holds each drain
    answer (OKAY, SLVERR) of a TRNG CSR read outstanding when the three TRNG
    paths report isolated, and the TRNG fall with those three paths isolated,
    inside the window of the TRNG reset recovery leaf, and samples them only
    when this value rises. The leaf writes 0 before its window opens and after
    it closes, and 1 after CHK-TRNG-DRAIN passes, which it reaches only after
    CHK-TRNG-ISOLATE-ALL and CHK-TRNG-CLEAR-SYNC passed. Same rules as ``graded_owner``: a no-op
    that returns False on Verilator. On VCS a sampler without the variable is
    a testbench error.
    """
    return _set_bound("trng_drain_pass", int(bool(passed)), "FCOV-TRNG-DRAIN-PASS", log)


def set_drbg_fatal_pass(passed: bool, log=None) -> bool:
    """Write ``u_sep_fcov.drbg_fatal_pass`` (1 after the checks of a step pass, else 0).

    The pass label of the forced-error leaf: ``sep_drbg_err_inject_cg``,
    ``sep_edn_mode_cg.cp_auto_fifo_words`` and the CSRNG and EDN ``ERR_CODE``
    cells of ``sep_crypto_reset_cg.cp_reset_evidence``. The sampler holds each
    sample of those cells inside the window of the leaf as pending, and samples
    it only when this value rises. The leaf writes 1 after every check of a
    source-bit cell or a command FIFO trial passed, and 0 after. Same rules as
    ``graded_owner``: a no-op that returns False on Verilator. On VCS a sampler
    without the variable is a testbench error.
    """
    return _set_bound("drbg_fatal_pass", int(bool(passed)), "FCOV-DRBG-FATAL-PASS", log)


def set_drbg_seq_pass(passed: bool, log=None) -> bool:
    """Write ``u_sep_fcov.drbg_seq_pass`` (1 after the checks of an instance pass, else 0).

    The pass label of the DRBG command-sequence leaf: every sample that its
    window takes in ``sep_csrng_cmd_cg``, ``sep_edn_mode_cg``,
    ``sep_crypto_alert_cg.cp_csrng_recov_seq`` and the ``x_line_gate`` and
    ``cp_hw_raise`` cells of ``sep_crypto_intr_cg``. The sampler holds each
    such sample as pending and samples it only when this value rises; the
    pending list clears when the window of the leaf opens. The leaf writes 1
    after every check since its last write of 1 passed, and 0 after. Same
    rules as ``graded_owner``: a no-op that returns False on Verilator. On VCS
    a sampler without the variable is a testbench error.
    """
    return _set_bound("drbg_seq_pass", int(bool(passed)), "FCOV-DRBG-SEQ-PASS", log)


def set_drbg_seq_drop(drop: bool, log=None) -> bool:
    """Write ``u_sep_fcov.drbg_seq_pass`` = 2 (drop) or 0.

    The DRBG command-sequence leaf writes 2 and then 0 when a check or control
    since its last write of ``drbg_seq_pass`` failed. The rise to 2 drops every
    pending sample of that label, so a later pass cannot release a sample of a
    failed instance. Same rules as ``graded_owner``: a no-op that returns False
    on Verilator. On VCS a sampler without the variable is a testbench error.
    """
    return _set_bound("drbg_seq_pass", 2 if drop else 0, "FCOV-DRBG-SEQ-DROP", log)


# Bits of ``u_sep_fcov.esrc_tune_pass``.
ESRC_TUNE_PASS_TUNING = 1 << 0  # the tuning legs passed
ESRC_TUNE_PASS_SCLK = 1 << 1  # CHK-SCLK-DIV of the in-window instance passed (cp_div_ratio)


def set_esrc_tune_pass(passed: bool, log=None, bits: int = ESRC_TUNE_PASS_TUNING) -> bool:
    """Write ``u_sep_fcov.esrc_tune_pass`` (``bits`` after the checks pass, else 0).

    The pass label of ``sep_esrc_noise_gen_cg`` ``cp_detune_mode`` and
    ``cp_detune_lane``, of ``sep_esrc_fault_alert_cg.cp_autotune`` and of the
    AUTOTUNE_FAIL cells of ``sep_crypto_intr_cg`` ``x_esrc_status_enable`` and
    ``cp_esrc_raise_path``. The
    sampler holds each hit of those bins inside the window of the autotune
    detune leaf as pending, and samples them only when this value rises; the
    opening of that window drops older pending hits. The leaf writes 0 before
    its tuning legs and pulses bit 0 after every check and control of those legs
    passed. Bit 1 (``ESRC_TUNE_PASS_SCLK``) is the label of
    ``sep_esrc_noise_gen_cg.cp_div_ratio``: the leaf writes it after the
    in-window CHK-SCLK-DIV instance of a divide value passes, and the sampler
    samples the lane-period hits of that window only on its rise. Same rules as
    ``graded_owner``: a no-op that returns False on Verilator. On VCS a sampler
    without the variable is a testbench error.
    """
    if bits not in (ESRC_TUNE_PASS_TUNING, ESRC_TUNE_PASS_SCLK):
        raise ValueError(f"esrc_tune_pass bits {bits:#x} are not one label bit")
    return _set_bound("esrc_tune_pass", bits if passed else 0, "FCOV-ESRC-TUNE-PASS", log)


def set_km_ss_pass(passed: bool, log=None) -> bool:
    """Write ``u_sep_fcov.km_ss_pass`` (1 after the check passes, else 0).

    The pass label of ``sep_km_sideload_delivery_cg.cp_sd_single_share``. The
    sampler holds the cell of a single-share AES delivery after a KM wipe as
    pending from the KEY_VALID rise, and samples it only when this value rises.
    The key-bank leaf writes 0 before each single-share instance and 1 after
    ``CHK-SINGLE-SHARE`` passes on that instance (the sideload ciphertext equals
    the AES-256 golden of the written key). Same rules as ``graded_owner``: a
    no-op that returns False on Verilator. On VCS a sampler without the
    variable is a testbench error.
    """
    return _set_bound("km_ss_pass", int(bool(passed)), "FCOV-KM-SS-PASS", log)


# Bits of ``u_sep_fcov.km_sk_pass``, the shared-key pass label of the key-bank leaf.
KM_SK_PASS_CONSUME = 1 << 0
KM_SK_PASS_WORDS = 1 << 1
KM_SK_PASS_IRQ = 1 << 2


def set_km_sk_pass(bits: int, log=None) -> bool:
    """Write ``u_sep_fcov.km_sk_pass`` (the passed shared-key checks, or 0).

    The pass label of ``sep_km_abr_shared_key_cg``. The sampler holds the
    ``cp_sk_write_dir`` cells from the ``MLKEM_SHARED_KEY.KEY_CTRL`` writes and
    samples them on the rise of ``KM_SK_PASS_CONSUME``, which the key-bank leaf
    writes after ``CHK-BANK-SK-CONSUME`` passes. It holds
    ``cp_sk_delivery_state[firmware_consumes]`` and samples it on the rise of
    ``KM_SK_PASS_WORDS``, written after ``CHK-BANK-SK-SW`` passes. It holds the
    ``cp_sk_interrupt`` line cells and samples them on the rise of
    ``KM_SK_PASS_IRQ``, written after ``CHK-BANK-SK-IRQ`` passes; any other
    change of the label drops them. The leaf writes 0 before the consume step
    and before the interrupt step. Same rules as ``graded_owner``: a no-op
    that returns False on Verilator. On VCS a sampler without the variable is a
    testbench error.
    """
    return _set_bound("km_sk_pass", bits & 0b111, "FCOV-KM-SK-PASS", log)


# Bits of ``u_sep_fcov.xhs_pass``, the pass label of the external stream handshake
# leaf. Index 0 is the crypto stream (1), index 1 the pool stream (2); the depth
# bits are indexed by the internal stream 0, 1, 2.
XHS_PASS_FULL = (1 << 0, 1 << 1)
XHS_PASS_PARTIAL = (1 << 2, 1 << 3)
XHS_PASS_STALL = (1 << 4, 1 << 5)
XHS_PASS_POOL_POP = 0b111 << 6
XHS_PASS_FIFO_DEPTH = (1 << 9, 1 << 10, 1 << 11)
XHS_PASS_WIDTH = 12


def set_xhs_pass(bits: int, log=None) -> bool:
    """Write ``u_sep_fcov.xhs_pass`` (the passed checks of the external stream leaf, or 0).

    The pass label of ``sep_entropy_delivery_cg`` ``x_ext_beat`` (``XHS_PASS_FULL``,
    ``XHS_PASS_PARTIAL``), ``cp_ext_stall`` (``XHS_PASS_STALL``), ``cp_pool_pop``
    (``XHS_PASS_POOL_POP``: pop at level 2 to 31, pop at 32, feed at 31) and
    ``cp_adapter_fifo_depth`` (``XHS_PASS_FIFO_DEPTH``). Inside the window of the
    external stream handshake leaf the sampler holds each event of those cells as
    pending, and samples it only when its bit rises; a closed window drops it, and a
    broken hold drops a held depth cell. The leaf writes the bits after the check
    that grades the cell passes, and 0 after. Same rules as ``graded_owner``: a no-op
    that returns False on Verilator. On VCS a sampler without the variable is a
    testbench error.
    """
    if bits < 0 or bits >> XHS_PASS_WIDTH:
        raise ValueError(f"xhs_pass bits {bits:#x} are not {XHS_PASS_WIDTH} bits")
    return _set_bound("xhs_pass", bits, "FCOV-XHS-PASS", log)


def set_iprst_edn_pass(passed: bool, log=None) -> bool:
    """Write ``u_sep_fcov.iprst_edn_pass`` (1 after the check passes, else 0).

    The pass label of the legal cells of
    ``sep_crypto_reset_cg.cp_sw_rst_edn_cancel``. The sampler holds each clean
    cancel inside the window of the per-IP reset leaf as pending from the
    reset release, and samples them only when this value rises. The leaf writes
    0 at its start and 1 after CHK-EDN-DISCARD passes, then 0. Same rules as
    ``graded_owner``: a no-op that returns False on Verilator. On VCS a sampler
    without the variable is a testbench error.
    """
    return _set_bound("iprst_edn_pass", int(bool(passed)), "FCOV-IPRST-EDN-PASS", log)


# Bits of ``u_sep_fcov.esrc_pa_pass``: one per check of the persistent-alert
# leaf that releases held cells (the CzPa* localparams of cov/sv/sep_fcov.sv).
ESRC_PA_RESET = 1 << 0  # CHK-PF-RESET
ESRC_PA_TRIP_COUNT = 1 << 1  # CHK-PF-TRIP-COUNT
ESRC_PA_NOTRIP = 1 << 2  # CHK-PF-NOTRIP
ESRC_PA_CONSEC = 1 << 3  # CHK-PF-CONSEC
ESRC_PA_DISABLE = 1 << 4  # CHK-PF-DISABLE
ESRC_PA_HALT = 1 << 5  # CHK-PF-HALT
ESRC_PA_RECOVER_E = 1 << 6  # CHK-PF-RECOVER, exit by MODULE_ENABLE
ESRC_PA_RECOVER_R = 1 << 7  # CHK-PF-RECOVER, exit by TRNG reset
ESRC_PA_SM_ERR = 1 << 8  # CHK-SM-ERR legs set and reset_clears (cp_sm_err, PERSISTENT_FAILURE)


def set_esrc_pa_pass(bits: int, log=None) -> bool:
    """Write ``u_sep_fcov.esrc_pa_pass`` (the passed check bits ``ESRC_PA_*``, or 0).

    The pass label of the cells that ``sep_esrc_persistent_alert_rand_test``
    owns in ``sep_esrc_fault_alert_cg`` (``cp_alert_threshold``, ``cp_any_fail``,
    ``cp_alert_hang``, ``cp_sm_err``), ``sep_esrc_startup_health_cg`` (``cp_window_class``,
    ``x_enable_boot``) and ``sep_crypto_intr_cg`` (the PERSISTENT_FAILURE cells
    of ``x_esrc_status_enable`` and ``cp_esrc_raise_path``). The sampler holds
    each event of those cells inside the window of the leaf as pending, clears
    the pending cells when a window opens, and samples a cell only when a bit of
    a check that grades it rises. The leaf writes the bit after that check
    passes, holds it two clocks and writes 0. Same rules as ``graded_owner``: a
    no-op that returns False on Verilator. On VCS a sampler without the variable
    is a testbench error.
    """
    if bits >> 9 or bits < 0:
        raise ValueError(f"esrc_pa_pass bits {bits:#x} are not 0 to 0x1ff")
    return _set_bound("esrc_pa_pass", bits, "FCOV-ESRC-PA-PASS", log)


def set_bfault_pass(passed: bool, log=None) -> bool:
    """Write ``u_sep_fcov.bfault_pass`` (1 after the checks of an instance pass, else 0).

    The pass label of the points that ``sep_cpu_bridge_fault_matrix_rand_test``
    owns in ``sep_fault_source_report_cg``, ``sep_fault_source_ack_cg`` and
    ``sep_dma_host_fault_cg``. The sampler holds each legal outcome inside the
    window of that leaf as pending and samples the held outcomes only when this
    value rises; a fall to 0, a window close and a reset drop them. The leaf
    writes 0 at the start of a graded instance and 1 after the checks of that
    instance pass. Same rules as ``graded_owner``: a no-op that returns False on
    Verilator. On VCS a sampler without the variable is a testbench error.
    """
    return _set_bound("bfault_pass", int(bool(passed)), "FCOV-BFAULT-PASS", log)


# Bits of ``u_sep_fcov.km_cpu_pass``: one per check of the KM cpu-protect leaf
# that releases held cells (the Kcp* localparams of cov/sv/sep_fcov.sv).
KCP_TRAP = 0  # CHK-TRAP-WIPE and CHK-TRAP-CLR of a trap kind
KCP_EXEC_OK = 1  # CHK-EXEC-OK (C0, C2)
KCP_EXEC = 2  # CHK-EXEC (C1, C3, C5, C6)
KCP_LOCKOUT = 3  # CHK-LOCKOUT (C2)
KCP_EXEC_RST = 4  # CHK-EXEC-RST
KCP_LOCK_FETCH = 5  # CHK-LOCKOUT-FETCH and CHK-LOCKOUT-ORDER (C4)


def set_km_cpu_pass(bits: int, log=None) -> bool:
    """Write ``u_sep_fcov.km_cpu_pass`` (the passed check bits ``1 << KCP_*``, or 0).

    The pass label of the cells that ``sep_km_cpu_protect_rand_test`` owns in
    ``cp_mem_iface_req``, the execute-protection points, ``cp_fr_err_out``
    (except ``port_equals_pic``), ``cp_km_trap_cause``, ``cp_vw_pre_contents``,
    ``cp_vw_effect`` and ``cp_if_rom_write``. The sampler holds each event of
    those cells inside the window of the leaf as pending, clears the pending
    cells on every clock with the window closed, and samples a cell only when a
    bit of a check that grades it rises. The leaf writes the bit after that
    check passes, holds it two clocks and writes 0. Same rules as
    ``graded_owner``: a no-op that returns False on Verilator. On VCS a sampler
    without the variable is a testbench error.
    """
    if bits >> 6 or bits < 0:
        raise ValueError(f"km_cpu_pass bits {bits:#x} are not 0 to 0x3f")
    return _set_bound("km_cpu_pass", bits, "FCOV-KM-CPU-PASS", log)


def set_lite_split_pass(passed: bool, log=None) -> bool:
    """Write ``u_sep_fcov.lite_split_pass`` (1 after the check passes, else 0).

    The pass label of ``sep_fabric_inbound_aperture_cg.cp_lite_split``. The
    sampler holds the cell of the last System Interface completion inside the
    window of ``sep_fabric_inbound_filter_rule_matrix_test`` and samples it
    only when this value rises. The leaf writes 0 before each burst, and 1
    after the check of that burst passes, holds it two clocks and writes 0.
    Same rules as ``graded_owner``: a no-op that returns False on Verilator.
    On VCS a sampler without the variable is a testbench error.
    """
    return _set_bound("lite_split_pass", int(bool(passed)), "FCOV-LITE-SPLIT-PASS", log)


def set_row_pass(value: int, log=None) -> bool:
    """Write ``u_sep_fcov.row_pass`` (1 release, 2 drop, 3 release with cache,
    4 release of the TRNG reply samples, 0 idle).

    The pass label of ``sep_fabric_row_response_matrix_test`` (owner 231):
    ``sep_aperture_reserved_access_cg`` (``cp_row_cell``, ``cp_row_init_dir``,
    ``cp_aperture_offset_dir``, ``cp_non_aliasing``),
    ``sep_crypto_bus_access_cg.cp_otbn_cache_reg``, the legal
    ``cp_burst_region`` bins and ``cp_si_pool``. Also the label of
    ``sep_unmapped_access_policy_test`` (owner 755: ``cp_row_cell``,
    ``cp_array_tail``) and ``sep_fabric_deadspace_decode_test`` (owner 234:
    ``cp_row_cell``, the legal ``sep_fabric_trng_reply_cg`` samples). The
    sampler holds each sample of those points inside the window of its owner as
    pending and samples it only when this value rises to 1, 3 or 4; a rise to 2
    drops every pending sample. ``cp_otbn_cache_reg`` samples only on a rise to
    3; the TRNG reply samples only on a rise to 4, which samples no other held
    sample; any other rise drops the held samples it does not release. The leaf
    writes 2 and then 0 at the start of each graded instance and 2 when a check
    fails, and writes 1 (3 for an instance of the OTBN cache leg after
    CHK-ROW-CACHE, 4 for a repeated TRNG access after its check) and then 0
    after every check of the instance passed. Same rules as ``graded_owner``: a
    no-op that returns False on Verilator. On VCS a sampler without the
    variable is a testbench error.
    """
    if value not in (0, 1, 2, 3, 4):
        raise ValueError(f"row_pass {value} is not 0, 1, 2, 3 or 4")
    return _set_bound("row_pass", value, "FCOV-ROW-PASS", log)


def set_rebase_pass(passed: bool, log=None) -> bool:
    """Write ``u_sep_fcov.rebase_pass`` (1 after the check passes, else 0).

    The pass label of ``sep_fabric_inbound_aperture_cg.cp_filter_order``. The
    sampler holds each code of the window of ``sep_fabric_inbound_rebase_test``
    and samples the held codes only when this value rises inside that window.
    The leaf writes 1 after CHK-REBASE-FILTER-FIRST passes, holds it two clocks
    and writes 0. Same rules as ``graded_owner``: a no-op that returns False on
    Verilator. On VCS a sampler without the variable is a testbench error.
    """
    return _set_bound("rebase_pass", int(bool(passed)), "FCOV-REBASE-PASS", log)


def set_writeback_pass(passed: bool, log=None) -> bool:
    """Write ``u_sep_fcov.writeback_pass`` (1 after the check passes, else 0).

    The pass label of ``sep_filter_range_granule_cg.cp_writeback``. The sampler
    holds each read-back code of the window of
    ``sep_fabric_inbound_filter_window_walk_test`` and samples the held codes
    only when this value rises inside that window. The leaf writes 1 after
    CHK-WALK-WRITEBACK of the graded pass passes over all four halves, holds it
    two clocks and writes 0. Same rules as ``graded_owner``: a no-op that
    returns False on Verilator. On VCS a sampler without the variable is a
    testbench error.
    """
    return _set_bound("writeback_pass", int(bool(passed)), "FCOV-WRITEBACK-PASS", log)


def set_pbem_pass(passed: bool, log=None) -> bool:
    """Write ``u_sep_fcov.pbem_pass`` (1 after the checks pass, else 0).

    The pass label of ``sep_fault_source_report_cg.cp_partial_narrow``. The
    sampler holds each partial-write and narrow-read outcome of the window of
    ``sep_periph_bus_err_misaligned_test`` and samples the held outcomes only
    when this value rises inside that window. The leaf writes 1 after
    CHK-MISALIGN-RD and CHK-MISALIGN-LATCH of a block probe pass, holds it two
    clocks and writes 0. Same rules as ``graded_owner``: a no-op that returns
    False on Verilator. On VCS a sampler without the variable is a testbench
    error.
    """
    return _set_bound("pbem_pass", int(bool(passed)), "FCOV-PBEM-PASS", log)


# Sources whose cp_src_exclusive_other bin waits for the exo_pass label.
EXO_PASS_SOURCES = (35, 36, 41, 42, 43)


def exo_pass_bit(src: int) -> int:
    """Bit of ``exo_pass`` that releases the held ``cp_src_exclusive_other`` bin of ``src``."""
    if src not in EXO_PASS_SOURCES:
        raise ValueError(f"source {src} has no exo_pass bit (sources {EXO_PASS_SOURCES})")
    return 1 << (src - 32)


def set_exo_pass(mask: int, log=None) -> bool:
    """Write ``u_sep_fcov.exo_pass`` (one bit per passed EXCL check, or 0).

    The pass label of ``sep_pic_source_map_cg.cp_src_exclusive_other`` bins
    s35, s36 and s41 to s43. The sampler holds each exclusive rise of those
    sources in the window of their owner and samples a held rise only when bit
    ``source - 32`` (``exo_pass_bit``) rises; the release does not depend on
    the window. The owner writes the bit after CHK-SRC<source>-EXCL passes,
    keeps the bits of the checks that passed before it, holds the value at
    least one clock and writes 0 at the end. Same rules as ``graded_owner``: a
    no-op that returns False on Verilator. On VCS a sampler without the
    variable is a testbench error.
    """
    allowed = 0
    for src in EXO_PASS_SOURCES:
        allowed |= exo_pass_bit(src)
    if mask & ~allowed:
        raise ValueError(f"exo_pass 0x{mask:x} sets a bit outside 0x{allowed:x}")
    return _set_bound("exo_pass", mask, "FCOV-EXO-PASS", log)


# Bits of ``u_sep_fcov.abr_pic_pass``: one per bin of
# ``sep_abr_completion_cg.cp_abr_pic``, each written after the check of its edge.
ABR_PIC_ERROR_RISE = 0  # error_rise_on_trig, CHK-PIC-ERROR-RISE
ABR_PIC_ERROR_W1C = 1  # error_fall_on_w1c, CHK-PIC-ERROR-W1C
ABR_PIC_NOTIF_RISE = 2  # notif_rise_on_done, CHK-PIC-NOTIF-RISE
ABR_PIC_NOTIF_W1C = 3  # notif_fall_on_w1c, CHK-PIC-NOTIF-W1C
ABR_PIC_PASS_BITS = 4


def set_abr_pic_pass(mask: int, log=None) -> bool:
    """Write ``u_sep_fcov.abr_pic_pass`` (one bit per passed edge check, or 0).

    The pass label of ``sep_abr_completion_cg.cp_abr_pic``. The sampler holds
    the first armed edge of each bin inside the window of
    ``sep_abr_mldsa_keygen_kat_test`` and samples it only when the bit of that
    bin (``ABR_PIC_*``) rises inside that window; the next write that arms the
    bin, a window close and a reset drop it. The owner writes the bit after the
    check of that edge passes, keeps the bits of the checks that passed before
    it, holds the value at least one clock and writes 0 at the end. Same rules
    as ``graded_owner``: a no-op that returns False on Verilator. On VCS a
    sampler without the variable is a testbench error.
    """
    if mask < 0 or mask >> ABR_PIC_PASS_BITS:
        raise ValueError(f"abr_pic_pass 0x{mask:x} is out of range")
    return _set_bound("abr_pic_pass", mask, "FCOV-ABR-PIC-PASS", log)
