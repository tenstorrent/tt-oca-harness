<!-- SPDX-License-Identifier: Apache-2.0 -->
# CPU AXI-isolate forced-reset recovery

This note records the problem, behavior, limits, and directed tests for the
SMC CPU reset-timeout recovery change. It is implementation and test context,
not a software interface specification.

## Problem

The SMC CPU boundary contains two `axi_isolate` instances in
`smc_4core_cpu.sv`:

| Instance | Traffic direction | Behavior while isolated |
| --- | --- | --- |
| MMIO | CPU to fabric | New transactions receive an error response |
| L2 frontend | Fabric to CPU | New transactions remain blocked |

The isolates use `rst_primary`, not the CPU core or uncore reset. This lets
them separate the CPU from live fabric before the CPU is reset.

Normally, an isolate enters `Drain`, stops accepting new addresses, and waits
for every accepted transaction to finish. Its pending write count falls on a
B response, its pending read count falls on the last R beat, and its pending W
count falls on the last accepted W beat.

If `CPU_CTRL.RESET_TIMEOUT` expires with `timeout_mode=1`, the reset must be
applied even when draining has not completed. The reset CPU can forget an
outstanding transaction and stop accepting or producing the beat needed to
clear a pending count. Before this change, the isolate could then remain in
`Drain`, `drained_o` would remain low, and the CPU AXI paths would not reopen.

## Recovery behavior

`smc_cpu_ctrl_wrap` drives `isolate_flush_o` when a software reset request is
pending, the timeout has fired, and force mode is enabled. Both CPU isolates
receive this signal as `flush_i`.

`axi_isolate` latches the pulse into a recovery window. The window remains
active while isolation is requested and closes when `isolate_i` deasserts.
This matters because the timeout pulse can end before a late response or W
beat arrives.

During the recovery window, the isolate:

1. Clears each safe pending count and moves its AW and AR state machines to
   `Isolate`.
2. Accepts and hides late B and R responses so they can clear routing state
   without reaching the reset side.
3. Ignores counter decrements at zero, preventing late responses from
   underflowing a cleared count and breaking a later drain.
4. Accepts orphaned W beats without forwarding them after their pending count
   has been cleared. This lets upstream write routing reach the burst's last
   beat and close.

The response absorber is above the terminating demux inside `axi_isolate`.
Therefore, a late response can also release that demux's ID tracking rather
than remaining parked inside the isolate.

## Safety boundary

The flush does not withdraw an AW, W, or AR beat that is already presented to
the receiving side and waiting for `ready`. The `flush_aw_ok`, `flush_w_ok`,
and `flush_ar_ok` checks defer that channel's clear until the beat is
accepted. The latched recovery window applies the clear automatically if the
beat is accepted later.

Withdrawing a presented request would violate AXI and could corrupt live
routing state. Consequently, the flush can complete isolate bookkeeping, but
it cannot repair every dead endpoint or every fabric entry outside the
isolate.

## Recovery cases and limits

| Path | Scenario | Result |
| --- | --- | --- |
| MMIO | CPU stops accepting a response; fabric is healthy | **Recovers.** The isolate absorbs the response, clears its pending count, and completes the reset drain. |
| MMIO | Fabric returns B/R after the timeout reset | **Recovers when the response arrives.** The recovery window absorbs the late response and releases its routing state. |
| MMIO | Fabric never returns B/R | **Partially recovers.** The isolate and reset handshake complete, but fabric routing toward the dead endpoint remains occupied because no response clears it. |
| MMIO | Fabric never accepts a presented AW/AR | **Does not recover.** The channel remains in `Hold`; clearing it would retract an AXI request that is already presented. |
| L2 | Fabric-side master stops accepting B/R | **Partially recovers.** The isolate and reset handshake complete, but the issuing master must discard or otherwise resolve its stale transaction. |
| L2 | CPU accepts a request but never produces B/R | **Partially recovers.** The isolate clears its count, but the issuing master and fabric can remain blocked waiting for the missing response. |
| L2 | CPU does not accept a presented AW/AR/W | **Does not recover if the beat is never accepted.** The flush remains pending to avoid retracting the request; it applies automatically if the CPU later accepts the beat. |
| L2 | A W burst stops before its last beat | **Partially recovers if reset is already requested.** The reset can complete, but upstream W routing remains occupied until the remaining beats, including `last`, arrive. |

For a response that never arrives, a downstream demux can continue tracking
the transaction by AXI ID. Later traffic using that ID may remain blocked,
especially if it targets a different destination. Read and write tracking are
separate, so a dead read does not necessarily block writes, and vice versa.
Only the missing response or a reset that also covers the affected endpoint
and fabric state can clear this residual.

For a request held valid without `ready`, recovery is intentionally deferred.
There is no protocol-safe way for the isolate to make the receiving endpoint
accept the request.

## Harness tests

The shared scenarios are implemented in
`smc_cpu_isolate_flush_test_seq.py`. Four directed test leaves are retained
for DV review:

| Test | Wedge | Post-reset proof |
| --- | --- | --- |
| `smc_cpu_l2_read_wedge_test` | Holds L2 R responses at SEP_IN while reads remain pending | Discards the stale testbench responses, reopens the isolate, and completes a fresh L2 read |
| `smc_cpu_l2_write_wedge_test` | Starts the reset request, accepts a later L2 AW, and withholds that transaction's W beats | Releases and absorbs the late W beats, then completes an L2 write and checked readback |
| `smc_cpu_mmio_read_wedge_test` | Firmware issues a SYS_OUT read whose R response is held | Absorbs the released stale response, reboots firmware, repeats the external read, and reads through the front port |
| `smc_cpu_mmio_write_wedge_test` | Firmware issues a SYS_OUT write whose B response is held | Absorbs the released stale response, reboots firmware, completes and checks a new external write, and reads through the front port |

Every test also checks that:

- the relevant pending count is nonzero before the timeout;
- reset remains withheld before the timeout;
- force mode applies the reset and clears the pending count;
- the isolate reports drained while the original traffic is still blocked;
- cleared counts remain at zero while stale traffic is consumed; and
- the recovery window closes when isolation is released.

The L2 read test explicitly drops stale R responses from the testbench's
SEP_IN and SYS_IN views before issuing its fresh read. This models coordinated
cleanup by the fabric-side master; the RTL flush alone does not repair a
master that continues waiting for a response that was discarded during reset.

The L2 write test requests reset before creating its partial-W wedge. It
therefore verifies late-W cleanup after a reset is already in flight, not the
case where an earlier incomplete burst prevents the reset-control write from
reaching `cpu_ctrl`.

The leaves remain individually selectable from `cpu.toml`, but are not members
of `all`, `hosted`, `smoke`, or any dedicated group. No scheduled regression
runs them pending DV review and approval.

The MMIO tests require the `mmio_wedge` firmware image and therefore require
the SMC DV firmware toolchain setup described in `hw/sys/smc/dv/README.md`.

The companion `tt-axi` block bench contains standalone `axi_isolate` recovery
tests for late responses, late W data, deferred clears, and the dead-endpoint
limits. This harness note does not record a fixed pass count because results
must be taken from the run associated with the RTL under review.
