# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I3C pin-level helpers for SMC OSS tests.

What the testbench determines and what the DUT determines
--------------------------------------------------------
``tb/tb_top.sv`` resolves the open-drain I3C0 pads itself::

    assign tb_i3c0_scl_dut_low = i3c_scl_oe_to_pad[0] && !i3c_scl_to_pad[0]; // :674
    assign tb_i3c0_sda_dut_low = i3c_sda_oe_to_pad[0] && !i3c_sda_to_pad[0]; // :676
    assign tb_i3c0_scl = !(tb_i3c0_scl_dut_low || tb_i3c0_scl_ext_low);      // :678
    assign tb_i3c0_sda = !(tb_i3c0_sda_dut_low || tb_i3c0_sda_ext_low);      // :679

``*_ext_low`` are **testbench inputs** this helper drives, so while an
``ext_low`` is 1 the matching resolved pad is 0 by that combinational assign
whatever the DUT does: asserting it would be a tautology and is therefore NOT
checked or tokenized here (``[NO-ALWAYS-PASS-CHECKER]``).

Why the DUT-drive levels are OBSERVED-ONLY here
-----------------------------------------------------------------
``tb_i3c0_{scl,sda}_dut_low`` really are DUT-determined, but every expectation
this helper could place on them in this bench is ``0`` -- and no positive
control for either net exists anywhere in this testbench, so ``== 0`` would pass
identically against a DUT that tied ``i3c_*_oe_to_pad`` low, against a
black-boxed core, and against a core whose pad driver is broken. That is exactly
the shape policy ``[NEGATIVE-NEEDS-POSITIVE-CONTROL]`` prohibits, so the levels
are **recorded, not asserted**, and no ``CHK-`` token claims them as checks.

The core is enabled -- ``smc_i3c_to_fabric_test_seq`` writes the RDL-declared
``HC_CONTROL.BUS_ENABLE`` and value-compares the readback, and this helper runs
with the core enabled (``core_enabled=True``) -- but an enabled controller with
no bus transfer queued releases both open-drain lines, so ``*_dut_low`` never
reaches 1. Making the core drive SCL/SDA requires queueing real I3C bus
traffic, which this bench does not generate, so no ``PROBE_CONTROLS`` entry can
be built for these nets here.

The two nets are not registered in ``PROBE_SIGNALS`` / ``UNBACKABLE_PROBES``
(``env/smc_probe_liveness.py``); this helper carries the disclosure in its own
retained log line instead.

What therefore IS asserted here: every I3C0 net must be resolvable (never X/Z)
at every sample point, in every step, with the core enabled. An X on a pad is a
real defect and that check is fail-capable independently of any level
expectation.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge

# Bound, in clk_smc_i cycles, for the resolved pad to follow an ``ext_low``
# change. The wait below polls the pad level and FAILS on expiry with
# last-state diagnostics ([NO-BLIND-DELAY-SYNC] / [TIMEOUT-MUST-FAIL]); the
# property under check is the level, not the latency.
_PAD_FOLLOW_TIMEOUT_CYCLES = 200

_I3C0_NETS = (
    "tb_i3c0_scl",
    "tb_i3c0_sda",
    "tb_i3c0_scl_dut_low",
    "tb_i3c0_sda_dut_low",
    "tb_i3c0_scl_ext_low",
    "tb_i3c0_sda_ext_low",
)


def _pad_level(dut, sig_name: str, step: str) -> int:
    """Resolve an I3C0 net to 0/1, FAILING when it is X/Z in the checked window.

    ``int(sig.value)`` on an unresolved net either raises or resolves
    arbitrarily; either way an X would hide a real defect rather than report it
    ([X-AWARE-CHECK]).
    """
    value = getattr(dut, sig_name).value
    assert value.is_resolvable, (
        f"I3C0 {step}: {sig_name} is not resolvable (value={value!s}) during the "
        f"checked window -- X/Z on the resolved pad is a defect, not a pass"
    )
    return int(value)


def _state(dut, step: str) -> str:
    """Last-state diagnostic string: both pads, both DUT drives, both controls."""
    return (
        f"scl={_pad_level(dut, 'tb_i3c0_scl', step)} "
        f"sda={_pad_level(dut, 'tb_i3c0_sda', step)}, "
        f"dut_low scl={_pad_level(dut, 'tb_i3c0_scl_dut_low', step)} "
        f"sda={_pad_level(dut, 'tb_i3c0_sda_dut_low', step)}, "
        f"ext_low scl={_pad_level(dut, 'tb_i3c0_scl_ext_low', step)} "
        f"sda={_pad_level(dut, 'tb_i3c0_sda_ext_low', step)}"
    )


async def _settle_tb_resolved_pad(dut, sig_name: str, level: int, step: str) -> None:
    """Synchronization ONLY -- never evidence.

    Waits (bounded) for a pad whose level this step forced through
    ``tb_top.sv:687-688``. Since ``ext_low`` determines it, reaching the level
    proves nothing about the DUT; it only lets the drive change propagate before
    the step's samples are taken. Emits no ``CHK-`` token. Expiry
    still fails, because a TB-forced level that never appears means the pad
    resolution itself is broken.
    """
    for _ in range(_PAD_FOLLOW_TIMEOUT_CYCLES):
        if _pad_level(dut, sig_name, step) == level:
            return
        await RisingEdge(dut.clk_smc_i)
    raise AssertionError(
        f"I3C0 {step}: TB-forced {sig_name} never reached {level} within "
        f"{_PAD_FOLLOW_TIMEOUT_CYCLES} smc clocks -- the tb_top open-drain "
        f"resolution is broken ({_state(dut, step)})"
    )


def _sample_step(dut, step: str) -> dict[str, int]:
    """Resolvability-checked sample of every I3C0 net for one step.

    Returns the levels for the OBSERVED-ONLY record. Nothing here compares a
    level against an expectation -- see the module docstring.
    """
    return {net: _pad_level(dut, net, step) for net in _I3C0_NETS}


async def observe_i3c0_external_pull_low(core_enabled: bool = False) -> None:
    """Drive the I3C0 external pull-low steps and record what the pads did.

    Drives the split-port ``tb_i3c0_{scl,sda}_ext_low`` controls through a
    release / SCL-low / SDA-low / release sequence. At every step every I3C0 net
    is sampled and required to be resolvable; the DUT-drive levels are recorded
    as OBSERVED-ONLY diagnostics and are NOT asserted, because no positive
    control for those nets exists in this testbench (module docstring).

    ``core_enabled`` records whether the caller has the I3C host controller
    enabled (``HC_CONTROL.BUS_ENABLE``) across this window; it only affects the
    retained log line, so the disclosure cannot drift from what actually ran.

    This is a pad-level observation pass, not a claim about I3C bus protocol.
    """
    dut = cocotb.top
    samples: dict[str, dict[str, int]] = {}

    # Step 1: both controls released.
    dut.tb_i3c0_scl_ext_low.value = 0
    dut.tb_i3c0_sda_ext_low.value = 0
    await ClockCycles(dut.clk_smc_i, 1)
    await _settle_tb_resolved_pad(dut, "tb_i3c0_scl", 1, "release")
    await _settle_tb_resolved_pad(dut, "tb_i3c0_sda", 1, "release")
    samples["release"] = _sample_step(dut, "release")

    # Step 2: external SCL pull-low.
    dut.tb_i3c0_scl_ext_low.value = 1
    await ClockCycles(dut.clk_smc_i, 1)
    await _settle_tb_resolved_pad(dut, "tb_i3c0_scl", 0, "scl_low")
    samples["scl_low"] = _sample_step(dut, "scl_low")

    # Step 3: swap -- external SDA pull-low, SCL released.
    dut.tb_i3c0_scl_ext_low.value = 0
    dut.tb_i3c0_sda_ext_low.value = 1
    await ClockCycles(dut.clk_smc_i, 1)
    await _settle_tb_resolved_pad(dut, "tb_i3c0_sda", 0, "sda_low")
    await _settle_tb_resolved_pad(dut, "tb_i3c0_scl", 1, "sda_low")
    samples["sda_low"] = _sample_step(dut, "sda_low")

    # Step 4: release again.
    dut.tb_i3c0_sda_ext_low.value = 0
    await ClockCycles(dut.clk_smc_i, 1)
    await _settle_tb_resolved_pad(dut, "tb_i3c0_sda", 1, "release_restore")
    samples["release_restore"] = _sample_step(dut, "release_restore")

    observed = "; ".join(
        f"{step}: scl_dut_low={s['tb_i3c0_scl_dut_low']} "
        f"sda_dut_low={s['tb_i3c0_sda_dut_low']} "
        f"scl={s['tb_i3c0_scl']} sda={s['tb_i3c0_sda']}"
        for step, s in samples.items()
    )
    # Not a CHK- token: `is_resolvable` cannot be false on a two-state
    # simulator, so a Verilator run would carry a checker that cannot fail.
    # The resolvability asserts above stay as X-guards on the samples; the
    # record below is diagnostic only.
    cocotb.log.info(
        "OBSERVED-ONLY-I3C0-PADS-RESOLVABLE (not a check on a two-state simulator): 4 "
        "external-pull steps driven with the I3C host controller %s; all %d I3C0 nets "
        "sampled resolvable at every one of the %d sample points",
        "ENABLED (HC_CONTROL.BUS_ENABLE=1)" if core_enabled else "left disabled",
        len(_I3C0_NETS),
        len(samples) * len(_I3C0_NETS),
    )
    # Diagnostics: NOT a CHK- token and NOT asserted.
    cocotb.log.info(
        "OBSERVED-ONLY-I3C0-DUT-DRIVE (not a check): %s. These levels are "
        "recorded, not compared: an idle == 0 expectation on "
        "tb_i3c0_{scl,sda}_dut_low has no positive control in this testbench, so "
        "it would also pass on a dead pad driver "
        "([NEGATIVE-NEEDS-POSITIVE-CONTROL]). "
        "applies: the core IS enabled here and its HC_CONTROL.BUS_ENABLE "
        "readback is value-checked, but a DUT-driven low needs queued I3C bus "
        "traffic, which hw/sys/smc/dv/README.md:11-15 defers (I3C real-core "
        "protocol is not ported). Registering these nets in "
        "env/smc_probe_liveness.py UNBACKABLE_PROBES is the remaining step and "
        "is owned outside this helper.",
        observed,
    )


__all__ = [
    "observe_i3c0_external_pull_low",
]
