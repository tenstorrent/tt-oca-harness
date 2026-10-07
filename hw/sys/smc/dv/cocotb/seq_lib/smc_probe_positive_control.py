# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Positive controls for the ``tb_top`` observability probes.

Every idle-zero compare in ``SmcScoreboard`` (``tb_sync_irq == 0``,
``tb_uart_irq_any == 0``, ``tb_i2c_cg_en == 0``, ``tb_axil_*_active == 0``) is a
negative check: a stuck-at-0 net, an undriven port, or a ``tb_top.sv`` assign
orphaned by an RTL rename passes it exactly as a live, quiet DUT does.  Policy
``[NEGATIVE-NEEDS-POSITIVE-CONTROL]`` requires the same probe to be proven able
to read 1 in a run before that ``== 0`` counts as evidence.

This module holds the stimulus that does it.  Every helper here:

1. drives **real DUT stimulus** through the approved frontdoor (SEP_IN AXI CSR
   accesses, or the top-level ``tb_gpio_ext_drive_*`` pins) -- no force, no
   deposit, no hierarchical write on the proof path;
2. samples the probe **every ``clk_smc_i`` cycle** inside a bounded window;
3. **FAILS** (``AssertionError`` with the last observed state) if the probe never
   reads 1 -- expiry is a testcase failure, never a silent pass
   (``[TIMEOUT-MUST-FAIL]``);
4. restores the idle stimulus and **confirms the probe returns to 0** inside a
   second bounded window;
5. emits its ``CHK-`` evidence token only after **both** legs passed
   (``[EVIDENCE-TOKEN-CONDITIONAL]``), through ``cocotb.log`` -- the logger the
   harness captures, so the token is verifiably present in the kept log.

The observed 1 is recorded in the run-scoped ledger in
``env/smc_probe_liveness.py``, which the scoreboard consults: an idle leg whose
probe was credited is exact-compared, and one whose probe was not is logged as
``OBSERVED-ONLY ... NOT checked evidence``.  Crediting happens through the
ledger (a DUT observation) rather than by a flag these helpers set, so a helper
cannot declare a probe alive that the DUT never drove.

Two shapes of control live here.  Most prove a *level*: the probe idles at 0, the
control raises it to 1 and returns it to 0.  :func:`prove_gpio_pad_bus_probe`
proves a *change* instead, because its observables (the ``tb_core2pad_o`` /
``tb_core2pad_en_o`` pad-output vectors) are non-zero at idle -- it drives a real
GPIO0 TX programming change, requires exactly one pad to move, and requires the
bus to restore bit-for-bit.  The three ``tb_gpio_*_any`` OR-aggregates get **no**
control: they read 1 from reset onward and nothing can drive them to 0,
so they are declared unbackable (see below) rather than given a control that would
certify nothing.

``tb_axil_dtp_csr_active`` has **no** control here.
``tb_top.sv`` ties ``axil_dtp_csr_resp = '0`` -- there is no responder, so
an AXI-Lite access into the DTP CSR window would wedge instead of completing --
and the DTP CSR boundary is outside this bench's scope
(``hw/sys/smc/dv/README.md``). It is listed in
``env.smc_probe_liveness.UNBACKABLE_PROBES`` and its idle value is
OBSERVED-ONLY, never closure evidence.

:func:`prove_axil_efuse_bank_probe` reuses the window and RDL-sourced expected
value that ``smc_efuse_vip_utils.prove_efuse_bank_axil_activity`` owns for the
eFuse tests; ``tb_axil_any_master_active`` has no control of its own, the
passive ledger credits it from the existing stimulus.
"""

from __future__ import annotations

from pathlib import Path

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from env.smc_gpio_item import (
    GPIO_STABLE_VECTOR_FIELDS,
    SmcGpioItem,
    SmcGpioOp,
)
from env.smc_probe_liveness import (
    PROBE_SIGNALS,
    UNBACKABLE_PROBES,
    credit_probe,
    probe_alive,
    probe_evidence,
)

from .smc_addr_map import (
    CLOCK_GATE_CONTROL,
    I2C_CG_EN,
    UART_CG_EN,
    _field_mask,
    gpio_intf_u32,
    reset_unit_u32,
    smc_addr,
    smc_bootrom_addr,
    smc_indexed_addr,
)
from .smc_base_test_seq import smc_base_test_seq
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_efuse_vip_utils import (
    EFUSE_BANK_INIT_TIME_RESET,
    EFUSE_SHIM_CTRL_WINDOW,
)

_REPO = Path(__file__).resolve().parents[6]
_UART_H = _REPO / "hw" / "ip" / "uart" / "uart_16550" / "regs" / "gen" / "c" / "uart_16550_main.h"
_UART_CTRL_H = (
    _REPO
    / "hw"
    / "ip"
    / "uart"
    / "uart_log_engine_wrap"
    / "regs"
    / "gen"
    / "c"
    / "uart_log_engine_ctrl.h"
)

# ------------------------------------------------------------------ addresses --
# Every address and field position below is imported by symbol from a generated
# header (``[ADDRESS-FROM-AUTHORITATIVE-MAP]``); no numeric literal addresses.
SYNC_REG = smc_addr("SMC_TOP_SMC_RESET_UNIT_SYNC_REG_BASE_ADDR")
SYNC_REG_SYNC_BM = reset_unit_u32("RESET_UNIT__SYNC_REG__SYNC_bm")
SYNC_REG_SYNC_RESET = reset_unit_u32("RESET_UNIT__SYNC_REG__SYNC_reset")

UART0_CTRL = smc_indexed_addr(
    "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_CTRL_BASE_ADDR",
    0,
)
UART0_IER = smc_indexed_addr("SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR", 0)
UART0_ITR = smc_indexed_addr("SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR", 0)
UART_EN = _field_mask(_UART_CTRL_H, "UART_LOG_ENGINE_CTRL__CTRL__UART_EN_bm")
# ETBEI/TTBEI = the transmitter-holding-register-empty interrupt enable and its
# ITR (interrupt test register) counterpart. ITR is a real 16550 register in the
# RTL, so raising the source through it is frontdoor CSR stimulus, not a TB
# backdoor. With the TX FIFO empty after reset the THRE source is already
# active, so the IER unmask is what raises the aggregate; the ITR write raises
# the source deterministically regardless of the reset FIFO state.
IER_ETBEI = _field_mask(_UART_H, "UART_16550_MAIN__IER__ETBEI_bm")
ITR_TTBEI = _field_mask(_UART_H, "UART_16550_MAIN__ITR__TTBEI_bm")

# The adopter external window, which HAS a real responder: `smc_external_req_o`
# is absorbed by `smc_ip_integration` inside `smc_wrapper`
# (hw/top/smc_ip_integration.sv), whose external-window demux routes window
# offset 0x2000 to `pll_wrap`. `pll_wrap` terminates with
# `prim_axi_lite_err_slv(RESP_OKAY, RESP_DATA='0)`, so the read completes OKAY
# with data 0 -- an exact expectation. What this control proves is upstream of
# that behavioural responder: `u_smc.smc_external_req_o.ar_valid` asserted, i.e.
# `tb_axil_external_active` is alive. `pll_wrap` is a declared behavioural stub
# (``[BEHAVIORAL-STUB-DECLARED]``); no claim is made here about PLL behaviour.
EXTERNAL_PLL_CGM0_STATUS = smc_bootrom_addr(
    "SMC_TOP_SMC_EXTERNAL_MANDATORY_SMC_PLL_WRAP_PLL_CNTL_CGM_0_STATUS_BASE_ADDR"
)
EXTERNAL_PLL_CGM0_STATUS_EXPECTED = 0

GPIO0_DATA_CTRL = smc_indexed_addr("SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR", 0)
# DATA_CTRL field bits by symbol from generated hw/ip/gpio/regs/gen/c/gpio_intf.h.
# Encodings from hw/ip/gpio/regs/gen/adoc/gpio_intf.adoc: enable_rx_tx 2'b10 =
# RX enabled, interrupt_type 2'b01 = active-low level.
_GPIO_RX_ENABLE = 2 << gpio_intf_u32("GPIO_INTF__DATA_CTRL__ENABLE_RX_TX_bp")
_GPIO_IF_ENABLE = gpio_intf_u32("GPIO_INTF__DATA_CTRL__INTERFACE_ENABLE_bm")
_GPIO_IRQ_ENABLE = gpio_intf_u32("GPIO_INTF__DATA_CTRL__INTERRUPT_ENABLE_bm")
_GPIO_TYPE_ACTIVE_LOW = 1 << gpio_intf_u32("GPIO_INTF__DATA_CTRL__INTERRUPT_TYPE_bp")
GPIO0_INPUT_ACTIVE_LOW_IRQ = (
    _GPIO_RX_ENABLE | _GPIO_IF_ENABLE | _GPIO_IRQ_ENABLE | _GPIO_TYPE_ACTIVE_LOW
)

# TX (register-driven output) programming of GPIO wrap 0, by symbol from the same
# generated header. enable_rx_tx 2'b01 = TX enabled; core2pad is the value driven
# onto the pad; interface_enable selects the register values.
_GPIO_TX_ENABLE = 1 << gpio_intf_u32("GPIO_INTF__DATA_CTRL__ENABLE_RX_TX_bp")
_GPIO_CORE2PAD = gpio_intf_u32("GPIO_INTF__DATA_CTRL__CORE2PAD_bm")
GPIO0_OUTPUT_DRIVE_HIGH = _GPIO_IF_ENABLE | _GPIO_TX_ENABLE | _GPIO_CORE2PAD
GPIO0_OUTPUT_DRIVE_LOW = _GPIO_IF_ENABLE | _GPIO_TX_ENABLE

# -------------------------------------------------------------------- bounds --
# Liveness bounds in clk_smc_i cycles. No published SPEC latency exists for any
# of these aggregates, so these are generous upper bounds whose expiry is a
# FAILURE. They are not settle delays: the poll samples every cycle until the
# exact expected level appears ([NO-BLIND-DELAY-SYNC] / [TIMEOUT-MUST-FAIL]).
_LEVEL_BOUND_CYCLES = 128
# A level source must persist while its stimulus is held; re-checking rejects a
# one-cycle glitch that merely brushed the expected value.
_LEVEL_HOLD_CYCLES = 4
# Window kept open around an AXI-Lite request for the pulse-shaped activity
# probes (a *_valid handshake is only high while the request is outstanding).
_PULSE_DRAIN_CYCLES = 8


def _read_probe(dut, signal_name: str) -> int:
    """X-aware read of a tb_top probe.

    These probes are registered/combinational DUT observables that are out of
    reset by the time any control runs, so X/Z is a defect rather than a
    don't-care: fail with a diagnostic instead of letting ``int()`` resolve it
    arbitrarily (``[X-AWARE-CHECK]``).
    """
    raw = getattr(dut, signal_name).value
    assert raw.is_resolvable, f"{signal_name} is not resolvable (X/Z): {raw}"
    return int(raw)


async def _await_probe_level(
    dut,
    probe: str,
    expected: int,
    label: str,
    bound: int = _LEVEL_BOUND_CYCLES,
) -> int:
    """Bounded per-cycle poll until ``probe == expected``, then hold-verify it.

    Returns the number of ``clk_smc_i`` cycles the level took to appear. Raises
    on bound expiry with the last observed value, and on any X/Z seen while
    polling. Crediting the liveness ledger is done by the caller only after the
    full two-legged control passed.
    """
    signal_name = PROBE_SIGNALS[probe]
    clk = dut.clk_smc_i
    last = None
    for cycle in range(1, bound + 1):
        await ClockCycles(clk, 1)
        last = _read_probe(dut, signal_name)
        if last == expected:
            for hold in range(1, _LEVEL_HOLD_CYCLES + 1):
                await ClockCycles(clk, 1)
                held = _read_probe(dut, signal_name)
                assert held == expected, (
                    f"{label}: {signal_name} reached {expected} after {cycle} "
                    f"clk_smc_i cycles but did not hold it -- became {held} "
                    f"{hold} cycle(s) later while the stimulus was still held"
                )
            return cycle
    raise AssertionError(
        f"{label}: {signal_name} never reached {expected} within {bound} "
        f"clk_smc_i cycles (last observed {last}); the probe is stuck / "
        f"undriven / mis-bound, so an idle == 0 assertion on it is vacuous"
    )


async def _count_probe_high(dut, probe: str, hits: list[int]) -> None:
    """Sample a pulse-shaped probe every ``clk_smc_i`` edge, counting 1s."""
    signal_name = PROBE_SIGNALS[probe]
    handle = getattr(dut, signal_name)
    clk = dut.clk_smc_i
    while True:
        await RisingEdge(clk)
        value = handle.value
        if value.is_resolvable and int(value):
            hits[0] += 1


def _stop(task) -> None:
    task.cancel()


def _assert_idle_precondition(dut, probe: str, control: str) -> None:
    signal_name = PROBE_SIGNALS[probe]
    got = _read_probe(dut, signal_name)
    assert got == 0, (
        f"{control} precondition failed: {signal_name} is already {got} before "
        f"any stimulus was issued, so a later 1 would not be attributable to "
        f"this control"
    )


# ============================================================== sync_irq ======
async def prove_sync_irq_probe(seq: SmcCsrSeq) -> None:
    """Positive control for ``tb_sync_irq`` (0 -> 1 -> 0, both legs bounded).

    ``tb_top.sv`` assigns ``tb_sync_irq = sync_irq``, the ``smc_wrapper``
    boundary output ``smc_reset_unit.sv`` drives as
    ``sync_irq_o = hwif_out.SYNC_REG.sync.value``. SYNC_REG.sync is a plain
    ``sw=rw; hw=r`` CSR field (``reset_unit.rdl``, reset 0x0), so
    writing it over the SEP_IN AXI frontdoor is the real producer of the
    aggregate -- no force, no deposit.

    Costs 4 CSR accesses (write+readback set, write+readback clear).
    """
    dut = cocotb.top
    _assert_idle_precondition(dut, "sync_irq", "prove_sync_irq_probe")

    await seq.csr_write("SYNC_REG_SET", SYNC_REG, SYNC_REG_SYNC_BM)
    await seq.csr_read("SYNC_REG_SET_RB", SYNC_REG, expected=SYNC_REG_SYNC_BM)
    assert_cycles = await _await_probe_level(dut, "sync_irq", 1, "sync_irq_assert")

    await seq.csr_write("SYNC_REG_CLR", SYNC_REG, SYNC_REG_SYNC_RESET)
    await seq.csr_read("SYNC_REG_CLR_RB", SYNC_REG, expected=SYNC_REG_SYNC_RESET)
    clear_cycles = await _await_probe_level(dut, "sync_irq", 0, "sync_irq_release")

    credit_probe(
        "sync_irq",
        f"SYNC_REG.sync=1 over SEP_IN AXI @ 0x{SYNC_REG:08x} raised "
        f"tb_sync_irq after {assert_cycles} clk_smc_i cycle(s)",
    )
    cocotb.log.info(
        "CHK-PROBE-SYNC-IRQ-ALIVE: SYNC_REG.sync 0->1 raised tb_sync_irq to 1 "
        "after %d clk_smc_i cycle(s) (held %d), and 1->0 returned it to 0 after "
        "%d cycle(s); the probe reads both levels, so an idle tb_sync_irq==0 "
        "compare is fail-capable",
        assert_cycles,
        _LEVEL_HOLD_CYCLES,
        clear_cycles,
    )


# ========================================================== uart_irq_any ======
async def prove_uart_irq_any_probe(seq: SmcCsrSeq) -> None:
    """Positive control for ``tb_uart_irq_any`` (0 -> 1 -> 0, both bounded).

    ``tb_top.sv`` assigns ``tb_uart_irq_any = |uart_interrupt``. This
    ungates the UART clock, enables UART0, unmasks the THRE source in IER and
    raises it through the 16550 ITR (interrupt test register) -- the same
    IER/ITR programming ``smc_uart_irq_sources_priority_test_seq`` uses for its
    source-mapping legs, all real CSRs over the SEP_IN AXI frontdoor. Both
    registers and the clock-gate value are restored before returning.

    Costs 8 CSR accesses (CG save, CG ungate, UART_EN, IER set, ITR set, ITR
    clear, IER clear, CG restore).
    """
    dut = cocotb.top
    _assert_idle_precondition(dut, "uart_irq_any", "prove_uart_irq_any_probe")

    cg = await seq.csr_read("UART_CG_SAVE", CLOCK_GATE_CONTROL)
    await seq.csr_write("UART_UNGATE", CLOCK_GATE_CONTROL, cg & ~UART_CG_EN)
    await seq.csr_write("UART0_EN", UART0_CTRL, UART_EN)
    await seq.csr_write("UART0_IER_ETBEI", UART0_IER, IER_ETBEI)
    await seq.csr_write("UART0_ITR_TTBEI", UART0_ITR, ITR_TTBEI)
    assert_cycles = await _await_probe_level(dut, "uart_irq_any", 1, "uart_irq_assert")

    await seq.csr_write("UART0_ITR_CLR", UART0_ITR, 0)
    await seq.csr_write("UART0_IER_CLR", UART0_IER, 0)
    clear_cycles = await _await_probe_level(dut, "uart_irq_any", 0, "uart_irq_release")
    await seq.csr_write("UART_CG_RESTORE", CLOCK_GATE_CONTROL, cg)

    credit_probe(
        "uart_irq_any",
        f"UART0 IER.ETBEI + ITR.TTBEI over SEP_IN AXI raised tb_uart_irq_any "
        f"after {assert_cycles} clk_smc_i cycle(s)",
    )
    cocotb.log.info(
        "CHK-PROBE-UART-IRQ-ALIVE: UART0 IER.ETBEI+ITR.TTBEI raised "
        "tb_uart_irq_any to 1 after %d clk_smc_i cycle(s) (held %d), and "
        "clearing ITR/IER returned it to 0 after %d cycle(s); the probe reads "
        "both levels, so an idle tb_uart_irq_any==0 compare is fail-capable",
        assert_cycles,
        _LEVEL_HOLD_CYCLES,
        clear_cycles,
    )


# ============================================================== i2c_cg_en =====
async def prove_i2c_cg_en_probe(seq: SmcCsrSeq) -> None:
    """Positive control for ``tb_i2c_cg_en`` (0 -> 1 -> 0, both bounded).

    ``tb_top.sv`` assigns ``tb_i2c_cg_en = u_dut.u_smc.cg_ctrl_i2c_cg_en``,
    which the base-config register block drives from
    ``CLOCK_GATE_CONTROL.i2c_cg_en``. Programming that field over the SEP_IN AXI
    frontdoor is the real producer. The whole CLOCK_GATE_CONTROL word is saved
    and restored, so no other gate is disturbed.

    Costs 4 CSR accesses.
    """
    dut = cocotb.top
    _assert_idle_precondition(dut, "i2c_cg_en", "prove_i2c_cg_en_probe")

    cg = await seq.csr_read("I2C_CG_SAVE", CLOCK_GATE_CONTROL)
    await seq.csr_write("I2C_CG_SET", CLOCK_GATE_CONTROL, cg | I2C_CG_EN)
    assert_cycles = await _await_probe_level(dut, "i2c_cg_en", 1, "i2c_cg_set")

    await seq.csr_write("I2C_CG_RESTORE", CLOCK_GATE_CONTROL, cg & ~I2C_CG_EN)
    clear_cycles = await _await_probe_level(dut, "i2c_cg_en", 0, "i2c_cg_clear")
    await seq.csr_read("I2C_CG_RESTORE_RB", CLOCK_GATE_CONTROL, expected=cg & ~I2C_CG_EN)

    credit_probe(
        "i2c_cg_en",
        f"CLOCK_GATE_CONTROL.i2c_cg_en=1 over SEP_IN AXI @ "
        f"0x{CLOCK_GATE_CONTROL:08x} raised tb_i2c_cg_en after "
        f"{assert_cycles} clk_smc_i cycle(s)",
    )
    cocotb.log.info(
        "CHK-PROBE-I2C-CG-EN-ALIVE: CLOCK_GATE_CONTROL.i2c_cg_en 0->1 raised "
        "tb_i2c_cg_en to 1 after %d clk_smc_i cycle(s) (held %d), and 1->0 "
        "returned it to 0 after %d cycle(s); the probe reads both levels, so an "
        "idle tb_i2c_cg_en==0 compare is fail-capable",
        assert_cycles,
        _LEVEL_HOLD_CYCLES,
        clear_cycles,
    )


# ==================================================== axil_external_active ====
async def prove_axil_external_active_probe(seq: SmcCsrSeq) -> None:
    """Positive control for ``tb_axil_external_active`` (pulse at 1, then idle).

    ``tb_top.sv`` ORs ``u_smc.smc_external_req_o.{aw,w,ar}_valid``.
    The port is absorbed by ``smc_ip_integration`` inside ``smc_wrapper``, whose
    external-window demux gives the adopter PLL/PVT/GPIO-ctrl window a real
    responder, so a frontdoor CSR read into that window makes the master valid
    and completes. ``smc_periph_axi_lite_xbar.sv`` routes
    ``SMC_TOP_SMC_EXTERNAL_BASE_ADDR + EFUSE_SHIM_SIZE .. SMC_TOP_SMC_EXTERNAL_BASE_ADDR +
    SMC_TOP_SMC_EXTERNAL_SIZE`` to the external port, and
    ``smc_ip_integration.sv`` maps window offset 0x2000 to ``pll_wrap``, which
    answers OKAY with data 0.

    The probe is pulse-shaped (high only while a request is outstanding), so it
    is sampled every ``clk_smc_i`` edge across the access rather than polled
    afterwards; the idle leg then re-polls it back to 0.

    Costs 1 CSR access.
    """
    dut = cocotb.top
    _assert_idle_precondition(dut, "axil_external_active", "prove_axil_external_active_probe")

    hits = [0]
    sampler = cocotb.start_soon(_count_probe_high(dut, "axil_external_active", hits))
    try:
        rdata = await seq.csr_read(
            "EXTERNAL_PLL_CGM0_STATUS",
            EXTERNAL_PLL_CGM0_STATUS,
            expected=EXTERNAL_PLL_CGM0_STATUS_EXPECTED,
        )
        await ClockCycles(dut.clk_smc_i, _PULSE_DRAIN_CYCLES)
    finally:
        _stop(sampler)

    assert hits[0] > 0, (
        "tb_axil_external_active never sampled 1 while a real SEP_IN AXI read "
        f"of the adopter external window @ 0x{EXTERNAL_PLL_CGM0_STATUS:08x} was "
        "in flight: the activity probe is stuck at 0 / undriven / mis-tied, so "
        "any idle == 0 assertion on it is vacuous"
    )
    idle_cycles = await _await_probe_level(dut, "axil_external_active", 0, "axil_external_idle")

    credit_probe(
        "axil_external_active",
        f"{hits[0]} clk_smc_i cycle(s) high during a SEP_IN AXI read @ "
        f"0x{EXTERNAL_PLL_CGM0_STATUS:08x}",
    )
    cocotb.log.info(
        "CHK-PROBE-AXIL-EXTERNAL-ALIVE: tb_axil_external_active observed 1 for "
        "%d clk_smc_i cycle(s) during a frontdoor read of the adopter external "
        "window @ 0x%08x (rdata=0x%08x == expected 0x%x), then back to 0 after "
        "%d cycle(s); the probe reads both levels, so an idle "
        "tb_axil_external_active==0 compare is fail-capable",
        hits[0],
        EXTERNAL_PLL_CGM0_STATUS,
        rdata,
        EXTERNAL_PLL_CGM0_STATUS_EXPECTED,
        idle_cycles,
    )


# ================================================= axil_efuse_bank_active ====
async def prove_axil_efuse_bank_probe(seq: SmcCsrSeq) -> None:
    """Positive control for ``tb_axil_efuse_bank_active`` (pulse at 1, idle 0).

    ``tb_top.sv`` ORs ``u_smc.efuse_bank_ctrl_req_o.{aw,w,ar}_valid``. The
    stimulus target and its RDL-sourced expected value are imported from
    ``smc_efuse_vip_utils`` (the module that already owns this probe's proof for
    the eFuse tests), so there is one definition of the window and its reset
    value; only the sampling and the ledger credit live here, which is what lets
    a test that is not an eFuse test back its own idle leg.

    Costs 1 CSR access.
    """
    dut = cocotb.top
    _assert_idle_precondition(dut, "axil_efuse_bank_active", "prove_axil_efuse_bank_probe")

    hits = [0]
    sampler = cocotb.start_soon(_count_probe_high(dut, "axil_efuse_bank_active", hits))
    try:
        rdata = await seq.csr_read(
            "EFUSE_SHIM_CTRL_EFUSE_BANK_INIT_TIME",
            EFUSE_SHIM_CTRL_WINDOW,
            expected=EFUSE_BANK_INIT_TIME_RESET,
        )
        await ClockCycles(dut.clk_smc_i, _PULSE_DRAIN_CYCLES)
    finally:
        _stop(sampler)

    assert hits[0] > 0, (
        "tb_axil_efuse_bank_active never sampled 1 while a real SEP_IN AXI read "
        f"of the eFuse-shim window @ 0x{EFUSE_SHIM_CTRL_WINDOW:08x} was in "
        "flight: the activity probe is stuck at 0 / undriven / mis-tied, so any "
        "idle == 0 assertion on it is vacuous"
    )
    idle_cycles = await _await_probe_level(dut, "axil_efuse_bank_active", 0, "axil_efuse_bank_idle")

    credit_probe(
        "axil_efuse_bank_active",
        f"{hits[0]} clk_smc_i cycle(s) high during a SEP_IN AXI read @ "
        f"0x{EFUSE_SHIM_CTRL_WINDOW:08x}",
    )
    cocotb.log.info(
        "CHK-PROBE-AXIL-EFUSE-BANK-ALIVE: tb_axil_efuse_bank_active observed 1 "
        "for %d clk_smc_i cycle(s) during a frontdoor read of the eFuse-shim "
        "window @ 0x%08x (rdata=0x%08x == RDL reset 0x%02x), then back to 0 "
        "after %d cycle(s); the probe reads both levels, so an idle "
        "tb_axil_efuse_bank_active==0 compare is fail-capable",
        hits[0],
        EFUSE_SHIM_CTRL_WINDOW,
        rdata,
        EFUSE_BANK_INIT_TIME_RESET,
        idle_cycles,
    )


# ========================================================= gpio_irq_any ======
async def prove_gpio_irq_any_probe(seq: SmcCsrSeq) -> None:
    """Positive control for ``tb_gpio_irq_any`` (0 -> 1 -> 0, both bounded).

    ``tb_top.sv`` assigns ``tb_gpio_irq_any = |gpio_interrupt``. GPIO0 is
    programmed RX + interrupt_enable + active-low level over the SEP_IN AXI
    frontdoor, then the pad is driven from the top-level ``tb_gpio_ext_drive_*``
    pins (external pin drive, not an internal force). GPIO0's DATA_CTRL is saved
    and restored, and the external drive is released before returning.

    Costs 3 CSR accesses.
    """
    dut = cocotb.top
    saved = await seq.csr_read("GPIO0_DATA_CTRL_SAVE", GPIO0_DATA_CTRL)
    await seq.csr_write("GPIO0_INPUT_ACTIVE_LOW_IRQ", GPIO0_DATA_CTRL, GPIO0_INPUT_ACTIVE_LOW_IRQ)
    dut.tb_gpio_ext_drive_en.value = 0x1
    dut.tb_gpio_ext_drive_value.value = 0x1
    idle_cycles = await _await_probe_level(dut, "gpio_irq_any", 0, "gpio0_pad_high_idle")

    dut.tb_gpio_ext_drive_value.value = 0x0
    assert_cycles = await _await_probe_level(dut, "gpio_irq_any", 1, "gpio0_pad_low_assert")

    dut.tb_gpio_ext_drive_value.value = 0x1
    clear_cycles = await _await_probe_level(dut, "gpio_irq_any", 0, "gpio0_pad_high_clear")
    dut.tb_gpio_ext_drive_en.value = 0x0
    await seq.csr_write("GPIO0_DATA_CTRL_RESTORE", GPIO0_DATA_CTRL, saved)

    credit_probe(
        "gpio_irq_any",
        f"GPIO0 active-low pad drive raised tb_gpio_irq_any after "
        f"{assert_cycles} clk_smc_i cycle(s)",
    )
    cocotb.log.info(
        "CHK-PROBE-GPIO-IRQ-ALIVE: GPIO0 pad 1->0 raised tb_gpio_irq_any to 1 "
        "after %d clk_smc_i cycle(s) (held %d) and 0->1 cleared it after %d "
        "cycle(s) (pad-high idle confirmed after %d); the probe reads both "
        "levels, so an idle tb_gpio_irq_any==0 compare is fail-capable",
        assert_cycles,
        _LEVEL_HOLD_CYCLES,
        clear_cycles,
        idle_cycles,
    )


# ======================================================== gpio pad-bus =======
# Bound on the pad-output bus responding to a GPIO0 DATA_CTRL write, in
# clk_smc_i cycles. No published SPEC latency exists, so this is a generous
# upper bound whose expiry is a FAILURE: the poll samples the real vectors every
# cycle until the exact expected bit state appears
# ([NO-BLIND-DELAY-SYNC] / [TIMEOUT-MUST-FAIL]).
_PAD_BUS_BOUND_CYCLES = 128


def _pad_vec(dut, name: str) -> int:
    """Read a wide pad-bus vector, resolving X/Z bits to 0 (positions kept).

    Same reader as ``smc_gpio_agent`` and ``smc_gpio_output_driveback_test_seq``:
    VCS leaves undriven upper pad bits at X while Verilator zero-inits them, and
    every use here isolates GPIO wrap 0 by a single-bit delta, so an undriven X
    bit reading 0 is harmless. A *driven* bit that is X also reads 0, which makes
    the delta assertions below fail rather than pass.
    """
    value = getattr(dut, name).value
    try:
        return int(value)
    except Exception:  # noqa: BLE001 - X/Z present (VCS undriven pads)
        text = getattr(value, "binstr", None) or str(value)
        bits = "".join(c if c in "01" else "0" for c in text if c not in " _")
        return int(bits, 2) if bits else 0


async def _await_pad_bus(dut, predicate, label: str) -> tuple[int, int, int]:
    """Bounded per-cycle poll of (core2pad_en_o, core2pad_o) until ``predicate``.

    Returns ``(cycles, en_vec, val_vec)``. Raises on expiry, naming the last
    observed vectors.
    """
    en = val = 0
    for cycle in range(1, _PAD_BUS_BOUND_CYCLES + 1):
        await ClockCycles(dut.clk_smc_i, 1)
        en = _pad_vec(dut, "tb_core2pad_en_o")
        val = _pad_vec(dut, "tb_core2pad_o")
        if predicate(en, val):
            return cycle, en, val
    raise AssertionError(
        f"{label}: the pad-output bus never reached the expected state within "
        f"{_PAD_BUS_BOUND_CYCLES} clk_smc_i cycles (last "
        f"tb_core2pad_en_o=0x{en:x} tb_core2pad_o=0x{val:x}); the pad bus is "
        f"stuck / undriven / mis-bound, so a cross-sample 'it did not move' "
        f"compare on it is vacuous"
    )


async def prove_gpio_pad_bus_probe(seq: SmcCsrSeq) -> None:
    """Positive control for the GPIO pad-output bus vectors.

    The three ``tb_gpio_*_any`` aggregates admit no control: they are
    OR-reductions over the *whole* pad bus (``tb_top.sv``), which carries
    idle-high LSIO pads (UART TX) and default-enabled pad inputs, so they read 1
    from reset onward and no frontdoor stimulus can drive any of them to 0; a
    net tied to constant 1 is indistinguishable from the real aggregate. They
    are declared in ``env.smc_probe_liveness.UNBACKABLE_PROBES``.

    The raw vectors ``tb_core2pad_o`` / ``tb_core2pad_en_o`` (``tb_top.sv``
    mirrors of the same ``u_dut.u_smc.core2pad*_o`` nets the aggregates reduce)
    *do* move, so they can carry the proof. This control programs GPIO wrap 0 as a
    register-driven TX output over the SEP_IN AXI frontdoor -- the mechanism
    ``smc_gpio_output_driveback_test_seq`` uses -- and requires, each leg bounded
    and each expiry a failure:

    1. exactly **one** new output-enable bit appears in ``tb_core2pad_en_o``
       (self-locating: only wrap 0 is programmed, so a multi-bit delta is a
       failure), and that pad's ``tb_core2pad_o`` value is 1;
    2. driving the register value low clears that pad's value while its enable
       bit is still asserted;
    3. restoring DATA_CTRL releases the enable bit **and returns both vectors
       bit-for-bit to their pre-control values** -- which is what lets a caller
       compare samples taken before and after this control.

    Only then are ``gpio_core2pad_vec`` / ``gpio_core2pad_en_vec`` credited in the
    liveness ledger, so a scoreboard compare on those vectors is backed by a
    same-run observation of the DUT moving them.

    Costs 3 CSR accesses (TX high, TX low, restore) plus 1 read (save) = 4.
    """
    dut = cocotb.top
    for name in ("tb_core2pad_o", "tb_core2pad_en_o"):
        assert hasattr(dut, name), (
            f"prove_gpio_pad_bus_probe needs the tb_top pad-bus mirror {name}; "
            f"without it the GPIO pad-bus observables have no positive control "
            f"and no compare on them may be presented as checked evidence"
        )
    width = len(dut.tb_core2pad_en_o.value)
    mask = (1 << width) - 1

    base_en = _pad_vec(dut, "tb_core2pad_en_o")
    base_val = _pad_vec(dut, "tb_core2pad_o")

    saved = await seq.csr_read("GPIO0_DATA_CTRL_PADBUS_SAVE", GPIO0_DATA_CTRL)

    # 1) TX enabled, register value high -> exactly one new output-enable bit.
    await seq.csr_write("GPIO0_PADBUS_TX_HIGH", GPIO0_DATA_CTRL, GPIO0_OUTPUT_DRIVE_HIGH)
    assert_cycles, en_hi, val_hi = await _await_pad_bus(
        dut,
        lambda en, val: (en & (~base_en & mask)) != 0,
        "gpio0_padbus_tx_high",
    )
    newly_en = en_hi & (~base_en & mask)
    assert (newly_en & (newly_en - 1)) == 0, (
        f"programming GPIO wrap 0 as TX asserted more than one new pad "
        f"output-enable (delta=0x{newly_en:x}, base=0x{base_en:x}): the control "
        f"cannot attribute the pad-bus change to wrap 0"
    )
    pad_bit = newly_en
    pad_idx = newly_en.bit_length() - 1
    assert (val_hi & pad_bit) != 0, (
        f"GPIO wrap 0 pad[{pad_idx}] output-enable asserted but its "
        f"tb_core2pad_o value did not follow the register (expected 1, "
        f"tb_core2pad_o=0x{val_hi:x})"
    )

    # 2) TX still enabled, register value low -> value clears, enable holds.
    await seq.csr_write("GPIO0_PADBUS_TX_LOW", GPIO0_DATA_CTRL, GPIO0_OUTPUT_DRIVE_LOW)
    low_cycles, en_lo, val_lo = await _await_pad_bus(
        dut,
        lambda en, val: (val & pad_bit) == 0 and (en & pad_bit) != 0,
        f"gpio0_padbus_tx_low_pad{pad_idx}",
    )

    # 3) Restore -> enable releases and BOTH vectors return to the baseline.
    await seq.csr_write("GPIO0_DATA_CTRL_PADBUS_RESTORE", GPIO0_DATA_CTRL, saved)
    restore_cycles, en_end, val_end = await _await_pad_bus(
        dut,
        lambda en, val: en == base_en and val == base_val,
        f"gpio0_padbus_restore_pad{pad_idx}",
    )

    credit_probe(
        "gpio_core2pad_en_vec",
        f"GPIO0 DATA_CTRL TX programming over SEP_IN AXI @ "
        f"0x{GPIO0_DATA_CTRL:08x} asserted pad[{pad_idx}] in tb_core2pad_en_o "
        f"after {assert_cycles} clk_smc_i cycle(s) "
        f"(0x{base_en:x} -> 0x{en_hi:x}) and released it after "
        f"{restore_cycles} cycle(s)",
    )
    credit_probe(
        "gpio_core2pad_vec",
        f"GPIO0 register-driven output value 1 -> 0 moved pad[{pad_idx}] in "
        f"tb_core2pad_o (0x{val_hi:x} -> 0x{val_lo:x}) after {low_cycles} "
        f"clk_smc_i cycle(s)",
    )
    cocotb.log.info(
        "CHK-PROBE-GPIO-PAD-BUS-ALIVE: GPIO wrap 0 TX programming moved the pad "
        "output bus on pad[%d]: tb_core2pad_en_o 0x%x -> 0x%x (one new bit, "
        "after %d clk_smc_i cycles), tb_core2pad_o value 1 -> 0 after %d cycles "
        "with the enable held, and DATA_CTRL restore returned both vectors to "
        "the baseline (en=0x%x val=0x%x) after %d cycles. The pad-output bus is "
        "proven able to change under frontdoor CSR stimulus, so a cross-sample "
        "compare on tb_core2pad_o / tb_core2pad_en_o is fail-capable rather than "
        "a self-referential expectation. NOTE: the three tb_gpio_*_any "
        "OR-aggregates are NOT credited by this or any control -- they read 1 "
        "from reset onward and no stimulus can drive them to 0 (see "
        "env.smc_probe_liveness.UNBACKABLE_PROBES).",
        pad_idx,
        base_en,
        en_hi,
        assert_cycles,
        low_cycles,
        en_end,
        val_end,
        restore_cycles,
    )


async def ensure_gpio_pad_bus_control(seq) -> None:
    """Run :func:`prove_gpio_pad_bus_probe` unless this run already credited it.

    Lets a GPIO *observability* sequence back its own pad-bus compares without
    its testcase having to declare ``probe_positive_controls`` -- the sequence
    runs on the gpio sequencer, so the control is started as a sub-sequence on
    the SEP_IN AXI sequencer where the CSR accesses belong.
    """
    if probe_alive("gpio_core2pad_vec") and probe_alive("gpio_core2pad_en_vec"):
        return
    control = SmcProbePositiveControlSeq(
        f"{seq.get_name()}_gpio_pad_bus_control", ("gpio_pad_bus",)
    )
    control.cfg = seq.cfg
    control.env = seq.env
    await control.start(seq.env.sys_axi_agent.sequencer)


# ------------------------------------------------------------------ registry --
# Control name -> (control coroutine, CSR accesses it issues, probes it credits).
# The access count is what a caller adds to its own protocol-VIP
# `min_csr_accesses` floor when it enables a control. The credit tuple is checked
# after the control returns, so a control that passes its own legs but forgets to
# credit the ledger is a failure rather than a silent no-op.
PROBE_CONTROLS: dict[str, tuple] = {
    "sync_irq": (prove_sync_irq_probe, 4, ("sync_irq",)),
    "uart_irq_any": (prove_uart_irq_any_probe, 8, ("uart_irq_any",)),
    "i2c_cg_en": (prove_i2c_cg_en_probe, 4, ("i2c_cg_en",)),
    "axil_external_active": (prove_axil_external_active_probe, 1, ("axil_external_active",)),
    "axil_efuse_bank_active": (prove_axil_efuse_bank_probe, 1, ("axil_efuse_bank_active",)),
    "gpio_irq_any": (prove_gpio_irq_any_probe, 3, ("gpio_irq_any",)),
    # One control, two credited observables: the same GPIO0 TX programming moves
    # the output-enable vector and the value vector.
    "gpio_pad_bus": (
        prove_gpio_pad_bus_probe,
        4,
        ("gpio_core2pad_vec", "gpio_core2pad_en_vec"),
    ),
}

assert all(
    probe in PROBE_SIGNALS for _coro, _cost, credits in PROBE_CONTROLS.values() for probe in credits
), "every PROBE_CONTROLS credit must name a probe declared in PROBE_SIGNALS"


def control_csr_accesses(names) -> int:
    """CSR accesses the named controls issue in total (for floor arithmetic)."""
    return sum(PROBE_CONTROLS[n][1] for n in names)


class SmcProbePositiveControlSeq(SmcCsrSeq):
    """Run the named probe positive controls on the SEP_IN AXI sequencer.

    ``smc_base_test`` starts this before ``run_scenario`` for every test that
    declares ``probe_positive_controls``, so the scoreboard's idle legs in that
    test are backed by a same-run observation of the same probe at 1.
    """

    def __init__(self, name: str, controls) -> None:
        super().__init__(name)
        self.controls = tuple(controls)
        unknown = [c for c in self.controls if c not in PROBE_CONTROLS]
        assert not unknown, (
            f"unknown probe positive control(s) {unknown}; known: "
            f"{sorted(PROBE_CONTROLS)}. {sorted(UNBACKABLE_PROBES)} cannot have "
            f"one in this TB."
        )

    async def body(self) -> None:
        for name in self.controls:
            control, _cost, credits = PROBE_CONTROLS[name]
            await control(self)
            for probe in credits:
                assert probe_alive(probe), (
                    f"{name} positive control returned without crediting "
                    f"{probe} in the liveness ledger ({probe_evidence(probe)})"
                )
        expected = control_csr_accesses(self.controls)
        assert self.accesses == expected, (
            f"probe positive controls issued {self.accesses} CSR accesses, "
            f"expected {expected} (PROBE_CONTROLS cost table is stale)"
        )
        cocotb.log.info(
            "CHK-PROBE-CONTROLS: %d probe positive control(s) passed both legs "
            "(%s) in %d SEP_IN AXI CSR accesses",
            len(self.controls),
            ", ".join(self.controls),
            self.accesses,
        )


class SmcGpioAggregateStabilitySeq(smc_base_test_seq):
    """Cross-sample GPIO pad-bus compare with a *backed* FAIL-ON path.

    The three ``tb_gpio_*_any`` aggregates are OR-reductions over the whole pad
    bus (``tb_top.sv``), read 1 from reset onward, and no frontdoor stimulus can
    drive any of them to 0, so a compare of a later sample against an earlier
    sample of the same probe cannot separate a stuck-at-1, undriven or mis-bound
    net from a live quiet DUT (``[NEGATIVE-NEEDS-POSITIVE-CONTROL]``). They are
    declared in ``env.smc_probe_liveness.UNBACKABLE_PROBES``: the scoreboard
    logs them as OBSERVED-ONLY diagnostics and *refuses* a stated expectation
    on them.

    The backable property is on the raw pad-output vectors
    ``tb_core2pad_o`` / ``tb_core2pad_en_o`` (the same ``u_dut.u_smc.core2pad*_o``
    nets the aggregates reduce, mirrored per-pad in ``tb_top.sv``). Those *do*
    move under real frontdoor GPIO CSR programming, so:

    1. :func:`prove_gpio_pad_bus_probe` runs first (via
       :func:`ensure_gpio_pad_bus_control`) and proves this run's DUT moves both
       vectors -- one new output-enable bit for GPIO wrap 0, its value tracking
       the register high then low, then a bit-for-bit restore. Expiry fails.
    2. This sequence then dispatches ``samples`` SAMPLEs carrying the reference
       sample's ``core2pad_en_vec`` as ``expect_core2pad_en_vec``, and the
       scoreboard books that exact compare as **checked** evidence precisely
       because the control credited the probe in the same run.

    Only the output-*enable* vector carries the persistence claim: the pad *value*
    vector also carries free-running DUT outputs (the AVSBus clock is
    ``core2pad_o[49]`` in ``tb_top.sv``), so it moves with no GPIO stimulus and an
    exact cross-sample expectation on it would be flaky rather than proof -- see
    ``GPIO_STABLE_VECTOR_FIELDS``. Its value is reported as a diagnostic.

    The expectation is an *earlier* observation rather than the sample being
    checked, on an observable proven able to change.
    """

    def __init__(self, name: str, reference, samples: int = 2, gap_ref_cycles: int = 80) -> None:
        super().__init__(name)
        self.reference = reference
        self.samples = samples
        self.gap_ref_cycles = gap_ref_cycles
        self.checked: list[SmcGpioItem] = []

    async def body(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard
        ref = self.reference
        assert ref is not None and ref.resolvable, (
            f"GPIO pad-bus stability: the reference sample is missing or was not resolvable ({ref})"
        )
        assert ref.vec_width > 0, (
            "GPIO pad-bus stability: the reference sample carries no pad-bus "
            f"vectors (tb_core2pad_o / tb_core2pad_en_o absent from tb_top?): "
            f"{ref}"
        )
        # Positive control first: without it the vector compare below would be
        # booked OBSERVED-ONLY and this sequence would claim nothing.
        await ensure_gpio_pad_bus_control(self)
        for probe in ("gpio_core2pad_vec", "gpio_core2pad_en_vec"):
            assert probe_alive(probe), (
                f"GPIO pad-bus stability: {probe} was not credited by the "
                f"pad-bus positive control, so a cross-sample compare on it "
                f"cannot be presented as checked evidence "
                f"({probe_evidence(probe)})"
            )
        seen_before = sb.gpio_samples_seen
        for i in range(self.samples):
            await ClockCycles(dut.clk_ref_i, self.gap_ref_cycles)
            item = SmcGpioItem(f"stability_{i}")
            item.op = SmcGpioOp.SAMPLE
            for field in GPIO_STABLE_VECTOR_FIELDS:
                setattr(item, "expect_" + field, getattr(ref, field))
            await self.start_item(item)
            await self.finish_item(item)
            # finish_item returns after the driver's ap.write(), so the
            # scoreboard's exact compares above have already run and passed.
            for field in GPIO_STABLE_VECTOR_FIELDS:
                exp = getattr(ref, field)
                got = getattr(item, field)
                assert got == exp, (
                    f"GPIO {field} changed between the reference sample and "
                    f"stability sample {i} (0x{exp:x} -> 0x{got:x}) over "
                    f"{(i + 1) * self.gap_ref_cycles} clk_ref_i cycles, after "
                    f"the pad-bus control restored GPIO0 DATA_CTRL and with no "
                    f"further GPIO CSR programming or pad drive in this test: "
                    f"reference={ref} sample={item}"
                )
            self.checked.append(item)
        observed = sb.gpio_samples_seen - seen_before
        assert observed == self.samples, (
            f"GPIO pad-bus stability: scoreboard booked {observed} SAMPLE "
            f"items, expected {self.samples} (a mis-bound analysis port would "
            f"make the cross-sample compare vacuous)"
        )
        cocotb.log.info(
            "CHK-GPIO-PAD-BUS-STABLE: %d sample(s) %d clk_ref_i apart all "
            "exact-compared by the scoreboard against the reference "
            "tb_core2pad_en_o=0x%x (%d pads), backed by this run's pad-bus "
            "positive control (%s). NOT checked evidence in this token: "
            "tb_core2pad_o (=0x%x at the reference) carries free-running pad "
            "outputs such as the AVSBus clock on bit 49, and the three "
            "tb_gpio_*_any OR-aggregates (%d/%d/%d) admit no control at all -- "
            "both are reported as diagnostics only.",
            self.samples,
            self.gap_ref_cycles,
            ref.core2pad_en_vec,
            ref.vec_width,
            probe_evidence("gpio_core2pad_en_vec"),
            ref.core2pad_vec,
            ref.core2pad_any,
            ref.core2pad_en_any,
            ref.pad2core_en_any,
        )
