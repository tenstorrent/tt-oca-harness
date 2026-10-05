# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP_IN flow control: outstanding transactions against ready-side backpressure.

AXI channels handshake independently and transactions are pipelined, so a
manager may present the next address while the subordinate is still answering
earlier ones, and it may hold BREADY or RREADY low for as long as it likes.
Two AMBA IHI 0022 rules are what make that safe, and both are checked here:

* A transfer starts when VALID is asserted and only completes when READY is
  also asserted; VALID may not be withdrawn before that, and the payload of the
  channel must stay stable across the wait (A3.2.1). The B and R channels are
  driven by the design, so their stability under the manager's backpressure is
  the design's obligation.
* Every issued transaction is answered with the data of the address it was
  issued for, and same-address writes take effect in the order they were
  issued. Three passes over eight scratch registers go out in one outstanding
  write group, each pass carrying its own word; the individual readbacks must
  show the last pass, and four further passes in one outstanding read group
  must return the same word every time. A fabric that dropped, merged,
  reordered or mis-routed one of the pipelined accesses returns the wrong word
  for that address.

The stall counts are also asserted non-zero. They are not the claim -- they are
the measurement that the backpressure this sequence is named for actually
happened, so a run in which the profile stopped reaching the bus fails instead
of passing on traffic that never stalled.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ReadOnly, RisingEdge
from env.smc_sys_axi_agent import SmcSysAxiGroupItem, SmcSysAxiItem, SmcSysAxiOp
from ocah_axi_vip import AxiTimingProfile

from .smc_addr_map import smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq

SCRATCH_COLD_0 = smc_indexed_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_SCRATCH_BASE_ADDR", 0)
SCRATCH_STRIDE = 4
# SCRATCH_COLD has eight registers (smc_reg.py: SCRATCH_COLD_SCRATCH_0..7).
SCRATCH_COUNT = 8
# Passes over the eight registers inside one outstanding group. Each write pass
# carries its own value, so the readback also shows the writes to one address
# completed in the order they were issued; the read passes repeat the same
# expectation from deeper in the pipeline.
WRITE_PASSES = 3
READ_PASSES = 4

# Cycles the manager holds the response channel's READY low. Long enough that
# the group is still outstanding when the window closes, short enough that it
# then drains well inside the access timeout.
READY_HOLD_CYCLES = 64


def scratch_addr(index: int) -> int:
    return SCRATCH_COLD_0 + index * SCRATCH_STRIDE


def scratch_pattern(index: int, write_pass: int = WRITE_PASSES - 1) -> int:
    """Word for one register on one write pass: distinct in both."""
    return 0xC0DE_0000 | (write_pass << 16) | (index << 8) | (0xF0 ^ index)


EXPECTED_ACCESSES = SCRATCH_COUNT * (WRITE_PASSES + READ_PASSES + 2)
# Every read of the sequence carries an expectation, so the scoreboard compares
# both the individual readbacks and the pipelined read group.
MIN_VALUE_CHECKS = SCRATCH_COUNT * (READ_PASSES + 1)


class _ChannelWatch:
    """Clocked observer of the SEP_IN handshake and response-payload stability.

    Counts the cycles each channel spent stalled (VALID high, READY low) and
    records every cycle in which the design withdrew BVALID/RVALID, or changed
    a response payload, while the manager was holding READY low.
    """

    _B_PAYLOAD = ("s_axi_bresp", "s_axi_bid")
    _R_PAYLOAD = ("s_axi_rdata", "s_axi_rresp", "s_axi_rlast", "s_axi_rid")

    def __init__(self, dut) -> None:
        self.dut = dut
        self.stop = False
        self.stalls = {"aw": 0, "ar": 0, "b": 0, "r": 0}
        self.violations: list[str] = []

    def _read(self, name: str) -> int | None:
        value = getattr(self.dut, name).value
        return int(value) if value.is_resolvable else None

    def _payload(self, names) -> tuple:
        return tuple(self._read(name) for name in names)

    async def run(self) -> None:
        held_b: tuple | None = None
        held_r: tuple | None = None
        while not self.stop:
            await RisingEdge(self.dut.clk_smc_i)
            await ReadOnly()
            state = {}
            for channel in ("aw", "ar", "b", "r"):
                valid = self._read(f"s_axi_{channel}valid")
                ready = self._read(f"s_axi_{channel}ready")
                state[channel] = (valid, ready)
                if valid == 1 and ready == 0:
                    self.stalls[channel] += 1

            held_b = self._check_hold("B", state["b"], held_b, self._B_PAYLOAD)
            held_r = self._check_hold("R", state["r"], held_r, self._R_PAYLOAD)

    def _check_hold(self, label, state, held, payload_names):
        """Enforce VALID-held and payload-stable across a READY-low wait."""
        valid, ready = state
        if held is not None:
            if valid != 1:
                self.violations.append(
                    f"{label}VALID was withdrawn while {label}READY was low (payload held {held})"
                )
                return None
            now = self._payload(payload_names)
            if now != held:
                self.violations.append(
                    f"{label} payload changed while {label}READY was low: {held} -> {now}"
                )
                return now
        if valid == 1 and ready == 0:
            return self._payload(payload_names)
        return None


class smc_sep_in_axi_flow_control_test_seq(SmcCsrSeq):
    """Outstanding writes and reads against B and R backpressure."""

    def __init__(self, name: str = "smc_sep_in_axi_flow_control_test_seq") -> None:
        super().__init__(name)
        self.value_checks: int | None = None
        self.stalls: dict[str, int] | None = None
        self.violations: list[str] = []

    def _access(
        self, label: str, op: SmcSysAxiOp, addr: int, *, wdata: int = 0, expected: int | None = None
    ) -> SmcSysAxiItem:
        item = SmcSysAxiItem(f"{op.value}_{label}")
        item.op = op
        item.addr = addr
        item.wdata = wdata
        item.expected = expected
        return item

    async def _group(self, name: str, items: list[SmcSysAxiItem], timing) -> None:
        group = SmcSysAxiGroupItem(name, items, timing=timing)
        await self.start_item(group)
        await self.finish_item(group)
        self.accesses += len(items)

    async def body(self) -> None:
        await self.wait_fuse_sense_done()
        dut = cocotb.top
        watch = _ChannelWatch(dut)
        watcher = cocotb.start_soon(watch.run())

        await self._group(
            "pipelined_writes",
            [
                self._access(
                    f"scratch{i}_pass{p}",
                    SmcSysAxiOp.WRITE,
                    scratch_addr(i),
                    wdata=scratch_pattern(i, p),
                )
                for p in range(WRITE_PASSES)
                for i in range(SCRATCH_COUNT)
            ],
            AxiTimingProfile(b_ready_delay=READY_HOLD_CYCLES),
        )
        for i in range(SCRATCH_COUNT):
            await self.csr_read(f"SCRATCH_COLD_{i}", scratch_addr(i), expected=scratch_pattern(i))

        await self._group(
            "pipelined_reads",
            [
                self._access(
                    f"scratch{i}_pass{p}",
                    SmcSysAxiOp.READ,
                    scratch_addr(i),
                    expected=scratch_pattern(i),
                )
                for p in range(READ_PASSES)
                for i in range(SCRATCH_COUNT)
            ],
            AxiTimingProfile(r_ready_delay=READY_HOLD_CYCLES),
        )

        for i in range(SCRATCH_COUNT):
            await self.csr_write(f"SCRATCH_COLD_{i}_RESTORE", scratch_addr(i), 0)

        watch.stop = True
        await RisingEdge(dut.clk_smc_i)
        await watcher

        self.stalls = dict(watch.stalls)
        self.violations = list(watch.violations)
        self.value_checks = self.env.scoreboard.sys_axi_value_checks_seen
        self.assert_all_reachable(EXPECTED_ACCESSES, "SEP_IN flow control")

        assert not self.violations, (
            "SEP_IN response channel broke the AXI handshake rule while the "
            f"manager held READY low: {self.violations[:4]}"
        )
        stalled = {name: count for name, count in self.stalls.items() if count == 0}
        assert not stalled, (
            f"no stall was observed on SEP_IN channel(s) {sorted(stalled)}, so the "
            f"outstanding-transaction and backpressure stimulus this sequence is "
            f"built on never reached the bus (counts {self.stalls})"
        )
        cocotb.log.info(
            "CHK-SEP-IN-FLOW-CONTROL: %d outstanding writes and %d outstanding reads across "
            "SCRATCH_COLD_0..%d completed with every word matching its address and the last "
            "write to each address winning, under %d-cycle B/R READY holds; stalled cycles "
            "aw=%d ar=%d b=%d r=%d",
            SCRATCH_COUNT * WRITE_PASSES,
            SCRATCH_COUNT * READ_PASSES,
            SCRATCH_COUNT - 1,
            READY_HOLD_CYCLES,
            self.stalls["aw"],
            self.stalls["ar"],
            self.stalls["b"],
            self.stalls["r"],
        )
        cocotb.log.info(
            "CHK-SEP-IN-RESP-STABLE: BVALID/RVALID stayed asserted and BRESP/BID and "
            "RDATA/RRESP/RLAST/RID stayed stable across every READY-low cycle "
            "(%d B and %d R stalled cycles observed, 0 violations)",
            self.stalls["b"],
            self.stalls["r"],
        )
