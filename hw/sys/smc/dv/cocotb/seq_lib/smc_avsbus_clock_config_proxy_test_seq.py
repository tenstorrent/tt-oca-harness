# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""AVSBus clock-gate proxy: the AVS_CFG window answers ungated and stops when gated.

The proof is a two-sided, same-run experiment on one variable
(``CLOCK_GATE_CONTROL.AVS_CG_EN``):

* **Positive control** -- with the gate CLEARED, all three AVS_CFG windows must
  COMPLETE, and their real round-trip latency is *measured* here rather than
  assumed ([NEGATIVE-NEEDS-POSITIVE-CONTROL]).
* **Negative leg** -- with the gate SET, the same three reads must fail to
  answer within a bound DERIVED from that measurement
  (``_GATED_BOUND_FACTOR`` x the slowest healthy round-trip, floored at
  ``_MIN_GATED_BOUND_NS``). A fixed bound shorter than a healthy CSR round-trip
  would hold on a fully awake AVSBus -- it would measure latency, not decode
  ([NO-ALWAYS-PASS-CHECKER]) -- which is why the bound is measured, and why the
  same-bound ungated control below shows a responsive window satisfies it.

Nothing here asserts the sequence's own access counters: reachability is
carried by ``assert_reachable_or_gated`` (scoreboard cross-check) and the value
compares by the scoreboard's own ``sys_axi_value_checks_seen`` tally.
"""

from __future__ import annotations

import cocotb
from cocotb.utils import get_sim_time

from .smc_addr_map import smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

# Resolved from the generated map, so the offset within SMC_BASE_CONFIG follows
# the RDL rather than a literal that has to be re-checked by hand.
CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")
AVS_CG_EN = 1 << 10
AVSBUS_TIMEOUT_READS = [
    ("AVS_CFG_0", smc_addr("SMC_TOP_SMC_AVSBUS_CONTROLLER_AVS_CFG_0_BASE_ADDR")),
    ("AVS_CFG_1", smc_addr("SMC_TOP_SMC_AVSBUS_CONTROLLER_AVS_CFG_1_BASE_ADDR")),
    ("AVS_CONFIG", smc_addr("SMC_TOP_SMC_AVSBUS_CONTROLLER_AVS_CONFIG_BASE_ADDR")),
]

# Positive-control bound. Generous -- it exists only so a wedged
# bench cannot hang the shared CSR master; expiry is a FAILURE of the positive
# control (asserted below), never a pass ([TIMEOUT-MUST-FAIL]).
_UNGATED_PROBE_BOUND_NS = 4000
# The gated bound must sit well ABOVE the measured healthy round-trip, so that
# a responsive AVS slave answering at bench latency would NOT be scored as a
# timeout. Factor and floor are stated here, not buried at the call site.
_GATED_BOUND_FACTOR = 4
_MIN_GATED_BOUND_NS = 400

# Directed-stimulus floor. Composition: 7 CLOCK_GATE_CONTROL accesses (save,
# write + readback ungated, write + readback gated, restore write + readback)
# plus one read per AVS_CFG window in each of the three probe loops (3 x 3 = 9).
EXPECTED_ACCESSES = 16
# Value-checked reads: the ungated CLOCK_GATE_CONTROL readback, the gated
# readback, and the restore readback.
EXPECTED_VALUE_CHECKS = 3


class smc_avsbus_clock_config_proxy_test_seq(SmcCsrSeq):
    """AVS_CFG answers with AVS_CG_EN=0 and stops answering with AVS_CG_EN=1."""

    def __init__(self, name: str = "smc_avsbus_clock_config_proxy_test_seq") -> None:
        super().__init__(name)
        # Measured, published for the testcase-level gate / evidence token.
        self.ungated_latencies_ns: dict[str, int] = {}
        self.gated_bound_ns = None
        self.gated_timeouts = 0
        self.value_checks = 0
        # Windows that did NOT time out at the gated bound while ungated --
        # the same-mechanism control for the negative leg.
        self.ungated_same_bound_ok = 0
        # True if `gated_bound_ns` came from the measurement rather than the
        # floor. Reported in the evidence token, not asserted (see body()).
        self.bound_from_measurement = False

    async def body(self) -> None:
        original = await self.csr_read("CLOCK_GATE_CONTROL_SAVE", CLOCK_GATE_CONTROL)

        # ---- Positive control: gate CLEARED, the AVS_CFG windows must answer ----
        ungated = original & ~AVS_CG_EN
        await self.csr_write("CLOCK_GATE_CONTROL_AVS_OFF", CLOCK_GATE_CONTROL, ungated)
        await self.csr_read("CLOCK_GATE_CONTROL_AVS_OFF", CLOCK_GATE_CONTROL, expected=ungated)
        for name, addr in AVSBUS_TIMEOUT_READS:
            before = self.timeouts
            t0 = get_sim_time(units="ns")
            rdata = await self.csr_read_bounded(
                f"{name}_UNGATED", addr, timeout_ns=_UNGATED_PROBE_BOUND_NS
            )
            latency = int(get_sim_time(units="ns") - t0)
            assert self.timeouts == before, (
                f"{name}: the AVS_CFG window did NOT answer within "
                f"{_UNGATED_PROBE_BOUND_NS} ns with AVS_CG_EN cleared "
                f"(CLOCK_GATE_CONTROL=0x{ungated:x}). Without this positive "
                f"control the gated-leg timeout below is indistinguishable from "
                f"a window that never decodes at all."
            )
            self.ungated_latencies_ns[name] = latency
            cocotb.log.info(
                "AVS positive control: %s @ 0x%08x answered in %d ns "
                "(rdata=0x%x) with AVS_CG_EN cleared",
                name,
                addr,
                latency,
                rdata,
            )

        healthy_ns = max(self.ungated_latencies_ns.values())
        self.gated_bound_ns = max(_MIN_GATED_BOUND_NS, healthy_ns * _GATED_BOUND_FACTOR)
        # Record whether the bound came from the measurement or from the floor.
        # This is reported, NOT asserted: the floor dominating is not a defect
        # (a larger bound only makes the negative leg harder to satisfy), but
        # the `details` string claims the bound is "derived from that
        # measurement", so the log must say which branch actually produced it.
        self.bound_from_measurement = healthy_ns * _GATED_BOUND_FACTOR >= _MIN_GATED_BOUND_NS

        # ---- SAME-BOUND ungated control ------------------------------------
        # The gate is still CLEARED here. Arithmetic on the bound cannot
        # establish that a responsive AVSBus would not be scored as a timeout:
        # `gated_bound_ns` is `max(400, 4*healthy)`, so any compare of it
        # against `healthy` has no counterexample for a non-negative healthy and
        # could not fail on any RTL ([NO-ALWAYS-PASS-CHECKER]).
        #
        # That property IS checkable -- just not by arithmetic on the bound.
        # Here the same three addresses are read UNGATED with a neutral bounded
        # read (`csr_read_bounded`) set to exactly `gated_bound_ns`, the bound
        # the negative leg will use. If a responsive window cannot answer inside
        # that bound, the negative leg's timeouts would say nothing about clock
        # gating, and this loop fails.
        #
        # Note on the mechanism: `csr_short_timeout` cannot be used for this
        # control -- it asserts internally that the access DID expire ("completed
        # before the short timeout"), so it is not a neutral bounded read. That
        # same internal assert is also why the negative leg cannot silently pass
        # on a timeout helper that expires unconditionally; the negative leg's
        # own `assert self.timeouts == before + 1` restates what the helper has
        # already enforced.
        for name, addr in AVSBUS_TIMEOUT_READS:
            before = self.timeouts
            await self.csr_read_bounded(
                f"{name}_UNGATED_SAME_BOUND",
                addr,
                timeout_ns=self.gated_bound_ns,
            )
            assert self.timeouts == before, (
                f"{name}: did NOT answer within the gated-leg bound "
                f"({self.gated_bound_ns} ns) while AVS_CG_EN was still CLEARED "
                f"(CLOCK_GATE_CONTROL=0x{ungated:x}, slowest healthy round-trip "
                f"measured {self.ungated_latencies_ns[name]} ns). The bound is "
                f"too tight to be satisfied by a responsive window, so a "
                f"timeout in the gated leg below would not be attributable to "
                f"clock gating."
            )
            self.ungated_same_bound_ok += 1

        # ---- Negative leg: gate SET, the same three reads must NOT answer ----
        enabled = original | AVS_CG_EN
        await self.csr_write("CLOCK_GATE_CONTROL_AVS_EN", CLOCK_GATE_CONTROL, enabled)
        await self.csr_read("CLOCK_GATE_CONTROL_AVS_EN", CLOCK_GATE_CONTROL, expected=enabled)
        for name, addr in AVSBUS_TIMEOUT_READS:
            before = self.timeouts
            await self.csr_short_timeout(name, addr, timeout_ns=self.gated_bound_ns)
            assert self.timeouts == before + 1
            self.gated_timeouts += 1

        await self.csr_write("CLOCK_GATE_CONTROL_RESTORE", CLOCK_GATE_CONTROL, original)
        await self.csr_read("CLOCK_GATE_CONTROL_RESTORE", CLOCK_GATE_CONTROL, expected=original)

        # ---- Reconciliation against the scoreboard, not against self-counts ----
        self.assert_reachable_or_gated(
            EXPECTED_ACCESSES,
            "AVSBUS_CLOCK_CONFIG",
            "AVS block clock-gated by this test",
        )
        sb = self.env.scoreboard
        self.value_checks = sb.sys_axi_value_checks_seen
        assert self.value_checks >= EXPECTED_VALUE_CHECKS, (
            f"expected {EXPECTED_VALUE_CHECKS} value-checked SEP_IN AXI reads "
            f"(AVS_CG_EN cleared / set / restored readbacks), scoreboard saw "
            f"{self.value_checks}"
        )
        assert self.gated_timeouts == len(AVSBUS_TIMEOUT_READS), (
            f"{self.gated_timeouts} of {len(AVSBUS_TIMEOUT_READS)} AVS_CFG "
            f"windows stopped answering while gated"
        )
        cocotb.log.info(
            "CHK-AVSBUS-CG: AVS_CG_EN=0 -> all %d AVS_CFG window(s) answered "
            "(latencies %s ns, slowest %d ns); AVS_CG_EN=1 -> all %d stopped "
            "answering within a bound of %d ns (= max(%d, %d x %d)); "
            "CLOCK_GATE_CONTROL 0x%x -> 0x%x -> 0x%x readback-checked; "
            "scoreboard value_checks=%d (>= %d)",
            len(AVSBUS_TIMEOUT_READS),
            ",".join(f"{n}={self.ungated_latencies_ns[n]}" for n, _ in AVSBUS_TIMEOUT_READS),
            healthy_ns,
            self.gated_timeouts,
            self.gated_bound_ns,
            _MIN_GATED_BOUND_NS,
            _GATED_BOUND_FACTOR,
            healthy_ns,
            ungated,
            enabled,
            original,
            self.value_checks,
            EXPECTED_VALUE_CHECKS,
        )
