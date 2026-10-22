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


def close_graded_window(log=None) -> bool:
    """Write 0 (no window open). Returns True when written."""
    gate = _gate_handle()
    if gate is None:
        return False
    gate.value = 0
    if log is not None:
        log.info("FCOV-GATE closed")
    return True
