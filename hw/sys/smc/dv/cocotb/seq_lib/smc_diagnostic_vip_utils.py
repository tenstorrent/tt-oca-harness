# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""ECC/DFD/DBS bounded diagnostic VIP helpers for SMC OSS tests.

``tb_axil_any_master_active`` (``hw/sys/smc/dv/tb/tb_top.sv``) is the OR of the
three downstream AXI-Lite master activity probes -- DTP CSR, smc_external and
eFuse bank. Like the eFuse-bank probe it is proven in **two legs**:

1. **Positive control** -- :func:`prove_axil_any_master_activity` drives real
   frontdoor stimulus that makes one of the OR's terms assert, and requires the
   OR to be *sampled at 1*. Without it, ``== 0`` on the OR also passes when the
   whole activity sensor is stuck low (`[NEGATIVE-NEEDS-POSITIVE-CONTROL]`).
2. **Idle re-check** -- :func:`check_diagnostic_observability`, which emits the
   ``CHK-DIAG-AXIL-IDLE`` evidence token only when leg 1 ran in the same test.

The reset levels this helper reports are exact-compared against their
design-intent post-bring-up state, so nothing is logged as "observed" that is
not also checked.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

from . import smc_efuse_vip_utils
from .smc_efuse_vip_utils import (
    EFUSE_SHIM_CTRL_WINDOW,
    count_probe_high_cycles,
    prove_efuse_bank_axil_activity,
    stop_sampler,
)

# Consume-once record of the positive-control observation (see module docstring).
_POSITIVE_CONTROL: list[str] = []


async def prove_axil_any_master_activity(seq) -> None:
    """Positive control for ``tb_axil_any_master_active`` (fail-capable at 1).

    Reuses the eFuse-bank leg of the OR: a real SEP_IN AXI read of the
    eFuse-shim window drives ``efuse_bank_ctrl_req_o.ar_valid``, which is one of
    the three terms of ``tb_axil_any_master_active``. Frontdoor only -- no force,
    deposit or backdoor on the proof path.

    The eFuse-bank term is used because it is the only OR term with a real
    responder in the DUT-only bench: the DTP CSR boundary is tied idle in
    ``tb_top.sv`` (``axil_dtp_csr_resp = '0'``) so an access there would wedge
    instead of completing.
    """
    dut = cocotb.top
    probe = dut.tb_axil_any_master_active
    assert probe.value.is_resolvable, (
        "tb_axil_any_master_active is not resolvable before the positive control"
    )
    assert int(probe.value) == 0, (
        "positive-control precondition failed: tb_axil_any_master_active is "
        "already 1 before any AXI-Lite master stimulus was issued"
    )

    hits = [0]
    sampler = cocotb.start_soon(count_probe_high_cycles(probe, dut.clk_smc_i, hits))
    try:
        await prove_efuse_bank_axil_activity(seq)
    finally:
        stop_sampler(sampler)
        # The nested eFuse-bank prover records its own observation for
        # check_efuse_otp_observability; a diagnostic test never consumes it, so
        # drop it here rather than leaving a stale credit behind.
        if smc_efuse_vip_utils._POSITIVE_CONTROL:
            smc_efuse_vip_utils._POSITIVE_CONTROL.pop()

    assert hits[0] > 0, (
        "tb_axil_any_master_active never sampled 1 while a real eFuse-bank "
        f"AXI-Lite request (SEP_IN read @ 0x{EFUSE_SHIM_CTRL_WINDOW:08x}) was in "
        "flight: the downstream-master activity OR is stuck at 0 / undriven / "
        "mis-tied, so any idle == 0 assertion on it is vacuous"
    )
    _POSITIVE_CONTROL.append(f"{hits[0]} clk_smc_i cycle(s) high")
    cocotb.log.info(
        "CHK-DIAG-AXIL-ACTIVE: tb_axil_any_master_active observed 1 for %d "
        "clk_smc_i cycle(s) under a real eFuse-bank AXI-Lite request; the "
        "downstream-master activity OR is alive and fail-capable",
        hits[0],
    )


async def check_diagnostic_observability() -> None:
    """Check bounded fault/debug observability after diagnostic CSR probes.

    Every level this helper reports is exact-compared here:

    * ``tb_axil_any_master_active == 0`` -- idle leg of the two-legged proof
      above; it is evidence only when the test ran the positive control.
    * ``rst_primary_smc_clk_no == 1`` and ``rst_wdt_smc_clk_no == 1`` --
      design-intent post-bring-up state: ``smc_base_test._bring_up`` asserts
      powergood and releases cold reset, so the SMC reset unit must have
      released the primary and WDT reset domains by the time the diagnostic CSR
      reads have completed (they could not have returned OKAY otherwise), and
      no step in a diagnostic CSR test re-asserts either. These are ``== 1``
      (deasserted) expectations, so they are not idle/negative checks.

    ``tb_sync_irq`` is NOT sampled or logged here: this path has no
    independently sourced expectation for it, and logging it as "observed" reads
    as a check that does not exist. SMC interrupt-aggregate observability is
    owned by ``smc_irq_observe_test_seq``.
    """
    dut = cocotb.top

    await ClockCycles(dut.clk_smc_i, 8)
    for signal in (
        dut.tb_axil_any_master_active,
        dut.rst_primary_smc_clk_no,
        dut.rst_wdt_smc_clk_no,
    ):
        assert signal.value.is_resolvable, f"{signal._name} is not resolvable"
    assert int(dut.tb_axil_any_master_active.value) == 0, (
        "Downstream AXI-Lite masters should be idle after diagnostic CSR probes"
    )
    assert int(dut.rst_primary_smc_clk_no.value) == 1, (
        "rst_primary_smc_clk_no must be released (1) after powergood + cold-reset "
        "bring-up and OKAY diagnostic CSR reads, got 0"
    )
    assert int(dut.rst_wdt_smc_clk_no.value) == 1, (
        "rst_wdt_smc_clk_no must be released (1) after bring-up (no WDT bite is "
        "stimulated by a diagnostic CSR test), got 0"
    )
    if _POSITIVE_CONTROL:
        cocotb.log.info(
            "CHK-DIAG-AXIL-IDLE: tb_axil_any_master_active == 0 after the "
            "diagnostic CSR probes, backed by this test's positive control "
            "(%s); rst_primary_smc_clk_no == 1 rst_wdt_smc_clk_no == 1",
            _POSITIVE_CONTROL.pop(),
        )
    else:
        cocotb.log.warning(
            "tb_axil_any_master_active sampled 0 after the diagnostic CSR "
            "probes, but this test ran no positive control "
            "(prove_axil_any_master_activity), so the observation cannot "
            "distinguish genuinely idle masters from a dead probe and is NOT "
            "closure evidence (rst_primary_smc_clk_no == 1 "
            "rst_wdt_smc_clk_no == 1 were checked)"
        )
