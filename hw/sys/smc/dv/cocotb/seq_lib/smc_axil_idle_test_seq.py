# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smc_axil_idle_test.

Two legs, because "the AXI-Lite masters are idle" is a negative claim:

1. **Positive control** -- :func:`prove_axil_probe_alive` drives real frontdoor
   SEP_IN AXI traffic that makes the activity OR ``tb_axil_any_master_active``
   (and its ``tb_axil_efuse_bank_active`` term) observe 1. Without it a
   stuck-at-0 / undriven / mis-tied probe passes the idle assert identically
   (`[NEGATIVE-NEEDS-POSITIVE-CONTROL]`).
2. **Idle leg** -- one ``SmcAxilItem`` SAMPLE through the observer agent, whose
   *backable* activity bits (``AXIL_CHECKABLE_FIELDS``) must all read exactly 0.
   ``dtp_csr_active`` is excluded: no positive control for it can exist in this
   TB, so it is reported OBSERVED-ONLY and never exact-compared (see
   :func:`assert_axil_idle`). The ``CHK-AXIL-IDLE`` evidence token is emitted
   only after both legs and the typed scoreboard-counter end gate passed
   (`[EVIDENCE-TOKEN-CONDITIONAL]`).
"""

from __future__ import annotations

import cocotb
from env.smc_axil_item import (
    AXIL_CHECKABLE_FIELDS,
    AXIL_UNBACKABLE_FIELDS,
    SmcAxilItem,
    SmcAxilOp,
)

from .smc_base_test_seq import smc_base_test_seq
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_diagnostic_vip_utils import prove_axil_any_master_activity


class SmcAxilMasterActivitySeq(SmcCsrSeq):
    """Frontdoor traffic leg for the ``tb_axil_*_active`` positive control.

    The AXI-Lite agent is SAMPLE-only (``env/smc_env.py``: observability, not a
    BFM), so the traffic that makes the activity OR read 1 comes from the SEP_IN
    AXI master. The shared prover
    ``smc_diagnostic_vip_utils.prove_axil_any_master_activity`` needs
    ``SmcCsrSeq.csr_read``, so this sequence runs on the SEP_IN AXI sequencer.
    """

    async def body(self) -> None:
        await prove_axil_any_master_activity(self)


async def prove_axil_probe_alive(seq) -> None:
    """Run the shared AXI-Lite activity positive control from ``seq``.

    Starts :class:`SmcAxilMasterActivitySeq` on the env's SEP_IN AXI sequencer.
    Raises if the probe never reads 1 while the real request is in flight (the
    assert lives in the shared helper), so an AXI-Lite idle claim made after
    this call is backed by a proven-live probe.
    """
    assert seq.env is not None, (
        f"{seq.get_name()}: env is not wired, so the AXI-Lite activity positive "
        "control cannot reach the SEP_IN AXI sequencer (start the sequence via "
        "smc_base_test.start_seq)"
    )
    inner = SmcAxilMasterActivitySeq(f"{seq.get_name()}_axil_positive_control")
    inner.cfg = seq.cfg
    inner.env = seq.env
    await inner.start(seq.env.sys_axi_agent.sequencer)


def assert_axil_idle(item: SmcAxilItem) -> str:
    """Exact idle compare on every *backable* activity bit (fail-capable).

    Iterates ``AXIL_CHECKABLE_FIELDS``, not ``AXIL_SAMPLE_FIELDS``:
    ``dtp_csr_active`` has no positive control in this TB (``tb_top.sv`` ties
    ``axil_dtp_csr_resp = '0'``, so an access into the DTP CSR window wedges
    instead of completing). Its sampled value is returned as OBSERVED-ONLY text
    for the caller's evidence token and must never be presented as checked
    evidence; the scoreboard books it the same way
    (``env/smc_probe_liveness.UNBACKABLE_PROBES``).

    Returns the OBSERVED-ONLY summary string.
    """
    assert item.resolvable, f"{item.get_name()}: AXI-Lite activity bits are X/Z"
    for field in AXIL_CHECKABLE_FIELDS:
        got = getattr(item, field)
        assert got == 0, (
            f"{item.get_name()}: tb_axil_{field} = {got}, expected 0 (no "
            f"AXI-Lite master traffic is driven in this window) ({item})"
        )
    return ", ".join(f"tb_axil_{f}={getattr(item, f)}" for f in AXIL_UNBACKABLE_FIELDS)


class smc_axil_idle_test_seq(smc_base_test_seq):
    # Exact number of AXI-Lite SAMPLE items this body dispatches. The end gate
    # reconciles it against the scoreboard's typed counter, which is incremented
    # on the analysis path -- so a mis-bound agent, a dropped item or a monitor
    # that never published fails instead of leaving the idle claim resting on an
    # item nothing booked ([NO-ZERO-ACTIVITY-PASS]). The declared probe positive
    # controls dispatch no agent SAMPLE items, so this count is exact.
    EXPECTED_AXIL_SAMPLES = 1

    def __init__(self, name: str = "smc_axil_idle_test_seq") -> None:
        super().__init__(name)
        self.sample: SmcAxilItem | None = None

    async def body(self) -> None:
        assert self.env is not None, (
            f"{self.get_name()}: env is not wired, so the typed scoreboard "
            "counter gate cannot run (start via smc_base_test.start_seq)"
        )
        sb = self.env.scoreboard
        before = sb.axil_samples_seen

        # Leg 1: prove the activity probe can read 1 under real master traffic.
        await prove_axil_probe_alive(self)

        # Leg 2: the idle observation itself, through the observer agent.
        item = SmcAxilItem("sample")
        item.op = SmcAxilOp.SAMPLE
        await self.start_item(item)
        await self.finish_item(item)
        self.sample = item
        observed_only = assert_axil_idle(item)

        # End gate: the sampled item this sequence holds is the same one the
        # scoreboard booked, and it booked exactly as many as were dispatched.
        booked = sb.axil_samples_seen - before
        assert booked == self.EXPECTED_AXIL_SAMPLES, (
            f"AXI-Lite idle claim rests on {booked} scoreboard-booked SAMPLE "
            f"item(s), expected {self.EXPECTED_AXIL_SAMPLES} "
            f"(sample={self.sample})"
        )
        assert self.sample is item and self.sample.resolvable, (
            f"AXI-Lite SAMPLE item was not retained/resolved: {self.sample}"
        )
        cocotb.log.info(
            "CHK-AXIL-IDLE: after the frontdoor AXI-Lite positive control "
            "returned the probes to idle, %d scoreboard-booked SmcAxilItem "
            "SAMPLE reads %s all == 0 (%s) [OBSERVED-ONLY, NOT checked "
            "evidence -- no positive control can exist in this TB: %s]",
            booked,
            "/".join(f"tb_axil_{f}" for f in AXIL_CHECKABLE_FIELDS),
            item,
            observed_only,
        )
