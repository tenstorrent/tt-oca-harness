# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Run-scoped liveness ledger for the ``tb_top`` observability probes.

Why this module exists
----------------------
Several SMC observability legs are *idle-zero* compares: the scoreboard asserts
``tb_sync_irq == 0``, ``tb_uart_irq_any == 0``, ``tb_i2c_cg_en == 0``,
``tb_axil_*_active == 0``.  On their own those are pure negative checks -- a
stuck-at-0 net, an undriven port, or a ``tb_top.sv`` assign orphaned by an RTL
rename passes every one of them exactly as a live, genuinely quiet DUT does
(policy ``[NEGATIVE-NEEDS-POSITIVE-CONTROL]``).

This module records, **per run and from the DUT itself**, which of those probes
was actually observed at 1 at some point in the run.  A passive watcher started
by ``smc_base_test._bring_up`` samples each probe on every ``clk_smc_i`` rising
edge; the first resolved 1 credits the probe with the simulation time at which
it was seen.  No force, no deposit, no write -- the watcher only reads.

``SmcScoreboard`` consults :func:`probe_alive` to decide, for every idle leg it
is asked to book, which of exactly **two** categories the leg falls in:

* **checked** -- the same probe was observed at 1 somewhere in this run, so the
  ``== 0`` compare can distinguish quiet from dead and is real evidence;
* **OBSERVED-ONLY** -- the probe was never seen at 1 in this run, so the value
  is logged as a diagnostic and explicitly *not* presented as checked evidence.

There is no third category: a value is either exact-compared with a same-run
positive control behind it, or it is declared unchecked in the kept log.

The stimulus that makes a probe read 1 lives in
``seq_lib/smc_probe_positive_control.py`` (bounded, fail-capable, frontdoor
only).  The ledger is separate from that stimulus so the credit is
an *observation* of the DUT rather than a claim made by the code that drove it.

Probes with no buildable control
--------------------------------
:data:`UNBACKABLE_PROBES` lists every probe for which **no same-run stimulus can
distinguish the net from a stuck one, in either direction**.  Such a probe is
never exact-compared by the scoreboard, never credited, and never counted as
checked evidence; its value is logged as a diagnostic and declared as such.

* ``tb_axil_dtp_csr_active`` -- unbackable *at 1*. ``tb_top.sv:1100`` ties
  ``axil_dtp_csr_resp = '0'``: there is no responder, so an AXI-Lite access to
  the DTP CSR window would wedge rather than complete, and the DTP CSR boundary
  is a recorded TB-policy deferral (``hw/sys/smc/dv/README.md``).
* ``gpio_core2pad_any`` / ``gpio_core2pad_en_any`` / ``gpio_pad2core_en_any`` --
  unbackable *at 0*.  ``tb_top.sv`` defines all three as OR-reductions over the
  **whole** pad bus (``|u_dut.u_smc.core2pad_o`` and friends).  The AVSBus
  clock and mdata pads (bits 49/50, ``tb_top.sv``) are output-enabled from
  reset and no frontdoor CSR write (including ``CLOCK_GATE_CONTROL.AVS_CG_EN``)
  clears them, so all three reductions read 1 from reset onward and this TB has
  no frontdoor path that drives any of them to 0.  A net tied to constant 1 is
  therefore indistinguishable from the real aggregate, which is exactly what
  ``[NEGATIVE-NEEDS-POSITIVE-CONTROL]`` forbids presenting as evidence -- so
  they are OBSERVED-ONLY and a stated ``expect_<field>`` on them is refused.
  The *fail-capable* GPIO pad-bus observability proof is on the raw vectors
  instead (``gpio_core2pad_vec`` / ``gpio_core2pad_en_vec`` below, whose control
  is ``seq_lib.smc_probe_positive_control.prove_gpio_pad_bus_probe``).

Watched vs control-only probes
------------------------------
The passive watcher credits a probe the first time it reads 1.  That is a
meaningful liveness event only for a probe that is **0 at idle**; for a probe
that is non-zero from reset the first-1 credit would be automatic and would
certify nothing.  :data:`WATCHED_PROBES` is therefore the explicit subset the
watcher may credit, and every other entry of :data:`PROBE_SIGNALS` can only be
credited by a control that proves the observable *changed* under real stimulus.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge
from cocotb.utils import get_sim_time

# ---------------------------------------------------------------- probe names --
# Logical probe name -> tb_top signal. The logical names are what the scoreboard
# and the positive-control helpers agree on; keep them equal to the item field
# name where one exists (`SmcIrqItem.sync_irq` -> "sync_irq").
PROBE_SIGNALS: dict[str, str] = {
    "sync_irq": "tb_sync_irq",
    "gpio_irq_any": "tb_gpio_irq_any",
    "uart_irq_any": "tb_uart_irq_any",
    "i2c_cg_en": "tb_i2c_cg_en",
    "axil_external_active": "tb_axil_external_active",
    "axil_efuse_bank_active": "tb_axil_efuse_bank_active",
    "axil_any_master_active": "tb_axil_any_master_active",
    # GPIO pad-output bus vectors. Non-zero at idle (LSIO pads), so the passive
    # first-1 credit would be automatic and prove nothing: they are
    # NOT in WATCHED_PROBES and can only be credited by
    # seq_lib.smc_probe_positive_control.prove_gpio_pad_bus_probe, which drives a
    # real frontdoor CSR change and requires the vector to MOVE.
    "gpio_core2pad_vec": "tb_core2pad_o",
    "gpio_core2pad_en_vec": "tb_core2pad_en_o",
}

# The subset of PROBE_SIGNALS the passive watcher may credit on its first
# observed 1. A probe outside this set idles non-zero, so a first-1 credit would
# be automatic and would certify nothing -- it must be credited by a control that
# proves the observable changed under real stimulus.
WATCHED_PROBES: tuple[str, ...] = (
    "sync_irq",
    "gpio_irq_any",
    "uart_irq_any",
    "i2c_cg_en",
    "axil_external_active",
    "axil_efuse_bank_active",
    "axil_any_master_active",
)

# Probes that cannot be given a positive control in this TB, with the reason.
# A probe listed here is never exact-compared by the scoreboard and never
# counted as checked evidence, regardless of the ledger.
UNBACKABLE_PROBES: dict[str, str] = {
    "axil_dtp_csr_active": (
        "tb_top.sv:1100 ties axil_dtp_csr_resp = '0' (no responder, an access "
        "would wedge instead of completing) and the DTP CSR boundary is a "
        "recorded TB-policy deferral (hw/sys/smc/dv/README.md); no "
        "frontdoor stimulus can "
        "make tb_axil_dtp_csr_active read 1, so its idle value is "
        "OBSERVED-ONLY and NOT closure evidence"
    ),
    "gpio_core2pad_any": (
        "tb_top.sv:1306 defines tb_gpio_core2pad_any = |u_dut.u_smc.core2pad_o, "
        "an OR-reduction over the WHOLE pad-output bus. A one-off bench "
        "reading at reset (no kept artifact) saw set bits 28, 30, 32, 34, 36, "
        "49, 50 and 64; 49 and 50 are the AVSBus clock and mdata outputs "
        "(tb_top.sv:727-728). One frontdoor write of "
        "CLOCK_GATE_CONTROL.AVS_CG_EN was tried and did not move those bits, "
        "so this TB has no frontdoor path that drives the reduction to "
        "0 and a net tied to constant 1 is indistinguishable from the real "
        "aggregate. Its value is OBSERVED-ONLY and NOT closure evidence; the "
        "fail-capable pad-bus proof is on the raw vector probe "
        "gpio_core2pad_vec (tb_core2pad_o)"
    ),
    "gpio_core2pad_en_any": (
        "tb_top.sv:1307 defines tb_gpio_core2pad_en_any = "
        "|u_dut.u_smc.core2pad_en_o, an OR-reduction over the WHOLE pad "
        "output-enable bus. A one-off bench reading at reset (no kept "
        "artifact) saw exactly two bits set -- 49 and 50, the AVSBus clock "
        "and mdata pads (tb_top.sv:727-728) -- not a broad band of LSIO pads. "
        "One frontdoor write of CLOCK_GATE_CONTROL.AVS_CG_EN was tried and "
        "did not move them, so nothing here drives the reduction to 0. "
        "OBSERVED-ONLY; the fail-capable pad-bus proof is on the raw vector probe "
        "gpio_core2pad_en_vec (tb_core2pad_en_o)"
    ),
    "gpio_pad2core_en_any": (
        "tb_top.sv:1308 defines tb_gpio_pad2core_en_any = "
        "|u_dut.u_smc.pad2core_en_o, an OR-reduction over the WHOLE pad "
        "input-enable bus, which is measured at 1 from reset onward; tb_top "
        "exposes no "
        "pad2core_en_o vector, so there is neither a level control nor an "
        "independent per-pad observable for it in this TB. OBSERVED-ONLY and NOT "
        "closure evidence"
    ),
}

# Consistency rails, checked at import so a mistake cannot reach a run silently.
assert not (set(WATCHED_PROBES) - set(PROBE_SIGNALS)), (
    "WATCHED_PROBES names a probe absent from PROBE_SIGNALS: "
    f"{sorted(set(WATCHED_PROBES) - set(PROBE_SIGNALS))}"
)
assert not (set(WATCHED_PROBES) & set(UNBACKABLE_PROBES)), (
    "a probe cannot be both watched-for-liveness and unbackable: "
    f"{sorted(set(WATCHED_PROBES) & set(UNBACKABLE_PROBES))}"
)
assert not (set(PROBE_SIGNALS) & set(UNBACKABLE_PROBES)), (
    "a probe cannot be both credit-able and unbackable: "
    f"{sorted(set(PROBE_SIGNALS) & set(UNBACKABLE_PROBES))}"
)
assert all(reason for reason in UNBACKABLE_PROBES.values()), (
    "every UNBACKABLE_PROBES entry must carry the reason it cannot be backed"
)

# probe name -> human-readable evidence string of the first observed 1.
_ALIVE: dict[str, str] = {}


def reset_probe_ledger() -> None:
    """Clear the ledger (call once per test, before the watcher starts)."""
    _ALIVE.clear()


def credit_probe(probe: str, evidence: str) -> None:
    """Record that ``probe`` was observed at 1, with how it was observed."""
    if probe in UNBACKABLE_PROBES:
        raise AssertionError(
            f"{probe} is declared unbackable in this TB and must never be "
            f"credited: {UNBACKABLE_PROBES[probe]}"
        )
    _ALIVE.setdefault(probe, evidence)


def refuse_expectation_on_unbackable(probe: str, label: str, expectation, where: str) -> None:
    """Refuse a stated ``expect_*`` on a probe that can never be backed.

    The compare side of the scoreboard needs the same structural rail
    :func:`credit_probe` has on the ledger side. Without it, the invariant "an
    unbackable probe is never exact-compared" holds only for as long as nobody
    writes a setter -- and the first sequence that does gets a silent, unbacked
    negative compare that the guard comments claim cannot exist.
    """
    if probe in UNBACKABLE_PROBES and expectation is not None:
        raise AssertionError(
            f"{where}: {label} carries expect={expectation}, but {probe} is "
            f"declared unbackable in this TB and must never be exact-compared: "
            f"{UNBACKABLE_PROBES[probe]}"
        )


def probe_alive(probe: str) -> bool:
    """True when ``probe`` was observed at 1 at least once in this run."""
    return probe in _ALIVE


def probe_evidence(probe: str) -> str:
    """Evidence string for a credited probe, or the reason it has none."""
    if probe in _ALIVE:
        return _ALIVE[probe]
    if probe in UNBACKABLE_PROBES:
        return f"UNBACKABLE: {UNBACKABLE_PROBES[probe]}"
    return "never observed at 1 in this run"


def alive_probes() -> dict[str, str]:
    """Copy of the ledger, for end-of-run reporting."""
    return dict(_ALIVE)


async def watch_probe_liveness(dut=None) -> None:
    """Passive per-cycle watcher: credit every probe the DUT drives to 1.

    Reads only. Samples all not-yet-credited probes on each ``clk_smc_i``
    rising edge and returns as soon as every watched probe has been credited,
    so a test that exercises all of them stops paying the sampling cost.

    Only :data:`WATCHED_PROBES` are eligible: a probe that idles non-zero would
    be credited on the first edge, which would certify nothing and would turn the
    ledger into a rubber stamp.

    A watched probe whose ``tb_top`` handle is missing raises immediately, so
    an RTL rename fails by naming the absent signal rather than as an
    uncredited idle leg.
    """
    dut = dut if dut is not None else cocotb.top
    clk = dut.clk_smc_i
    missing = [probe for probe in WATCHED_PROBES if not hasattr(dut, PROBE_SIGNALS[probe])]
    if missing:
        # Dropping an absent handle would shrink the watched set silently: a
        # tb_top rename then fails later (or not at all) as "idle legs were
        # booked on a probe no control credited", across every test that
        # samples that class. Fail at the source instead.
        detail = ", ".join(f"{p} ({PROBE_SIGNALS[p]})" for p in missing)
        raise AssertionError(
            f"watch_probe_liveness: {len(missing)} WATCHED_PROBES signal(s) "
            f"are absent from the DUT and can never be credited: {detail}"
        )
    pending = [
        (probe, getattr(dut, PROBE_SIGNALS[probe]), PROBE_SIGNALS[probe])
        for probe in WATCHED_PROBES
    ]
    while pending:
        await RisingEdge(clk)
        still: list[tuple[str, object, str]] = []
        for probe, handle, sig in pending:
            value = handle.value
            if value.is_resolvable and int(value):
                credit_probe(
                    probe,
                    f"{sig} observed at 1 at "
                    f"{int(get_sim_time(unit='ns'))}ns by the passive "
                    f"probe-liveness watcher",
                )
            else:
                still.append((probe, handle, sig))
        pending = still
