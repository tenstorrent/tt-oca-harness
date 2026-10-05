# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""eFuse/OTP bounded semantics helpers for SMC OSS tests.

The eFuse-bank AXI-Lite activity probe ``tb_axil_efuse_bank_active``
(``hw/sys/smc/dv/tb/tb_top.sv``: OR of
``u_dut.u_smc.efuse_bank_ctrl_req_o.{aw_valid,w_valid,ar_valid}``) is proven in
**two legs**, and a test that wants to present the idle leg as evidence must run
both:

1. **Positive control** -- :func:`prove_efuse_bank_axil_activity` drives a real
   SEP_IN AXI read into the eFuse-shim window and requires the probe to be
   *sampled at 1* while the request is in flight. Without this leg an ``== 0``
   assertion on the probe is indistinguishable from a stuck-at-0 / undriven /
   mis-tied activity sensor, and passes on a completely dead eFuse-bank master
   (`[NEGATIVE-NEEDS-POSITIVE-CONTROL]`).
2. **Idle re-check** -- :func:`check_efuse_otp_observability` re-samples the same
   probe after the bounded OTP/chip-config work and requires it back at 0.

:func:`check_efuse_otp_observability` labels its retained evidence line
according to whether leg 1 actually ran in the same test: it emits the
``CHK-EFUSE-BANK-IDLE`` evidence token only when the positive control was
observed, and otherwise logs a WARNING saying the idle observation is not
closure evidence. Callers that own an idle claim must therefore call
:func:`prove_efuse_bank_axil_activity` from their sequence body first (see
``smc_efuse_otp_clock_test_seq``).

Public API for other modules: :func:`prove_efuse_bank_axil_activity` (with
``record=False`` when the call is borrowed as stimulus for a different probe),
:func:`consume_positive_control`, :func:`check_efuse_otp_observability`,
:func:`count_probe_high_cycles` and :func:`stop_sampler`. ``_POSITIVE_CONTROL``
is module-private -- no cross-module ``.pop()``.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge

from .smc_addr_map import _REPO, _field_mask, smc_addr, smc_bootrom_addr

# --- eFuse preload asset (authoritative source for map-read expectations) ---
#
# The bench-wide ``+smc_efuse_hex`` plusarg (``smc_sim_cfg.toml:132-134``) makes
# ``efuse_bank_model.sv:140-160`` ``$readmemh`` this file into the bank storage
# at time 0, one 32-bit word per line, word ``n`` backing
# ``SMC_TOP_SMC_EFUSE_MAP_BASE_ADDR + 4*n``. Tests that want an exact expectation
# for a map read derive it from this file at run time, so the expectation
# follows a regenerated asset
# ([NO-UNJUSTIFIED-PRELOAD] / [ADDRESS-FROM-AUTHORITATIVE-MAP]).
#
# Proof class of anything checked this way is **transport**: it proves the map
# window decodes and returns the sensed word, not that fuse programming works.
EFUSE_DEFAULT_HEX = _REPO / "hw" / "sys" / "smc" / "dv" / "assets" / "smc_efuse_default.hex"
EFUSE_MAP_BASE = smc_addr("SMC_TOP_SMC_EFUSE_MAP_BASE_ADDR")
EFUSE_MAP_SIZE = smc_addr("SMC_TOP_SMC_EFUSE_MAP_SIZE")

_SMC_EFUSE_MAP_H = (
    _REPO / "hw" / "sys" / "smc" / "regs" / "gen" / "c" / "blocks" / "smc_efuse_map.h"
)


@lru_cache(maxsize=1)
def efuse_preload_words(path: Path | None = None) -> tuple[int, ...]:
    """Parse the eFuse preload hex asset into a tuple of 32-bit words."""
    src = Path(path) if path is not None else EFUSE_DEFAULT_HEX
    words: list[int] = []
    for raw in src.read_text(encoding="utf-8").splitlines():
        line = raw.split("//", 1)[0].strip()
        if line:
            words.append(int(line, 16))
    if not words:
        raise RuntimeError(f"no eFuse preload words parsed from {src}")
    return tuple(words)


def efuse_preload_word_at(addr: int) -> int:
    """Preload word backing SMC_EFUSE_MAP address ``addr`` (32-bit aligned)."""
    assert EFUSE_MAP_BASE <= addr < EFUSE_MAP_BASE + EFUSE_MAP_SIZE, (
        f"0x{addr:08x} is outside SMC_EFUSE_MAP "
        f"[0x{EFUSE_MAP_BASE:08x}, 0x{EFUSE_MAP_BASE + EFUSE_MAP_SIZE:08x})"
    )
    assert addr % 4 == 0, f"0x{addr:08x} is not 32-bit aligned"
    words = efuse_preload_words()
    idx = (addr - EFUSE_MAP_BASE) // 4
    assert idx < len(words), (
        f"0x{addr:08x} is word {idx} but {EFUSE_DEFAULT_HEX.name} holds only {len(words)} word(s)"
    )
    return words[idx]


def efuse_map_read_locked(lock_field_symbol: str) -> bool:
    """Is a SMC_EFUSE_MAP region read-locked by the preloaded LOCKS word?

    ``SMC_EFUSE_MAP.LOCKS`` is itself fuse-backed: it is word 0/1 of the preload
    asset, and each ``*_READ_LOCK`` bit position comes from the generated
    ``blocks/smc_efuse_map.h``. Callers therefore derive "this region reads back
    the blocked signature" from the *asset plus the generated map*, never from
    an observed read.
    """
    mask = _field_mask(_SMC_EFUSE_MAP_H, lock_field_symbol)
    locks_lo = efuse_preload_word_at(smc_addr("SMC_TOP_SMC_EFUSE_MAP_LOCKS_BASE_ADDR"))
    locks_hi = efuse_preload_word_at(smc_addr("SMC_TOP_SMC_EFUSE_MAP_LOCKS_BASE_ADDR") + 4)
    locks = (locks_hi << 32) | locks_lo
    return bool(locks & mask)


# Data returned on a blocked eFuse read. SPEC: "When a request is blocked, the
# error slave returns an error response with data value 0xbadcab1e"
# (hw/ip/efuse/doc/architecture.adoc:354-356). That sentence describes the JTAG
# lifecycle error slave; it states no response code for a lock-blocked
# SMC_EFUSE_MAP read.
EFUSE_BLOCKED_READ_DATA = 0xBADCAB1E

# Positive-control stimulus target, addressed by generated symbol (no hand
# literal): the eFuse-shim AXI-Lite window at 0xC040_0000.
#
# Why this window and not the EFUSE_READ_CTRL FSM: the eFuse read/program
# interfaces reach the macro over the separate custom command port
# ``efuse_shim_command_req_o``, so triggering a fuse read does NOT move
# ``efuse_bank_ctrl_req_o``. The only fabric stimulus that does is an access
# routed to the eFuse leg whose address falls outside the eFuse map / interface
# CSR ranges: ``smc_periph_axi_lite_xbar.sv`` maps 0xC040_0000 (+EFUSE_SHIM_SIZE)
# to the eFuse leg, and ``efuse_interface_controller.sv`` decodes anything
# outside [SMC_EFUSE_MAP .. EFUSE_INTERFACE_CTRL] to ``SHIM_SEL``, i.e. straight
# out on ``efuse_bank_ctrl_req_o``.
EFUSE_SHIM_CTRL_WINDOW = smc_bootrom_addr(
    "SMC_TOP_SMC_EXTERNAL_MANDATORY_EFUSE_SHIM_CTRL_BASE_ADDR"
)

# Offset 0 of that window is implemented by ``efuse_shim_ctrl_reg``
# (``hw/ip/efuse/dv/models/regs/efuse_shim_ctrl.rdl``) as EFUSE_BANK_INIT_TIME,
# field ``init_time[31:0]`` declared ``sw=rw; hw=r`` -- hardware never writes it,
# so the RDL reset is the expected value for a first read after reset.
#
# The value is imported by symbol from the generated PeakRDL C header
# (``EFUSE_SHIM_CTRL__EFUSE_BANK_INIT_TIME__INIT_TIME_reset``), so it follows
# an RDL regeneration ([ADDRESS-FROM-AUTHORITATIVE-MAP]).
_EFUSE_SHIM_CTRL_H = (
    _REPO / "hw" / "ip" / "efuse" / "dv" / "models" / "regs" / "gen" / "c" / "efuse_shim_ctrl.h"
)
EFUSE_BANK_INIT_TIME_RESET = _field_mask(
    _EFUSE_SHIM_CTRL_H, "EFUSE_SHIM_CTRL__EFUSE_BANK_INIT_TIME__INIT_TIME_reset"
)

# Consume-once record of the positive-control observation so the idle leg can
# state, in the kept log, whether it is backed by one *in this test*.
# Module-private: use the public
# ``prove_efuse_bank_axil_activity(..., record=False)`` / :func:
# ``consume_positive_control`` API below instead of reaching in from another
# module ([REUSE-AND-LAYERING]).
_POSITIVE_CONTROL: list[str] = []


def consume_positive_control() -> str | None:
    """Take this test's pending eFuse-bank positive-control credit, if any.

    Public accessor for the consume-once record above. Returns the observation
    string and clears it, or ``None`` when no positive control ran in this test.
    A caller that borrows :func:`prove_efuse_bank_axil_activity` purely as
    stimulus for a *different* probe (see ``smc_diagnostic_vip_utils``) should
    prefer ``record=False`` so no credit is ever created; this accessor exists
    for the callers that must drop a credit they cannot own.
    """
    return _POSITIVE_CONTROL.pop() if _POSITIVE_CONTROL else None


def stop_sampler(task) -> None:
    """Stop a ``count_probe_high_cycles`` task."""
    task.cancel()


async def count_probe_high_cycles(sig, clk, hits: list[int]) -> None:
    """Sample ``sig`` on every ``clk`` rising edge and count resolved 1s.

    Shared by the eFuse-bank and downstream-master positive controls (see
    ``smc_diagnostic_vip_utils``); run it with ``cocotb.start_soon`` alongside
    the stimulus and kill it afterwards.
    """
    while True:
        await RisingEdge(clk)
        value = sig.value
        if value.is_resolvable and int(value):
            hits[0] += 1


async def prove_efuse_bank_axil_activity(
    seq, label: str = "EFUSE_SHIM_CTRL_EFUSE_BANK_INIT_TIME", *, record: bool = True
) -> int:
    """Positive control for ``tb_axil_efuse_bank_active`` (fail-capable at 1).

    Drives one real frontdoor SEP_IN AXI read of the eFuse-shim window through
    ``seq`` (no force, no deposit, no backdoor) and requires the eFuse-bank
    AXI-Lite activity OR to be observed at 1 while the request is outstanding.
    The read itself is value-checked against the RDL reset of the register that
    implements that offset, so the access is fail-capable on its own too.

    ``record=False`` performs the same fail-capable proof but leaves no
    positive-control credit behind for :func:`check_efuse_otp_observability` to
    consume. Callers that borrow this helper only as *stimulus* for a different
    probe (``smc_diagnostic_vip_utils.prove_axil_any_master_activity``) must pass
    it: the credit belongs to the test that owns the eFuse-bank idle claim, and
    a borrowed run leaving one behind would let an unrelated idle assertion
    print as if it were backed.

    Returns the read data. Raises if the probe never reads 1.
    """
    dut = cocotb.top
    probe = dut.tb_axil_efuse_bank_active
    assert probe.value.is_resolvable, (
        "eFuse-bank AXI-Lite activity signal is not resolvable before the positive control"
    )
    assert int(probe.value) == 0, (
        "positive-control precondition failed: tb_axil_efuse_bank_active is "
        "already 1 before any eFuse-bank stimulus was issued"
    )

    hits = [0]
    sampler = cocotb.start_soon(count_probe_high_cycles(probe, dut.clk_smc_i, hits))
    try:
        rdata = await seq.csr_read(
            label, EFUSE_SHIM_CTRL_WINDOW, expected=EFUSE_BANK_INIT_TIME_RESET
        )
        await ClockCycles(dut.clk_smc_i, 4)
    finally:
        stop_sampler(sampler)

    assert hits[0] > 0, (
        "tb_axil_efuse_bank_active never sampled 1 while a real SEP_IN AXI read "
        f"of the eFuse-shim window @ 0x{EFUSE_SHIM_CTRL_WINDOW:08x} was in "
        "flight: the activity probe is stuck at 0 / undriven / mis-tied, so any "
        "idle == 0 assertion on it is vacuous"
    )
    if record:
        _POSITIVE_CONTROL.append(
            f"{hits[0]} clk_smc_i cycle(s) high @ 0x{EFUSE_SHIM_CTRL_WINDOW:08x}"
        )
    cocotb.log.info(
        "CHK-EFUSE-BANK-AXIL-ACTIVE: tb_axil_efuse_bank_active observed 1 for "
        "%d clk_smc_i cycle(s) during %s @ 0x%08x (rdata=0x%08x == RDL reset "
        "0x%02x); the probe is alive and fail-capable",
        hits[0],
        label,
        EFUSE_SHIM_CTRL_WINDOW,
        rdata,
        EFUSE_BANK_INIT_TIME_RESET,
    )
    return rdata


async def check_efuse_otp_observability() -> None:
    """Idle leg: eFuse-bank AXI-Lite is quiet after the bounded OTP checks.

    Only counts as evidence when :func:`prove_efuse_bank_axil_activity` ran
    earlier in the same test (see module docstring).
    """
    dut = cocotb.top

    await ClockCycles(dut.clk_smc_i, 8)
    assert dut.tb_axil_efuse_bank_active.value.is_resolvable, (
        "eFuse-bank AXI-Lite activity signal is not resolvable"
    )
    assert int(dut.tb_axil_efuse_bank_active.value) == 0, (
        "eFuse-bank AXI-Lite should be idle after bounded OTP checks"
    )
    credit = consume_positive_control()
    if credit is not None:
        cocotb.log.info(
            "CHK-EFUSE-BANK-IDLE: tb_axil_efuse_bank_active == 0 after the "
            "bounded OTP/chip-config checks, backed by this test's positive "
            "control (%s)",
            credit,
        )
    else:
        cocotb.log.warning(
            "tb_axil_efuse_bank_active sampled 0 after the bounded OTP checks, "
            "but this test ran no positive control "
            "(prove_efuse_bank_axil_activity), so the observation cannot "
            "distinguish a genuinely idle eFuse bank from a dead probe and is "
            "NOT closure evidence"
        )
