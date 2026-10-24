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
    ``bn.addc`` carry, 5 ``bn.addm`` reduction). The leaf sets it before the
    command write of the program and writes 0 after the DMEM compare of that
    program. Same rules as ``graded_owner``: a no-op that returns False on
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
    ``sep_sec_dis_robustness_cg``). Inside the window of one of those leaves the
    sampler holds each event with the tag written here, and drops an event
    while the tag is 0. The leaf writes a new tag before each graded step and
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
    later. Same rules as ``graded_owner``: a no-op that returns False on
    Verilator. On VCS a sampler without the variable is a testbench error.
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


def set_km_lat_graded(on: bool, log=None) -> bool:
    """Write ``u_sep_fcov.km_lat_graded`` (1 while the latency watcher grades, else 0).

    The sub-window of ``sep_km_memory_boot_cg.cp_km_sram_latency``. The KM fault
    leaf writes 1 after its latency watcher starts on the fixed and the random
    latency runs, and 0 before the watcher stops. The bins sample only while it
    is 1 inside the owner window, so a read that no latency check grades (the
    L = 1 control run, the fatal points, a boot) fills no bin. Same rules as
    ``graded_owner``: a no-op that returns False on Verilator. On VCS a sampler
    without the variable is a testbench error.
    """
    return _set_bound("km_lat_graded", int(bool(on)), "FCOV-KM-LAT-GRADED", log)


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
