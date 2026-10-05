# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Dual-SMC elaboration probe.

Answers whether Verilator can carry two SMC instances with a measurement
rather than a guess.
The build cost is recorded by the runner; this test only has to prove the 2x
model elaborates and that both instances leave the shared cold reset, so that a
later failure in the OCCP flow cannot be blamed on the doubled top.

No bus traffic, no firmware. Checks:
  * both instances report powergood_stable and release their primary SMC reset
  * both reach fuse-sense done and memory-init done
  * the shared I3C0 bus idles high (nothing drives it before firmware runs) and
    the wired-AND resolves without X
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from smc_dual_base_test import SmcDualHarness, dual_test
from smc_occp_dual_defs import SHARED_I3C_CHANNELS

REQUIRED_EVIDENCE = (
    "CHK-DUAL-BOOT-STALL",
    "CHK-DUAL-ELAB",
    "CHK-DUAL-FUSE-SENSE",
    "CHK-DUAL-I3C-IDLE",
    "CHK-DUAL-I3C-INDEXING",
    "CHK-DUAL-MEM-INIT",
    "CHK-DUAL-RESET",
)

# Both instances must clear fuse sense within this many clk_smc cycles. The
# single-instance smc_cpu_firmware_boot_test uses a 200k-cycle bound for the
# same eFuse responder; keep it.
FUSE_SENSE_BOUND = 200_000


def _resolved(sig) -> bool:
    return sig.value.is_resolvable


async def _wait_high(name: str, sig, clk, bound: int) -> int:
    for cycle in range(bound):
        await ClockCycles(clk, 1)
        if _resolved(sig) and int(sig.value) == 1:
            return cycle + 1
    raise AssertionError(f"TIMEOUT {name}: still {sig.value} after {bound} clk_smc_i cycles")


def _check_i3c_counter_indexing(dut) -> None:
    """Assert cocotb indexes the per-channel I3C counters the way the TB meant.

    The TB exports tb_i3c_channel_id_N = SharedI3cIdx[N], so the mapping can
    be read rather than assumed: cocotb reads an unpacked-array port as element 0
    for every index, which would attribute every channel's traffic to I3C0. The
    counters are flat scalars, and this check makes that class of silent
    mis-attribution fail loudly.
    """
    seen = [
        int(getattr(dut, f"tb_i3c_channel_id_{pos}").value)
        for pos in range(len(SHARED_I3C_CHANNELS))
    ]
    assert seen == list(SHARED_I3C_CHANNELS), (
        f"cocotb sees the I3C counter positions as {seen} but the testbench "
        f"assigned {list(SHARED_I3C_CHANNELS)}. Every per-channel count and "
        "every 'transfer seen on I3Cn' label is mis-attributed by this amount."
    )
    cocotb.log.info(
        "CHK-DUAL-I3C-INDEXING: cocotb reads tb_i3c_channel_id as %s; the TB "
        "assigns SharedI3cIdx = %s",
        seen,
        list(SHARED_I3C_CHANNELS),
    )


@dual_test(REQUIRED_EVIDENCE)
async def smc_dual_elaboration_test(harness: SmcDualHarness) -> None:
    dut = harness.dut

    await harness.bring_up()

    # After bring_up, which is where the [BUILD-MODEL-IDENTITY] guard runs. The
    # ports read below exist only on the dual model, so probing them first
    # turns a run against another target's model into an AttributeError naming
    # one port instead of the guard's account of which model answered.
    # tb_i3c_channel_id_N is a continuous assign from a localparam
    # (tb_top.sv), so it reads the same here as it did at time zero.
    _check_i3c_counter_indexing(cocotb.top)

    # Both instances present and powered. powergood_stable is the output of a
    # 32-deep clk_ref_i sync chain off powergood_i (smc_reset_ctrl.sv), so wait
    # for it with a bound rather than sampling once.
    assert int(dut.dual_present_o.value) == 1, "dual top did not elaborate"
    dut_pg = await _wait_high(
        "dut_powergood_stable_o", dut.dut_powergood_stable_o, dut.clk_ref_i, 1000
    )
    bfm_pg = await _wait_high(
        "bfm_powergood_stable_o", dut.bfm_powergood_stable_o, dut.clk_ref_i, 1000
    )
    cocotb.log.info(
        "CHK-DUAL-ELAB: both smc_wrapper instances elaborated; powergood_stable "
        "after %d / %d clk_ref_i cycles (dut / bfm)",
        dut_pg,
        bfm_pg,
    )

    # Independent reset release. Both share one cold reset, so this proves the
    # two reset trees are wired, not that they are independent domains.
    for name in ("dut_rst_primary_smc_clk_no", "bfm_rst_primary_smc_clk_no"):
        sig = getattr(dut, name)
        assert _resolved(sig), f"{name} unresolvable after reset settle"
        assert int(sig.value) == 1, f"{name} still asserted (= {sig.value})"
    cocotb.log.info("CHK-DUAL-RESET: dut/bfm rst_primary_smc_clk_no both deasserted")

    # eFuse sense + memory init on both sides. These are the two boot-sequencer
    # gates that would silently stall a firmware run.
    dut_fuse = await _wait_high(
        "dut_fuse_sense_done",
        dut.dut_fuse_sense_done_o,
        dut.clk_smc_i,
        FUSE_SENSE_BOUND,
    )
    bfm_fuse = await _wait_high(
        "bfm_fuse_sense_done",
        dut.bfm_fuse_sense_done_o,
        dut.clk_smc_i,
        FUSE_SENSE_BOUND,
    )
    cocotb.log.info(
        "CHK-DUAL-FUSE-SENSE: dut done after %d cycles, bfm after %d cycles (bound=%d)",
        dut_fuse,
        bfm_fuse,
        FUSE_SENSE_BOUND,
    )

    # Memory init is gated by fuse_reset_n, which boot_stall holds asserted
    # (smc_cpu_wrapper.sv wires mem_init_reset_ni to fuse_reset_ni; the zeroing
    # FSM in smc_4core_cpu.sv is reset by it). So while the probe holds
    # boot_stall on both instances, init_mem_done must still be LOW -- that is
    # the boot-stall contract, and a 1 here would mean boot_stall is not
    # reaching the reset path on this top.
    for name in ("dut_init_mem_done_o", "bfm_init_mem_done_o"):
        sig = getattr(dut, name)
        assert _resolved(sig) and int(sig.value) == 0, (
            f"{name} = {sig.value} while boot_stall is held; boot_stall is not "
            "gating fuse_reset_n on this instance"
        )
    cocotb.log.info(
        "CHK-DUAL-BOOT-STALL: init_mem_done low on both instances while "
        "boot_stall is held (fuse_reset_n gated)"
    )

    # Shared I3C0 bus: no firmware has run (both cores are still stalled), so
    # the wired-AND must resolve to a clean idle 1 on both lines. An X here
    # would mean the resolver is reading an undriven OE probe and every later
    # I3C result on this top is meaningless.
    await ClockCycles(dut.clk_periph_i, 100)
    for name in ("tb_i3c0_scl", "tb_i3c0_sda"):
        sig = getattr(dut, name)
        assert _resolved(sig), (
            f"{name} is {sig.value}: the shared open-drain resolver is not "
            "producing a defined value, so no I3C traffic on this top can be "
            "trusted"
        )
        assert int(sig.value) == 1, f"{name} idles low (= {sig.value})"
    for name in (
        "tb_i3c0_scl_dut_low",
        "tb_i3c0_sda_dut_low",
        "tb_i3c0_scl_bfm_low",
        "tb_i3c0_sda_bfm_low",
    ):
        sig = getattr(dut, name)
        assert _resolved(sig) and int(sig.value) == 0, (
            f"{name} = {sig.value} with no firmware running"
        )
    cocotb.log.info(
        "CHK-DUAL-I3C-IDLE: shared I3C0 resolves to idle high; neither "
        "instance pulls SCL/SDA low before firmware runs"
    )

    # Release boot_stall on both instances and require memory init to complete.
    # This is the other half of the boot-stall contract, and it proves both
    # reset paths actually come out of hold rather than being permanently
    # stuck -- which the held-low check above cannot distinguish on its own.
    harness.set_gpio_override("dut", 57, 0)
    harness.set_gpio_override("bfm", 57, 0)
    dut.dut_boot_stall_hold.value = 0
    dut.bfm_boot_stall_hold.value = 0
    await ClockCycles(dut.clk_smc_i, 64)

    dut_init = await _wait_high(
        "dut_init_mem_done", dut.dut_init_mem_done_o, dut.clk_smc_i, FUSE_SENSE_BOUND
    )
    bfm_init = await _wait_high(
        "bfm_init_mem_done", dut.bfm_init_mem_done_o, dut.clk_smc_i, FUSE_SENSE_BOUND
    )
    cocotb.log.info(
        "CHK-DUAL-MEM-INIT: after boot_stall release, init_mem_done asserted "
        "after %d / %d clk_smc_i cycles (dut / bfm)",
        dut_init,
        bfm_init,
    )

    cocotb.log.info("smc_dual_elaboration_test PASS")
