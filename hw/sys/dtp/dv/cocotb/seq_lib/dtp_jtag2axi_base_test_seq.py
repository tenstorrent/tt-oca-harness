# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""JTAG2AXI helper base sequence for DTP tests."""

from __future__ import annotations

import dataclasses
import random
from dataclasses import dataclass

import cocotb
from cocotb.triggers import ClockCycles, ReadOnly
from env.dtp_axi_port_history import DtpAxiPortHistory
from env.dtp_jtag_item import DtpJtagItem, DtpJtagOp
from env.dtp_tap_device import unpack_jtag2axi_caps
from env.dtp_types import (
    GATE_TDR_CHECK_ID,
    JTAG2AXI_TARGETS,
    MEM_IMAGE_CHECK_ID,
    RESET_COUNT_CHECK_ID,
    SMC_DBG_AXSIZE_8B,
    DtpJtag2AxiOp,
    DtpJtag2AxiStatus,
    DtpJtagInstr,
    DtpTapState,
    get_jtag2axi_target,
    pack_series_ctrl,
    pack_series_data,
    pack_single_op,
    unpack_series_ctrl,
    unpack_series_data,
    unpack_single_op,
    unpack_single_op_fields,
)
from ocah_jtag_vip import OcahJtagChecker
from ocah_lib import OcahKnobs

from .dtp_base_test_seq import dtp_base_test_seq

AXI_MEM_SIZE = 2**16
AXI_BEAT_BYTES = 8
GEOMETRY_CHECK_ID = "CHK-J2A-GEOMETRY"
STATUS_BIT_CHECK_ID = "CHK-J2A-STATUS-BIT"
ERR_RDATA_CHECK_ID = "CHK-J2A-ERR-RDATA"
SERIES_ADDR_CHECK_ID = "CHK-J2A-SERIES-ADDR"
BUS_REQ_CHECK_ID = "CHK-J2A-BUS-REQ"
BLOCKED_CHECK_ID = "CHK-AXI-BLOCKED"
STATUS_BIT_NEGATIVE_KNOB = "DTP_J2A_STATUS_BIT_NEGATIVE"
BUS_REQ_NEGATIVE_KNOB = "DTP_J2A_BUS_REQ_NEGATIVE"
# System cycles a launched bridge transaction has to complete on its port.
PORT_COMPLETION_CYCLES = 200
AXI_RESP_SLVERR = 2
AXI_RESP_DECERR = 3
# Increment flag per beat of the WITH_ERROR_STATUS streams: the second beat
# re-writes the held address.
SERIES_STATUS_INCREMENTS = (1, 0, 1, 1)
# TCK cycles for a bridge's state machine to return to idle after a response,
# and for a released bridge to put a queued request on the bus.
QUEUE_DROP_TCK = 32


@dataclass(frozen=True)
class DtpSeriesStatusPlan:
    """One WITH_ERROR_STATUS series: its geometry and the beat that carries the fault.

    The status bit a shift returns belongs to the previous beat, so
    ``expected_status_bit(shift)`` is 1 only for the shift after the fault
    beat; ``fault_idx`` is ``None`` for a clean stream.
    """

    target: str
    base: int
    size: int
    stride: int
    increments: tuple[int, ...]
    fault_idx: int | None
    expected: DtpJtag2AxiStatus

    @property
    def beats(self) -> int:
        return len(self.increments)

    def addr(self, idx: int) -> int:
        return self.base + self.stride * sum(self.increments[:idx])

    @property
    def final_addr(self) -> int:
        return self.addr(self.beats)

    @property
    def span(self) -> int:
        """Bytes from ``base`` through the slot the trailing shift touches."""
        return self.final_addr - self.base + self.stride

    @property
    def fault_addr(self) -> int:
        if self.fault_idx is None:
            raise ValueError("a clean stream has no fault beat")
        return self.addr(self.fault_idx)

    def is_fault(self, idx: int) -> bool:
        return self.fault_idx is not None and idx == self.fault_idx

    def expected_status_bit(self, shift: int) -> int:
        return int(self.is_fault(shift - 1))

    def beat_resp_name(self, idx: int) -> str:
        return self.expected.name if self.is_fault(idx) else "OKAY"

    def first_visit_beats(self) -> tuple[int, ...]:
        """Beats whose address no earlier beat touched; a one-shot fault fires on the first access."""
        seen: set[int] = set()
        first: list[int] = []
        for idx in range(self.beats):
            if self.addr(idx) not in seen:
                seen.add(self.addr(idx))
                first.append(idx)
        return tuple(first)

    def final_words(self, words: list[int]) -> list[int]:
        """The word each beat's address holds after the stream: the last one written there."""
        last: dict[int, int] = {}
        for idx, data in enumerate(words):
            last[self.addr(idx)] = data
        return [last[self.addr(idx)] for idx in range(self.beats)]


@dataclass
class DtpBusLedger:
    """The port counts that the judged operations of a ledgered pass add up to."""

    target: str
    writes: int
    reads: int
    # (writes, reads) of every other bridge port when the pass opened.
    others: dict[str, tuple[int, int]]

    def count(self, *, read: bool) -> int:
        return self.reads if read else self.writes

    def account(self, *, read: bool) -> tuple[int, int]:
        """Add one transaction of the operation's direction; returns (writes, reads)."""
        if read:
            self.reads += 1
        else:
            self.writes += 1
        return self.writes, self.reads


class dtp_jtag2axi_base_test_seq(dtp_base_test_seq):
    """Helpers for DTP JTAG2AXI single-operation and series-operation tests."""

    _bus_ledger: DtpBusLedger | None = None

    async def pre_body(self) -> None:
        """Gate every pass on the DUT publishing the geometry the DV table holds."""
        await super().pre_body()
        await self.verify_bridge_geometry()
        self.open_bus_ledger()

    async def post_body(self) -> None:
        await super().post_body()
        self.close_bus_ledger()

    async def verify_bridge_geometry(self) -> None:
        """Compare each bridge's ``*_JTAG2AXI_CAPS`` fields with ``JTAG2AXI_TARGETS``.

        Records ``CHK-J2A-GEOMETRY`` per bridge and fails the pass on a mismatch,
        before any bridge request is packed with the table's field widths.
        ``DTP_J2A_GEOMETRY_NEGATIVE=1`` corrupts the expected address size so the
        run must FAIL, proving the gate rejects a wrong table end to end.
        """
        checker = OcahJtagChecker(
            name=f"{self.get_name()}.geometry",
            raise_on_error=False,
            required_ids={GEOMETRY_CHECK_ID},
            logger=cocotb.log,
        )
        negative = OcahKnobs.is_set("DTP_J2A_GEOMETRY_NEGATIVE")
        if negative:
            self.log.warning("NEGATIVE VALIDATION: geometry gate expectations will be corrupted")
        await self.reset_tap()
        for cfg in JTAG2AXI_TARGETS.values():
            value = await self.read_tdr(cfg.caps_reg)
            observed = unpack_jtag2axi_caps(value)
            self.log.info(
                "GEOMETRY %s raw=0x%04x bus_type=%d addr_size=%d data_size=%d wr_pl=%d rd_pl=%d",
                cfg.caps_reg,
                value,
                observed["bus_type"],
                observed["addr_size"],
                observed["data_size"],
                observed["wr_pl_depth"],
                observed["rd_pl_depth"],
            )
            checker.expect_equal(
                GEOMETRY_CHECK_ID,
                (
                    observed["bus_type"],
                    observed["addr_size"],
                    observed["data_size"],
                    observed["wr_pl_depth"],
                    observed["rd_pl_depth"],
                ),
                (
                    cfg.bus_type,
                    cfg.addr_width ^ int(negative),
                    cfg.data_size,
                    cfg.wr_pl_depth,
                    cfg.rd_pl_depth,
                ),
                context=f"{cfg.caps_reg} (bus_type, addr_size, data_size, wr_pl_depth, rd_pl_depth)",
            )
        checker.finalize()

    async def jtag2axi_write(
        self,
        addr: int,
        data: int,
        wstrb: int = 0xFF,
        size: int = 3,
    ) -> DtpJtagItem:
        """Issue a JTAG2AXI SMC fabric single write; returns item with status."""
        return await self._send(
            op=DtpJtagOp.J2A_WRITE,
            axi_addr=addr,
            axi_data=data,
            axi_wstrb=wstrb,
            axi_size=size,
        )

    async def jtag2axi_read(self, addr: int, size: int = 3) -> DtpJtagItem:
        """Issue a JTAG2AXI SMC fabric single read; returns item with status+rdata."""
        return await self._send(op=DtpJtagOp.J2A_READ, axi_addr=addr, axi_size=size)

    # --- common data/address helpers -----------------------------------------
    @staticmethod
    def size_bytes(size: int) -> int:
        return 1 << size

    @staticmethod
    def data_mask(size: int) -> int:
        return (1 << (8 * (1 << size))) - 1

    @staticmethod
    def full_wstrb(size: int) -> int:
        return (1 << (1 << size)) - 1

    def aligned_addr(self, addr: int, size: int) -> int:
        """Align an address to the active transfer size."""
        align = self.size_bytes(size)
        return addr - (addr % align)

    def random_aligned_addr(self, rng, size: int) -> int:
        """Pick a 64-bit-beat-aligned address inside the SMC fabric responder window.

        The window bounds the low address bits only: a caller adds a
        size-aligned offset within the beat and ``random_upper_addr`` bits.
        """
        max_addr = AXI_MEM_SIZE - AXI_BEAT_BYTES
        return rng.randrange(0, (max_addr // AXI_BEAT_BYTES) + 1) * AXI_BEAT_BYTES

    def read_mem_int(self, addr: int, size: int) -> int:
        """Read the backdoor AXI RAM for the transfer size."""
        return self.read_target_mem_int("smc_axi", addr, size)

    def write_mem_int(self, addr: int, value: int, size: int) -> None:
        """Backdoor-preload the AXI RAM for read-side scenarios."""
        self.write_target_mem_int("smc_axi", addr, value, size)

    # --- shared-VIP AXI scoreboard glue ---------------------------------------
    @property
    def axi_scoreboard(self):
        """The shared OcahAxiScoreboard, or None when the test did not opt in."""
        return getattr(self.cfg, "axi_scoreboard", None)

    def target_evidence(self, target: str):
        """The recorder of the sequence's judgements of ``target``: the bridge's own
        checker when the test names per-bridge IDs, else the shared scoreboard or None."""
        checker = getattr(self.cfg, "axi_target_evidence", {}).get(target)
        return checker if checker is not None else self.axi_scoreboard

    def axi_model(self, target: str):
        """The shared OcahAxiRefModel for one JTAG2AXI target, or None."""
        return getattr(self.cfg, "axi_models", {}).get(target)

    def _mirror_model_preload(self, target: str, addr: int, payload: bytes) -> None:
        """Keep the reference model's shadow memory equal to backdoor preloads."""
        model = self.axi_model(target)
        if model is not None:
            model.write_bytes(addr, payload)

    async def scoreboard_expect_no_activity(
        self, target: str, cycles: int, *, context: str
    ) -> None:
        """Emit CHK-AXI-NOACT from tb pulse counters and monitor counters."""
        scoreboard = self.axi_scoreboard
        if scoreboard is None:
            return
        before = await self.target_activity_counts(target)
        monitor = getattr(self.cfg, "axi_monitors", {}).get(target)
        monitor_before = monitor.get_request_activity() if monitor else None
        await self.wait_sys_cycles(cycles)
        after = await self.target_activity_counts(target)
        scoreboard.expect_no_activity(
            before=before,
            after=after,
            context=f"{context} target={target} cycles={cycles} source=tb_pulse_counters",
        )
        if monitor_before is not None:
            scoreboard.expect_no_activity(
                before=monitor_before,
                after=monitor.get_request_activity(),
                context=f"{context} target={target} cycles={cycles} source=vip_monitor",
            )

    async def scoreboard_expect_no_activity_since(
        self, target: str, before: dict[str, int], *, context: str
    ) -> dict[str, int]:
        """Emit CHK-AXI-NOACT against a counter snapshot taken before the gated request.

        Returns the closing snapshot so a later window can start from it.
        """
        after = await self.target_activity_counts(target)
        self.log.info("%s %s activity before=%s after=%s", context, target, before, after)
        scoreboard = self.axi_scoreboard
        if scoreboard is not None:
            scoreboard.expect_no_activity(
                before=before,
                after=after,
                context=f"{context} target={target} source=tb_pulse_counters",
            )
        for key in ("aw", "w", "ar"):
            self.assert_equal(f"{context}.{key}_count", after[key], before[key])
        return after

    def scoreboard_begin_blocked(self, target: str) -> None:
        """Open a blocked window: any monitored item on the stream fails."""
        scoreboard = self.axi_scoreboard
        if scoreboard is not None:
            scoreboard.begin_blocked_window(stream=target)

    def scoreboard_end_blocked(
        self, target: str, *, context: str, check_id: str | None = None
    ) -> None:
        """Close a blocked window and emit zero-transaction evidence.

        ``check_id`` names the evidence ID; the scoreboard's default applies
        without one.
        """
        scoreboard = self.axi_scoreboard
        if scoreboard is None:
            return
        if check_id is None:
            scoreboard.end_blocked_window(stream=target, context=context)
        else:
            scoreboard.end_blocked_window(stream=target, check_id=check_id, context=context)

    def scoreboard_check_target_memory(
        self,
        target: str,
        addr: int,
        length: int,
        *,
        context: str,
        expected: bytes | None = None,
    ) -> None:
        """Emit CHK-AXI-WMEM: backdoor RAM bytes versus an expectation.

        Pass ``expected`` with intent-derived bytes (what the stimulus meant to
        write) for a non-circular check; without it the model shadow is used,
        which only proves RAM-vs-observed-bus consistency.
        """
        scoreboard = self.axi_scoreboard
        if scoreboard is None:
            return
        scoreboard.check_memory(
            dut_bytes=bytes(
                self.target_memory(target).read(self.target_slot(target, addr), length)
            ),
            address=addr,
            length=length,
            stream=target,
            context=context,
            expected=expected,
        )

    def check_target_word(
        self, target: str, addr: int, expected: int, *, size: int, context: str
    ) -> None:
        """CHK-AXI-WMEM: the subordinate word at ``addr`` equals ``expected``, taken from the stimulus."""
        nbytes = self.size_bytes(size)
        expected &= self.data_mask(size)
        self.scoreboard_check_target_memory(
            target, addr, nbytes, context=context, expected=expected.to_bytes(nbytes, "little")
        )
        self.assert_equal(
            context,
            self.read_target_mem_int(target, addr, size),
            expected,
            f"target={target} addr=0x{addr:x}",
        )

    def scoreboard_arm_strobes(self, target: str, wstrb: int, addr: int, *, context: str) -> None:
        """Arm the intent write strobes for the next observed write."""
        scoreboard = self.axi_scoreboard
        if scoreboard is None:
            return
        cfg = self.target_cfg(target)
        aligned = addr - (addr % cfg.beat_bytes)
        scoreboard.arm_expected_strobes(
            (wstrb,),
            address=aligned,
            stream=target,
            context=f"{context} target={target} source=stimulus-wstrb",
        )

    def scoreboard_expect_completion(
        self, target: str, status: int, *, context: str, polls: int = 16
    ) -> None:
        """Emit CHK-AXI-COMPLETION: the bridge left BUSY within the poll bound."""
        scoreboard = self.axi_scoreboard
        if scoreboard is None:
            return
        cfg = self.target_cfg(target)
        # Bound: `polls` status polls, each one wide TDR scan plus TAP navigation.
        bound_ns = polls * (cfg.single_op_len + 16) * self.cfg.jtag_period_ns
        scoreboard.expect_not_timed_out(
            "CHK-AXI-COMPLETION",
            timed_out=(int(status) == int(DtpJtag2AxiStatus.BUSY_OR_FULL)),
            timeout_ns=float(bound_ns),
            context=f"{context} target={target} polls={polls}",
        )

    def check_reset_counted(self, counter: str, before: int, after: int, context: str) -> None:
        """``CHK-RESET-COUNT`` on the shared AXI scoreboard, or the base
        assertion when the test attaches none."""
        scoreboard = self.axi_scoreboard
        if scoreboard is None:
            super().check_reset_counted(counter, before, after, context)
            return
        scoreboard.expect_equal(
            RESET_COUNT_CHECK_ID,
            after - before,
            1,
            context=f"{counter} before={before} after={after} {context}",
        )

    # --- per-operation bus-request ledger (CHK-J2A-BUS-REQ) --------------------
    def bus_ledger_target(self) -> str | None:
        """The bridge whose port this scenario's ledger accounts; None keeps it closed."""
        return None

    def port_history(self, target: str) -> DtpAxiPortHistory:
        """The completed-transaction history of the port behind ``target``."""
        history = getattr(self.cfg, "axi_port_histories", {}).get(target)
        assert history is not None, f"{target} port history is not ready (no AXI scoreboard)"
        return history

    def open_bus_ledger(self) -> None:
        """Account the bridge ports for this pass when the test requires CHK-J2A-BUS-REQ.

        From the second pass on, every port's counts must equal those the
        previous pass closed with.
        """
        self._bus_ledger = None
        target = self.bus_ledger_target()
        if target is None or BUS_REQ_CHECK_ID not in self.cfg.axi_checker_required_ids:
            return
        writes, reads = self.port_history(target).counts()
        histories = self.cfg.axi_port_histories
        for name, history in histories.items():
            if history.mark is not None:
                self._check_bus_counts(name, history.mark, context="between_passes")
        others = {name: history.counts() for name, history in histories.items() if name != target}
        self._bus_ledger = DtpBusLedger(target=target, writes=writes, reads=reads, others=others)
        if OcahKnobs.is_set(BUS_REQ_NEGATIVE_KNOB):
            self.log.warning(
                "NEGATIVE VALIDATION: bus-request address expectations will be corrupted"
            )

    def close_bus_ledger(self) -> None:
        """No transaction reached the port after the pass's last judged operation.

        Every other bridge port holds the counts it opened the pass with.
        """
        ledger = self._bus_ledger
        if ledger is None:
            return
        for name, counts in {ledger.target: (ledger.writes, ledger.reads), **ledger.others}.items():
            self._check_bus_counts(name, counts, context="after_last_op")
            self.port_history(name).mark = counts
        self._bus_ledger = None

    def _check_bus_counts(self, target: str, expected: tuple[int, int], *, context: str) -> None:
        """Record the port's write and read counts against ``expected``; raise on a mismatch."""
        observed = self.port_history(target).counts()
        self._record_bus_fields(
            target,
            [("writes", observed[0], expected[0]), ("reads", observed[1], expected[1])],
            context=context,
        )

    def _record_bus_fields(
        self, target: str, fields: list[tuple[str, int, int]], *, context: str
    ) -> None:
        """Record every (field, observed, expected) under CHK-J2A-BUS-REQ, then raise on a mismatch."""
        scoreboard = self.axi_scoreboard
        if scoreboard is not None:
            for field, observed, expected in fields:
                scoreboard.expect_equal(
                    BUS_REQ_CHECK_ID,
                    observed,
                    expected,
                    context=f"{context} target={target} field={field}",
                )
        for field, observed, expected in fields:
            self.assert_equal(f"{context}.bus_{field}", observed, expected, f"target={target}")

    async def wait_port_completion(
        self,
        target: str,
        *,
        read: bool,
        above: int,
        timeout_cycles: int = PORT_COMPLETION_CYCLES,
    ) -> bool:
        """Wait until the port completes a transaction of one direction beyond ``above``.

        The monitor completes a write at its B and a read at its last R, so
        the transaction's effect on the subordinate is final, and the
        reference model and scoreboard consume it in the same publication: a
        one-shot fault or credit armed after the wait cannot land on it.
        Returns False when none completes within ``timeout_cycles`` system
        cycles.
        """
        history = self.port_history(target)
        for _ in range(timeout_cycles):
            if history.count(read=read) > above:
                return True
            await self.wait_sys_cycles(1)
        return history.count(read=read) > above

    @staticmethod
    def strobe_lane_mask(wstrb: int) -> int:
        """The data bits of the byte lanes ``wstrb`` enables."""
        return sum(0xFF << (8 * lane) for lane in range(8) if (wstrb >> lane) & 0x1)

    async def expect_bus_request(
        self,
        target: str,
        *,
        read: bool,
        addr: int,
        size: int,
        context: str,
        data: int = 0,
        wstrb: int = 0,
    ) -> None:
        """CHK-J2A-BUS-REQ: the operation just issued completed exactly one transaction, the one it requested.

        Against the stimulus: the port's exact write and read counts, the
        address over the full bridge width, a single beat, the AXI4 size, and
        for a write the strobes and the strobed data, ``data`` and ``wstrb``
        being the bus lanes the request drives. A no-op unless this pass's ledger
        accounts ``target``. ``DTP_J2A_BUS_REQ_NEGATIVE=1`` corrupts the
        expected address, so the run must fail.
        """
        ledger = self._bus_ledger
        if ledger is None or ledger.target != target:
            return
        await self.wait_port_completion(target, read=read, above=ledger.count(read=read))
        self._check_bus_counts(target, ledger.account(read=read), context=context)
        item = self.port_history(target).last(read=read)
        cfg = self.target_cfg(target)
        expected_addr = self.masked_addr(target, addr)
        if OcahKnobs.is_set(BUS_REQ_NEGATIVE_KNOB):
            expected_addr ^= 0x4
        fields = [("address", item.address, expected_addr), ("beats", item.beat_count, 1)]
        if cfg.bus_type == 0:  # AXI4; AXI4-Lite carries no AxSIZE
            fields.append(("size", item.size, size))
        if not read:
            lanes = self.strobe_lane_mask(wstrb)
            fields.append(("strobes", item.strobes[0] if item.strobes else -1, wstrb))
            fields.append(("data", item.first_data & lanes, data & lanes))
        self._record_bus_fields(target, fields, context=context)

    @staticmethod
    def target_cfg(target: str):
        return get_jtag2axi_target(target)

    def target_data_mask(self, target: str, size: int | None = None) -> int:
        cfg = self.target_cfg(target)
        bits = cfg.data_width if size is None else 8 * self.size_bytes(size)
        return (1 << bits) - 1

    def target_full_wstrb(self, target: str, size: int | None = None) -> int:
        cfg = self.target_cfg(target)
        strobe_bits = cfg.wstrb_bits if size is None else self.size_bytes(size)
        return (1 << strobe_bits) - 1

    def target_memory(self, target: str):
        cfg = self.target_cfg(target)
        memory = getattr(self.cfg, cfg.memory_attr)
        assert memory is not None, f"{cfg.memory_attr} is not ready"
        return memory

    def target_responder(self, target: str):
        responder = self.cfg.jtag2axi_responders.get(target)
        assert responder is not None, f"JTAG2AXI responder for {target} is not ready"
        return responder

    @staticmethod
    def axi_resp_to_jtag_status(resp: int) -> DtpJtag2AxiStatus:
        """Map AXI BRESP/RRESP encoding into the JTAG2AXI status field."""
        if int(resp) == 0:
            return DtpJtag2AxiStatus.SUCCESS
        if int(resp) == 2:
            return DtpJtag2AxiStatus.SLVERR
        if int(resp) == 3:
            return DtpJtag2AxiStatus.DECERR
        raise ValueError(f"unsupported AXI response for JTAG2AXI status: {resp}")

    def configure_target_error(
        self,
        target: str,
        addr: int,
        resp: int,
        *,
        read: bool = True,
        write: bool = True,
        arm: bool = True,
        err_rdata: int = 0,
    ) -> DtpJtag2AxiStatus:
        """Configure a one-shot target response error and return expected status.

        ``arm=False`` injects the responder error WITHOUT arming the reference
        model or a scoreboard credit — for gated attempts whose op must never
        reach the bus (an armed credit that is never consumed correctly fails
        CHK-AXI-CREDITS at finalization).

        The errored read beat answers ``err_rdata`` as its RDATA word.
        """
        cfg = self.target_cfg(target)
        aligned = addr - (addr % cfg.beat_bytes)
        self.log.info(
            "Configure %s error addr=0x%08x aligned=0x%08x resp=%d read=%d write=%d err_rdata=0x%x",
            target,
            addr,
            aligned,
            resp,
            read,
            write,
            err_rdata,
        )
        self.target_responder(target).inject_error(
            aligned, resp, read=read, write=write, rdata=err_rdata
        )
        if not arm:
            return self.axi_resp_to_jtag_status(resp)
        # Arm the shared reference model and scoreboard credit so the injected
        # non-OKAY is classified as EXPECTED. One credit covers
        # the single op; direction narrows when only one side is armed.
        # DTP_AXI_SCOREBOARD_NEGATIVE=1 is the documented negative-validation
        # hook: it arms the WRONG response so the run must FAIL,
        # proving the checker rejects a bad expectation end to end.
        armed_resp = int(resp)
        if OcahKnobs.is_set("DTP_AXI_SCOREBOARD_NEGATIVE"):
            armed_resp = 2 if armed_resp == 3 else 3
            self.log.warning(
                "NEGATIVE VALIDATION: arming resp=%d instead of injected resp=%d",
                armed_resp,
                int(resp),
            )
        model = self.axi_model(target)
        if model is not None:
            model.expect_error(aligned, armed_resp, read=read, write=write)
        scoreboard = self.axi_scoreboard
        if scoreboard is not None:
            direction = None if (read and write) else ("read" if read else "write")
            scoreboard.arm_expected_resp(
                armed_resp,
                address=aligned,
                direction=direction,
                stream=target,
                context=f"target={target} injected=0x{aligned:x}",
            )
        return self.axi_resp_to_jtag_status(resp)

    def clear_target_errors(self, target: str) -> None:
        self.target_responder(target).clear_errors()
        model = self.axi_model(target)
        if model is not None:
            model.clear_expected_errors()

    def configure_target_backpressure(
        self,
        target: str,
        *,
        channels: tuple[str, ...],
        stall_cycles: int,
    ) -> None:
        self.log.info(
            "Configure %s backpressure channels=%s stall_cycles=%d",
            target,
            channels,
            stall_cycles,
        )
        self.target_responder(target).enable_backpressure(
            channels=channels,
            stall_cycles=stall_cycles,
        )

    def clear_target_backpressure(self, target: str) -> None:
        self.target_responder(target).disable_backpressure()

    def arm_target_w_before_aw(self, target: str) -> None:
        """Arm the target's responder to accept the next write's W beat while its AW waits."""
        self.target_responder(target).arm_w_before_aw()

    def target_mem_size(self, target: str) -> int:
        return int(self.cfg.axi_mem_size if target == "smc_axi" else self.cfg.otp_axil_mem_size)

    def target_slot(self, target: str, addr: int) -> int:
        """The responder memory offset of ``addr``.

        Every responder stores an access at its address modulo its window.
        """
        return addr % self.target_mem_size(target)

    def masked_addr(self, target: str, addr: int) -> int:
        """``addr`` as the bridge's address field holds it."""
        return addr & ((1 << self.target_cfg(target).addr_width) - 1)

    def random_target_aligned_addr(self, target: str, rng, size: int | None = None) -> int:
        cfg = self.target_cfg(target)
        align = cfg.beat_bytes if size is None else max(cfg.beat_bytes, self.size_bytes(size))
        max_addr = self.target_mem_size(target) - align
        return rng.randrange(0, (max_addr // align) + 1) * align

    def random_upper_addr(self, target: str, rng) -> int:
        """Seeded address bits above the responder window, up to the bridge address width.

        The responder memory never sees them; ``CHK-J2A-BUS-REQ`` judges them
        on the bus.
        """
        shift = self.target_mem_size(target).bit_length() - 1
        return rng.getrandbits(self.target_cfg(target).addr_width - shift) << shift

    def random_series_base(self, target: str, rng, *, span: int, straddle: bool = False) -> int:
        """A seeded beat-aligned stream base with seeded address bits above the responder window.

        The stream's ``span`` bytes stay inside one window. With ``straddle``,
        a seeded half of the streams longer than a beat cross a window top
        instead, at least one beat past it: the series address carries out of
        the window bits through a seeded run of ones above them and stops
        below the bridge address width.
        """
        cfg = self.target_cfg(target)
        mem = self.target_mem_size(target)
        low = min(self.random_target_aligned_addr(target, rng), mem - span)
        upper = self.random_upper_addr(target, rng)
        if straddle and span > cfg.beat_bytes and rng.getrandbits(1):
            window_bits = mem.bit_length() - 1
            run = rng.randrange(cfg.addr_width - window_bits)
            upper = (upper | (((1 << run) - 1) << window_bits)) & ~(1 << (window_bits + run))
            low = mem - rng.randrange(1, span // cfg.beat_bytes) * cfg.beat_bytes
        return upper | low

    def random_distinct_word(self, rng, target: str, *avoid: int) -> int:
        """A seeded data-width word, nonzero and different from every ``avoid`` word.

        A capture that repeats an ``avoid`` word, or a data field a status
        poll cleared, cannot pass for it.
        """
        mask = self.target_data_mask(target)
        excluded = {0, *(int(word) & mask for word in avoid)}
        while True:
            word = rng.getrandbits(self.target_cfg(target).data_width)
            if word not in excluded:
                return word

    def read_target_mem_int(self, target: str, addr: int, size: int) -> int:
        return int.from_bytes(
            self.target_memory(target).read(self.target_slot(target, addr), self.size_bytes(size)),
            "little",
        )

    def write_target_mem_int(self, target: str, addr: int, value: int, size: int) -> None:
        """Backdoor-write the responder slot of ``addr``, mirrored into the model at ``addr`` itself."""
        payload = (value & self.data_mask(size)).to_bytes(self.size_bytes(size), "little")
        self.target_memory(target).write(self.target_slot(target, addr), payload)
        self._mirror_model_preload(target, addr, payload)

    # --- end-state byte image of a random write stream ---------------------------
    # Images are keyed by responder slot, so two writes whose addresses share
    # a slot land in one image byte, as they do in the responder.
    def snapshot_target_word(
        self, target: str, image: dict[int, int], addr: int, size: int
    ) -> None:
        """Record the bytes of the word at ``addr`` that the image lacks."""
        word = self.read_target_mem_int(target, addr, size)
        slot = self.target_slot(target, addr)
        for byte_idx in range(self.size_bytes(size)):
            image.setdefault(slot + byte_idx, (word >> (8 * byte_idx)) & 0xFF)

    def image_write(
        self, target: str, image: dict[int, int], addr: int, data: int, wstrb: int, size: int
    ) -> None:
        """Apply one write's enabled lanes to the byte image."""
        slot = self.target_slot(target, addr)
        for byte_idx in range(1 << size):
            if (wstrb >> byte_idx) & 0x1:
                image[slot + byte_idx] = (data >> (8 * byte_idx)) & 0xFF

    def check_memory_image(self, target: str, image: dict[int, int], *, context: str) -> None:
        """Emit CHK-J2A-MEM-IMAGE: every byte of ``image`` matches the responder memory.

        The image holds every lane a stream wrote at its last value and every
        untouched lane of a touched word at its prior value, so a write that
        landed on the wrong lane or disturbed a neighbour fails here.
        """
        mismatches = 0
        for addr in sorted(image):
            observed = self.read_target_mem_int(target, addr, 0)
            if observed != image[addr]:
                mismatches += 1
                self.log.error(
                    "%s: %s byte 0x%x holds 0x%02x, image 0x%02x",
                    context,
                    target,
                    addr,
                    observed,
                    image[addr],
                )
        detail = f"target={target} bytes={len(image)}"
        scoreboard = self.axi_scoreboard
        if scoreboard is not None:
            scoreboard.expect_equal(
                MEM_IMAGE_CHECK_ID, mismatches, 0, context=f"{context} {detail}"
            )
        self.assert_equal(f"{context}.mem_image", mismatches, 0, detail)

    def log_jtag2axi_op(
        self,
        context: str,
        *,
        addr: int,
        data: int = 0,
        size: int = SMC_DBG_AXSIZE_8B,
        wstrb: int = 0,
        status: int | None = None,
    ) -> None:
        """Log raw and decoded JTAG2AXI fields for failure replay."""
        status_text = "" if status is None else f" status={DtpJtag2AxiStatus(status).name}"
        self.log.info(
            "%s addr=0x%08x size=%d bytes=%d wstrb=0x%02x data=0x%x%s",
            context,
            addr,
            size,
            self.size_bytes(size),
            wstrb,
            data & self.data_mask(size),
            status_text,
        )

    def log_target_jtag2axi_op(
        self,
        target: str,
        context: str,
        *,
        addr: int,
        data: int = 0,
        size: int | None = None,
        wstrb: int = 0,
        status: int | None = None,
    ) -> None:
        cfg = self.target_cfg(target)
        size = cfg.default_size if size is None else size
        status_text = "" if status is None else f" status={DtpJtag2AxiStatus(status).name}"
        self.log.info(
            "%s target=%s addr=0x%08x size=%d bytes=%d wstrb=0x%02x data=0x%x%s",
            context,
            target,
            addr,
            size,
            self.size_bytes(size),
            wstrb,
            data & self.target_data_mask(target, size),
            status_text,
        )

    # --- checked single operations -------------------------------------------
    async def write_single_and_check(
        self,
        addr: int,
        data: int,
        *,
        size: int = SMC_DBG_AXSIZE_8B,
        wstrb: int | None = None,
        context: str = "single_write",
    ) -> DtpJtagItem:
        """Issue one single-op write and verify status plus enabled byte lanes.

        ``data`` and ``wstrb`` start at ``addr``; the request carries them on
        the bus lanes ``addr`` selects in the 64-bit beat.
        """
        wstrb = self.full_wstrb(size) if wstrb is None else wstrb
        data &= self.data_mask(size)
        lane = addr % AXI_BEAT_BYTES
        self.log_jtag2axi_op(context, addr=addr, data=data, size=size, wstrb=wstrb)
        self.scoreboard_arm_strobes("smc_axi", wstrb << lane, addr, context=context)
        item = await self.jtag2axi_write(addr, data << (8 * lane), wstrb=wstrb << lane, size=size)
        self.scoreboard_expect_completion("smc_axi", item.status, context=context)
        self.assert_equal(f"{context}.status", item.status, DtpJtag2AxiStatus.SUCCESS)
        await self.expect_bus_request(
            "smc_axi",
            read=False,
            addr=addr,
            size=size,
            context=context,
            data=data << (8 * lane),
            wstrb=wstrb << lane,
        )
        observed = self.read_mem_int(addr, size)
        for byte_idx in range(self.size_bytes(size)):
            if (wstrb >> byte_idx) & 0x1:
                exp = (data >> (8 * byte_idx)) & 0xFF
                obs = (observed >> (8 * byte_idx)) & 0xFF
                self.assert_equal(
                    f"{context}.byte{byte_idx}",
                    obs,
                    exp,
                    f"addr=0x{addr + byte_idx:x} wstrb=0x{wstrb:02x}",
                )
        return item

    async def read_single_and_check(
        self,
        addr: int,
        expected: int,
        *,
        size: int = SMC_DBG_AXSIZE_8B,
        context: str = "single_read",
    ) -> DtpJtagItem:
        """Issue one single-op read and verify status plus returned data.

        The data field returns the whole beat; the ``size`` bytes at
        ``addr`` sit on the lanes ``addr`` selects.
        """
        expected &= self.data_mask(size)
        self.log_jtag2axi_op(context, addr=addr, size=size)
        item = await self.jtag2axi_read(addr, size=size)
        self.scoreboard_expect_completion("smc_axi", item.status, context=context)
        self.assert_equal(f"{context}.status", item.status, DtpJtag2AxiStatus.SUCCESS)
        await self.expect_bus_request("smc_axi", read=True, addr=addr, size=size, context=context)
        self.assert_equal(
            f"{context}.rdata",
            (item.rdata >> (8 * (addr % AXI_BEAT_BYTES))) & self.data_mask(size),
            expected,
            f"addr=0x{addr:x} size={size}",
        )
        return item

    async def write_target_single_raw(
        self,
        target: str,
        op: DtpJtag2AxiOp,
        addr: int,
        *,
        data: int = 0,
        wstrb: int = 0,
        size: int | None = None,
        arm_strobes: bool = True,
    ) -> None:
        """Issue a target-specific SINGLE_OP without waiting for completion.

        ``arm_strobes=False`` skips the CHK-AXI-STRB intent credit — for gated
        attempts, which never reach the bus, and for writes the scenario
        aborts, which never complete there (an armed strobe credit that no
        observed write consumes fails CHK-AXI-CREDITS).
        """
        cfg = self.target_cfg(target)
        size = cfg.default_size if size is None else size
        if op == DtpJtag2AxiOp.WRITE and arm_strobes:
            # Intent strobes for CHK-AXI-STRB: the wstrb programmed into the
            # TDR is the stimulus truth the observed bus strobes must match.
            self.scoreboard_arm_strobes(target, wstrb, addr, context="single_op")
        value = pack_single_op(op, addr, data, wstrb=wstrb, size=size, target=cfg)
        await self.write_tdr(cfg.single_op_reg, value)

    async def scan_target_single_to_update_dr(
        self,
        target: str,
        op: DtpJtag2AxiOp,
        addr: int,
        *,
        data: int = 0,
        wstrb: int = 0,
        size: int | None = None,
    ) -> None:
        """Load the target's SINGLE_OP instruction and shift ``op`` in as raw TMS
        steps that stop with the TAP in Update-DR and TCK idle.

        The bridge latches the operation on the TCK edge that leaves Update-DR,
        so the caller's next TCK step is the edge that launches it. No stimulus
        intent is armed: the caller discards the operation before it reaches
        the bus.
        """
        cfg = self.target_cfg(target)
        size = cfg.default_size if size is None else size
        value = pack_single_op(op, addr, data, wstrb=wstrb, size=size, target=cfg)
        await self.load_ir(DtpJtagInstr[cfg.single_op_reg])
        for tms in (1, 0, 0):
            await self.tms_step(tms)
        for bit_idx in range(cfg.single_op_len):
            await self.tms_step(int(bit_idx == cfg.single_op_len - 1), tdi=(value >> bit_idx) & 1)
        item = await self.tms_step(1)
        self.assert_equal(
            f"{target}.single_op_held_in_update_dr", item.result, DtpTapState.UPDATE_DR
        )

    async def poll_target_single_status(self, target: str) -> tuple[int, int]:
        """Poll a target SINGLE_OP TDR until the bridge reports not-busy.

        Returns the settled status and read data; the log line counts the
        captures that read BUSY_OR_FULL before it, which at the bench's TCK
        ratio is usually none, since a scan outlasts the bus access.
        """
        cfg = self.target_cfg(target)
        status, rdata = DtpJtag2AxiStatus.BUSY_OR_FULL, 0
        busy_polls = 0
        for _ in range(16):
            raw = await self.read_tdr(cfg.single_op_reg)
            status, rdata = unpack_single_op(raw, target=cfg)
            if status != DtpJtag2AxiStatus.BUSY_OR_FULL:
                break
            busy_polls += 1
        self.log.info(
            "%s SINGLE_OP status=%s rdata=0x%x busy_polls=%d",
            target,
            DtpJtag2AxiStatus(status).name,
            rdata,
            busy_polls,
        )
        return status, rdata

    async def write_target_single_and_check(
        self,
        target: str,
        addr: int,
        data: int,
        *,
        size: int | None = None,
        wstrb: int | None = None,
        context: str = "single_write",
    ) -> tuple[int, int]:
        """Issue one target write and verify status plus enabled byte lanes.

        ``data`` and ``wstrb`` start at ``addr``; the request carries them on
        the bus lanes ``addr`` selects in the beat.
        """
        cfg = self.target_cfg(target)
        size = cfg.default_size if size is None else size
        wstrb = self.target_full_wstrb(target, size) if wstrb is None else wstrb
        data &= self.target_data_mask(target, size)
        lane = addr % cfg.beat_bytes
        self.log_target_jtag2axi_op(
            target,
            context,
            addr=addr,
            data=data,
            size=size,
            wstrb=wstrb,
        )
        await self.write_target_single_raw(
            target,
            DtpJtag2AxiOp.WRITE,
            addr,
            data=data << (8 * lane),
            wstrb=wstrb << lane,
            size=size,
        )
        return await self.finish_target_single_write(
            target, addr, data, size=size, wstrb=wstrb, context=context
        )

    async def finish_target_single_write(
        self,
        target: str,
        addr: int,
        data: int,
        *,
        size: int,
        wstrb: int,
        context: str,
    ) -> tuple[int, int]:
        """Poll an issued write to its settled status and judge SUCCESS plus the enabled byte lanes in memory.

        ``data`` and ``wstrb`` start at ``addr``, as the request placed them
        on the lanes ``addr`` selects.
        """
        cfg = self.target_cfg(target)
        data &= self.target_data_mask(target, size)
        lane = addr % cfg.beat_bytes
        status, rdata = await self.poll_target_single_status(target)
        self.scoreboard_expect_completion(target, status, context=context)
        self.assert_equal(f"{context}.status", status, DtpJtag2AxiStatus.SUCCESS)
        await self.expect_bus_request(
            target,
            read=False,
            addr=addr,
            size=size,
            context=context,
            data=data << (8 * lane),
            wstrb=wstrb << lane,
        )
        observed = self.read_target_mem_int(target, addr, size)
        for byte_idx in range(self.size_bytes(size)):
            if (wstrb >> byte_idx) & 0x1:
                exp = (data >> (8 * byte_idx)) & 0xFF
                obs = (observed >> (8 * byte_idx)) & 0xFF
                self.assert_equal(
                    f"{context}.byte{byte_idx}",
                    obs,
                    exp,
                    f"target={cfg.name} addr=0x{addr + byte_idx:x}",
                )
        return status, rdata

    async def read_target_single_and_check(
        self,
        target: str,
        addr: int,
        expected: int,
        *,
        size: int | None = None,
        context: str = "single_read",
    ) -> tuple[int, int]:
        """Issue one target read and verify status plus returned data."""
        cfg = self.target_cfg(target)
        size = cfg.default_size if size is None else size
        expected &= self.target_data_mask(target, size)
        self.log_target_jtag2axi_op(target, context, addr=addr, size=size)
        await self.write_target_single_raw(target, DtpJtag2AxiOp.READ, addr, size=size)
        return await self.finish_target_single_read(
            target, addr, expected, size=size, context=context
        )

    async def finish_target_single_read(
        self, target: str, addr: int, expected: int, *, size: int, context: str
    ) -> tuple[int, int]:
        """Poll an issued read to its settled status and judge SUCCESS plus the returned data.

        The data field returns the whole beat; the ``size`` bytes at ``addr``
        sit on the lanes ``addr`` selects.
        """
        cfg = self.target_cfg(target)
        status, rdata = await self.poll_target_single_status(target)
        self.scoreboard_expect_completion(target, status, context=context)
        self.assert_equal(f"{context}.status", status, DtpJtag2AxiStatus.SUCCESS)
        await self.expect_bus_request(target, read=True, addr=addr, size=size, context=context)
        self.assert_equal(
            f"{context}.rdata",
            (rdata >> (8 * (addr % cfg.beat_bytes))) & self.target_data_mask(target, size),
            expected,
            f"target={cfg.name} addr=0x{addr:x} size={size}",
        )
        return status, rdata

    async def write_neighbour_then_read(
        self, target: str, addr: int, rng: random.Random, *, context: str
    ) -> tuple[int, int, int]:
        """Write a seeded word at ``addr`` and another at the next beat, then read ``addr`` back.

        The neighbouring write leaves its word in the SINGLE_OP data field,
        which the read must replace with the word the bus returns. On the SMC
        fabric every operation is a JTAG item the DTP scoreboard judges.
        Returns the read's status and data field and the word written at
        ``addr``.
        """
        cfg = self.target_cfg(target)
        size = cfg.default_size
        data = self.random_distinct_word(rng, target)
        other = self.random_distinct_word(rng, target, data)
        for word_addr, word, label in (
            (addr, data, "write"),
            (addr + cfg.beat_bytes, other, "neighbour"),
        ):
            if target == "smc_axi":
                await self.write_single_and_check(
                    word_addr, word, size=size, context=f"{context}.{label}"
                )
            else:
                await self.write_target_single_and_check(
                    target, word_addr, word, context=f"{context}.{label}"
                )
            self.check_target_word(
                target, word_addr, word, size=size, context=f"{context}.{label}.mem"
            )
        if target == "smc_axi":
            item = await self.read_single_and_check(
                addr, data, size=size, context=f"{context}.read"
            )
            return item.status, item.rdata, data
        status, rdata = await self.read_target_single_and_check(
            target, addr, data, context=f"{context}.read"
        )
        return status, rdata, data

    async def write_target_single_expect_status(
        self,
        target: str,
        addr: int,
        data: int,
        expected_status: DtpJtag2AxiStatus,
        *,
        size: int | None = None,
        wstrb: int | None = None,
        context: str = "single_write_error",
    ) -> tuple[int, int]:
        """Issue one target write and verify the requested non-OKAY/OKAY status."""
        cfg = self.target_cfg(target)
        size = cfg.default_size if size is None else size
        wstrb = self.target_full_wstrb(target, size) if wstrb is None else wstrb
        self.log_target_jtag2axi_op(
            target,
            context,
            addr=addr,
            data=data,
            size=size,
            wstrb=wstrb,
        )
        await self.write_target_single_raw(
            target,
            DtpJtag2AxiOp.WRITE,
            addr,
            data=data,
            wstrb=wstrb,
            size=size,
        )
        status, rdata = await self.poll_target_single_status(target)
        self.scoreboard_expect_completion(target, status, context=context)
        self.assert_equal(f"{context}.status", status, expected_status)
        await self.expect_bus_request(
            target, read=False, addr=addr, size=size, context=context, data=data, wstrb=wstrb
        )
        return status, rdata

    async def read_target_single_expect_status(
        self,
        target: str,
        addr: int,
        expected_status: DtpJtag2AxiStatus,
        *,
        size: int | None = None,
        context: str = "single_read_error",
    ) -> tuple[int, int]:
        """Issue one target read and verify the requested non-OKAY/OKAY status."""
        cfg = self.target_cfg(target)
        size = cfg.default_size if size is None else size
        self.log_target_jtag2axi_op(target, context, addr=addr, size=size)
        await self.write_target_single_raw(target, DtpJtag2AxiOp.READ, addr, size=size)
        status, rdata = await self.poll_target_single_status(target)
        self.scoreboard_expect_completion(target, status, context=context)
        self.assert_equal(f"{context}.status", status, expected_status)
        await self.expect_bus_request(target, read=True, addr=addr, size=size, context=context)
        return status, rdata

    async def verify_target_recovery(
        self,
        target: str,
        *,
        addr: int,
        data: int,
        read: bool,
        context: str,
    ) -> DtpJtag2AxiStatus:
        """Verify an OKAY access after an error/reset path to catch stuck state."""
        cfg = self.target_cfg(target)
        size = cfg.default_size
        if read:
            self.write_target_mem_int(target, addr, data, size)
            status, _ = await self.read_target_single_and_check(
                target,
                addr,
                data,
                size=size,
                context=f"{context}.recover_read",
            )
        else:
            status, _ = await self.write_target_single_and_check(
                target,
                addr,
                data,
                size=size,
                context=f"{context}.recover_write",
            )
            # CHK-AXI-WMEM against the STIMULUS intent (non-circular): the
            # bytes the recovery write meant to store must be in the RAM.
            intent = (data & self.data_mask(size)).to_bytes(self.size_bytes(size), "little")
            self.scoreboard_check_target_memory(
                target,
                addr,
                self.size_bytes(size),
                context=f"{context}.recover_write",
                expected=intent,
            )
        self.assert_equal(f"{context}.recovery_status", status, DtpJtag2AxiStatus.SUCCESS)
        return DtpJtag2AxiStatus(status)

    # --- gated SINGLE_OP evidence ---------------------------------------------
    async def gate_reference(self, target: str, image: int = 0) -> int:
        """The SINGLE_OP image a NOP capture returns while the bridge is enabled.

        Every bridge shifts each DR scan of the TAP and latches it at
        Update-DR unless disabled, whichever register the scan selects. The
        first NOP scan of ``image`` loads it into the update latch, and the
        second one's capture is the image the gated captures must repeat. A
        flow that takes several bridges' references in turn keeps the zero
        image, since each reference scan also loads the other bridges'
        latches.
        """
        cfg = self.target_cfg(target)
        await self.read_tdr(cfg.single_op_reg, image)
        return await self.read_tdr(cfg.single_op_reg, image)

    async def gate_image_reference(
        self, target: str, rng: random.Random, *, request_addr: int
    ) -> int:
        """``gate_reference`` over a seeded NOP image, for a flow that gates one bridge.

        Size and data are nonzero, the strobe is neither zero nor the full
        mask, and the address differs from the gated request's
        ``request_addr`` within the address field.
        """
        cfg = self.target_cfg(target)
        image = pack_single_op(
            DtpJtag2AxiOp.NOP,
            request_addr ^ rng.randint(1, (1 << cfg.addr_width) - 1),
            rng.randint(1, (1 << cfg.data_width) - 1),
            wstrb=rng.randint(1, (1 << cfg.wstrb_bits) - 2),
            size=rng.randint(1, (1 << cfg.size_bits) - 1),
            target=cfg,
        )
        return await self.gate_reference(target, image)

    def check_gated_tdr(
        self,
        target: str,
        reference: int,
        request: int,
        *,
        request_capture: int,
        post_capture: int,
        context: str,
    ) -> None:
        """Emit CHK-J2A-GATE-TDR: a gated SINGLE_OP register stays selected and latches nothing.

        The gated request's own capture and a NOP capture after its
        Update-DR must equal ``reference`` in every field. A register that
        left the scan path returns the shifted TDI instead, and one that
        latched the request returns its fields afterwards; ``request`` must
        differ from ``reference`` in a field the capture reads from the
        update latch (size, wstrb, address), so a latching bridge cannot
        pass.
        """
        cfg = self.target_cfg(target)
        names = ("op", "size", "wstrb", "data", "addr")

        def fields(value: int) -> dict[str, int]:
            return dict(zip(names, unpack_single_op_fields(value, target=cfg), strict=True))

        expected = fields(reference)
        stimulus = fields(request)
        distinct = any(stimulus[name] != expected[name] for name in ("size", "wstrb", "addr"))
        detail = f"{context} target={target} request=0x{request:x} reference=0x{reference:x}"
        scoreboard = self.target_evidence(target)
        if scoreboard is not None:
            scoreboard.expect_true(
                GATE_TDR_CHECK_ID, distinct, context=f"{detail} field=request_differs"
            )
        assert distinct, f"{context}: the gated request repeats the reference size, wstrb and addr"
        captures = {"request_capture": request_capture, "post_update_capture": post_capture}
        for label, capture in captures.items():
            observed = fields(capture)
            for name in names:
                if scoreboard is not None:
                    scoreboard.expect_equal(
                        GATE_TDR_CHECK_ID,
                        observed[name],
                        expected[name],
                        context=f"{detail} {label} field={name}",
                    )
                self.assert_equal(f"{context}.{label}.{name}", observed[name], expected[name])

    async def run_queued_write_drop(
        self, target: str, rng: random.Random, *, addr: int, context: str
    ) -> None:
        """The disable drops the bridge's buffered requests.

        A fixed-address series write with ``pl_depth`` at the bridge's write
        depth puts its first beat on the bus, where the responder holds AW
        (and W, which it accepts independently of AW), and queues the next
        beats in the bridge. The disable lands while they wait. The beat on
        the bus completes, since an AXI master cannot withdraw a valid
        request, and no queued beat reaches the bus, while gated or after
        the release: exactly one write completes and the slot keeps the first
        beat's word.
        """
        cfg = self.target_cfg(target)
        size = cfg.default_size
        queued = rng.randint(1, cfg.wr_pl_depth + 1)
        excluded = {self.read_target_mem_int(target, addr, size)}
        words: list[int] = []
        while len(words) < queued + 1:
            word = rng.getrandbits(cfg.data_width) & self.data_mask(size)
            if word not in excluded:
                excluded.add(word)
                words.append(word)
        # READY stall, in system cycles, outlasting the SERIES_CTRL
        # programming and capture (each with the driver's idle-TCK tail), the
        # beats' shifts and the disable settle.
        scan_tck = cfg.single_op_len + 32
        stall_tck = 2 * (scan_tck + self.cfg.idle_tck) + (queued + 1) * scan_tck + 16
        stall = (stall_tck * self.cfg.jtag_period_ns) // self.cfg.sys_clk_period_ns
        stall += rng.randint(16, 64)
        self.log.info(
            "%s %s: %d beat(s) queued behind the first, stall=%d words=%s",
            context,
            target,
            queued,
            stall,
            [f"0x{word:x}" for word in words],
        )
        writes_before = self.port_history(target).count(read=False)
        self.configure_target_backpressure(target, channels=("aw", "w"), stall_cycles=stall)
        await self.jtag2axi_series_ctrl(
            DtpJtag2AxiOp.WRITE,
            addr,
            pipeline_depth=cfg.wr_pl_depth,
            size=size,
            target=target,
        )
        before = await self.target_activity_counts(target)
        await self.series_data_no_incr(words[0], size=size, target=target, back_to_rti=True)
        await self.wait_for_target_activity(
            target, before=before, read=False, context=f"{context}.first_beat_on_bus"
        )
        for word in words[1:]:
            await self.series_data_no_incr(word, size=size, target=target, back_to_rti=True)
        # A beat the bridge refused would leave the series status BUSY_OR_FULL.
        _, _, _, _, status = await self.read_series_ctrl(size=size, target=target)
        self.assert_equal(f"{context}.queued_status", status, DtpJtag2AxiStatus.SUCCESS)
        await self.disable_debug_bits(cfg.dbg_disable_bit)
        if not await self.wait_port_completion(
            target, read=False, above=writes_before, timeout_cycles=2 * stall + 200
        ):
            raise AssertionError(f"{context}.first_beat: {target} write did not complete")
        # The state machine runs on TCK: it leaves the write path, and drops
        # the queue, only while TCK toggles.
        for _ in range(QUEUE_DROP_TCK):
            if self.cfg.tb_if.bridge_fsm_idle(target):
                break
            await self.tms_step(0)
        self.clear_target_backpressure(target)
        settled = await self.target_activity_counts(target)
        await self.enable_all_debug()
        for _ in range(QUEUE_DROP_TCK):
            await self.tms_step(0)
        await self.wait_sys_cycles(8)
        after = await self.target_activity_counts(target)
        writes = self.port_history(target).count(read=False)
        scoreboard = self.axi_scoreboard
        if scoreboard is not None:
            scoreboard.expect_no_activity(
                before=settled,
                after=after,
                context=(
                    f"{context} target={target} source=tb_pulse_counters "
                    f"window=first_beat_completion+release"
                ),
            )
            scoreboard.expect_no_activity(
                before={"writes": writes_before + 1},
                after={"writes": writes},
                context=(
                    f"{context} target={target} source=vip_monitor "
                    f"window=exact_delta sanctioned=first_beat(writes+1) queued={queued}"
                ),
            )
        for key in ("aw", "w", "ar"):
            self.assert_equal(f"{context}.{key}_count", after[key], settled[key])
        self.assert_equal(f"{context}.writes", writes, writes_before + 1)
        self.assert_equal(
            f"{context}.slot",
            self.read_target_mem_int(target, addr, size),
            words[0],
            f"addr=0x{addr:x}",
        )

    # --- errored-beat evidence ------------------------------------------------
    def check_error_rdata(
        self,
        target: str,
        addr: int,
        rdata: int,
        *,
        resp: int,
        preload: int,
        errored: int,
        size: int,
        context: str,
    ) -> None:
        """Emit CHK-J2A-ERR-RDATA: the SINGLE_OP rdata is the RDATA of the errored beat.

        The responder answers the errored R beat with the seeded ``errored``
        word, and the bridge latches the beat's data together with its status,
        so the capture returns that word: it equals ``errored`` and the beat
        the monitor observed at ``addr`` with ``resp``, and differs from the
        word preloaded in the slot.
        """
        cfg = self.target_cfg(target)
        mask = self.target_data_mask(target, size)
        observed = rdata & mask
        errored &= mask
        detail = (
            f"{context} target={target} addr=0x{addr:x} preload=0x{preload & mask:x} "
            f"errored=0x{errored:x}"
        )
        scoreboard = self.target_evidence(target)
        if scoreboard is not None:
            item = self.port_history(target).last(read=True)
            if item is None:
                raise AssertionError(f"{context}: no read observed on {target}")
            beat_addr = int(item.address) - int(item.address) % cfg.beat_bytes
            beat_word = int(item.data_words[0]) & mask
            scoreboard.expect_equal(
                ERR_RDATA_CHECK_ID,
                beat_addr,
                addr - addr % cfg.beat_bytes,
                context=f"{detail} field=beat_addr",
            )
            scoreboard.expect_equal(
                ERR_RDATA_CHECK_ID,
                int(item.resp),
                int(resp),
                context=f"{detail} field=beat_resp",
            )
            scoreboard.expect_equal(
                ERR_RDATA_CHECK_ID, observed, beat_word, context=f"{detail} field=rdata"
            )
            scoreboard.expect_equal(
                ERR_RDATA_CHECK_ID, beat_word, errored, context=f"{detail} field=beat_intent"
            )
            scoreboard.expect_equal(
                ERR_RDATA_CHECK_ID, observed, errored, context=f"{detail} field=rdata_intent"
            )
            scoreboard.expect_true(
                ERR_RDATA_CHECK_ID,
                observed != (preload & mask),
                context=f"{detail} field=rdata_not_preload",
            )
        self.assert_equal(f"{context}.err_rdata", observed, errored, f"addr=0x{addr:x}")

    # --- raw series TDR helpers ----------------------------------------------
    async def jtag2axi_series_ctrl(
        self,
        op: DtpJtag2AxiOp,
        addr: int,
        *,
        pipeline_depth: int = 0,
        size: int = SMC_DBG_AXSIZE_8B,
        reset: int = 0,
        target: str = "smc_axi",
        back_to_rti: bool = False,
    ) -> int:
        """Program or read a target SERIES_CTRL through the primary TAP."""
        cfg = self.target_cfg(target)
        value = pack_series_ctrl(
            op,
            addr,
            pipeline_depth=pipeline_depth,
            size=size,
            reset=reset,
            target=cfg,
        )
        if op != DtpJtag2AxiOp.NOP or reset:
            await self.write_tdr(cfg.series_ctrl_reg, value)
            return 0
        return await self.read_tdr(cfg.series_ctrl_reg, shift_value=value)

    async def read_series_ctrl(
        self,
        *,
        size: int = SMC_DBG_AXSIZE_8B,
        target: str = "smc_axi",
    ) -> tuple[int, int, int, int, int]:
        """Capture and decode a target SERIES_CTRL."""
        raw = await self.jtag2axi_series_ctrl(DtpJtag2AxiOp.NOP, 0, size=size, target=target)
        decoded = unpack_series_ctrl(raw, target=target)
        self.log.info(
            "%s SERIES_CTRL reset=%d addr=0x%x pl_depth=%d size=%d status=%s",
            target,
            decoded[0],
            decoded[1],
            decoded[2],
            decoded[3],
            DtpJtag2AxiStatus(decoded[4]).name,
        )
        # Every series stream ends with this status capture; a bridge stuck
        # BUSY fails CHK-AXI-COMPLETION here (every call site expects a final,
        # settled status — SUCCESS or an expected error, never BUSY).
        self.scoreboard_expect_completion(target, decoded[4], context=f"series_ctrl.{target}")
        return decoded

    async def check_series_addr(
        self, target: str, expected_addr: int, *, size: int, context: str
    ) -> int:
        """Emit CHK-J2A-SERIES-ADDR: the SERIES_CTRL capture holds ``expected_addr``; returns its status."""
        expected = self.masked_addr(target, expected_addr)
        _, addr_after, _, _, status = await self.read_series_ctrl(size=size, target=target)
        scoreboard = self.target_evidence(target)
        if scoreboard is not None:
            scoreboard.expect_equal(
                SERIES_ADDR_CHECK_ID, addr_after, expected, context=f"{context} target={target}"
            )
        self.assert_equal(f"{context}.addr_after", addr_after, expected)
        return status

    async def _series_data_shift(
        self,
        instr: DtpJtagInstr,
        data: int,
        *,
        size: int,
        target: str,
        increment: int | None = None,
        back_to_rti: bool = False,
    ) -> tuple[int, int]:
        value, width = pack_series_data(
            data, size, increment=increment, target=self.target_cfg(target)
        )
        await self.load_ir(instr, back_to_rti=True)
        item = await self.shift_dr(value, width, back_to_rti=back_to_rti)
        for _ in range(5):
            await self.tms_step(0)
        return item.result, width

    async def series_data_incr(
        self,
        data: int,
        *,
        size: int,
        target: str = "smc_axi",
        back_to_rti: bool = False,
    ) -> int:
        cfg = self.target_cfg(target)
        result, _ = await self._series_data_shift(
            cfg.series_data_incr_instr,
            data,
            size=size,
            target=target,
            back_to_rti=back_to_rti,
        )
        return result

    async def series_data_no_incr(
        self,
        data: int,
        *,
        size: int,
        target: str = "smc_axi",
        back_to_rti: bool = False,
    ) -> int:
        cfg = self.target_cfg(target)
        result, _ = await self._series_data_shift(
            cfg.series_data_no_incr_instr,
            data,
            size=size,
            target=target,
            back_to_rti=back_to_rti,
        )
        return result

    async def series_data_with_status(
        self,
        data: int,
        *,
        size: int,
        increment: int,
        target: str = "smc_axi",
        back_to_rti: bool = False,
    ) -> tuple[int, int]:
        cfg = self.target_cfg(target)
        result, _ = await self._series_data_shift(
            cfg.series_data_with_status_instr,
            data,
            size=size,
            target=target,
            increment=increment,
            back_to_rti=back_to_rti,
        )
        return unpack_series_data(result, size, with_status=True, target=cfg)

    # --- plain series beats -----------------------------------------------------
    async def series_write_beat(
        self, target: str, data: int, *, addr: int, size: int, increment: bool, context: str
    ) -> None:
        """One SERIES_DATA write beat to ``addr``, judged once the port completes it.

        The beat lands on the lanes ``addr`` and ``size`` select: the ledger
        judges the request (CHK-J2A-BUS-REQ) and the subordinate must hold
        ``data`` at ``addr`` (CHK-AXI-WMEM).
        """
        cfg = self.target_cfg(target)
        eff = cfg.axsize(size)
        payload = data & self.data_mask(eff)
        lane = addr % cfg.beat_bytes
        completed = self.port_history(target).count(read=False)
        before = await self.target_activity_counts(target)
        if increment:
            await self.series_data_incr(payload, size=size, target=target, back_to_rti=True)
        else:
            await self.series_data_no_incr(payload, size=size, target=target, back_to_rti=True)
        await self.wait_for_target_activity(
            target, before=before, read=False, context=f"{context}.axi"
        )
        if not await self.wait_port_completion(target, read=False, above=completed):
            raise AssertionError(f"{context}: {target} write did not complete")
        await self.expect_bus_request(
            target,
            read=False,
            addr=addr,
            size=eff,
            context=context,
            data=payload << (8 * lane),
            wstrb=self.full_wstrb(eff) << lane,
        )
        self.check_target_word(target, addr, payload, size=eff, context=f"{context}.mem")

    async def series_read_beat(
        self, target: str, *, addr: int, size: int, increment: bool, context: str
    ) -> int:
        """Read ``addr`` through SERIES_CTRL(READ) and two SERIES_DATA shifts; returns the payload.

        The first shift launches the read, and at pipeline depth 0 the bridge
        launches no second one; once the port completes the read
        (CHK-J2A-BUS-REQ), the second shift captures its data.
        """
        await self.jtag2axi_series_ctrl(DtpJtag2AxiOp.READ, addr, size=size, target=target)
        shift = self.series_data_incr if increment else self.series_data_no_incr
        completed = self.port_history(target).count(read=True)
        before = await self.target_activity_counts(target)
        await shift(0, size=size, target=target, back_to_rti=True)
        await self.wait_for_target_activity(
            target, before=before, read=True, context=f"{context}.axi"
        )
        if not await self.wait_port_completion(target, read=True, above=completed):
            raise AssertionError(f"{context}: {target} read did not complete")
        cfg = self.target_cfg(target)
        await self.expect_bus_request(
            target, read=True, addr=addr, size=cfg.axsize(size), context=context
        )
        raw = await shift(0, size=size, target=target, back_to_rti=True)
        payload, _ = unpack_series_data(raw, size, target=cfg)
        return payload

    async def series_reread_fixed(
        self,
        target: str,
        addr: int,
        last_word: int,
        beats: int,
        rng: random.Random,
        *,
        context: str,
    ) -> int:
        """Read the fixed series address ``addr`` ``beats`` times; returns the SERIES_CTRL status after.

        The first read returns ``last_word``, the last word the stream wrote;
        before every later read the slot takes a fresh word, so each capture
        is its own. The series address stays at ``addr``.
        """
        size = self.target_cfg(target).default_size
        expected = last_word
        for idx in range(1, beats + 1):
            if idx > 1:
                expected = self.random_distinct_word(rng, target, expected)
                self.write_target_mem_int(target, addr, expected, size)
            obs = await self.series_read_beat(
                target, addr=addr, size=size, increment=False, context=f"{context}.read#{idx}"
            )
            self.log_iteration(idx, beats, "series no-incr read addr=0x%x obs=0x%x", addr, obs)
            self.assert_equal(f"{context}.rdata#{idx}", obs, expected)
        _, addr_after, _, _, status = await self.read_series_ctrl(size=size, target=target)
        self.assert_equal(f"{context}.addr_after", addr_after, self.masked_addr(target, addr))
        return status

    # --- WITH_ERROR_STATUS streams ---------------------------------------------
    def plan_series_status(self, target: str, rng: random.Random) -> DtpSeriesStatusPlan:
        """Choose a clean WITH_ERROR_STATUS stream whose footprint fits one responder window."""
        cfg = self.target_cfg(target)
        plan = DtpSeriesStatusPlan(
            target=target,
            base=0,
            size=cfg.default_size,
            stride=cfg.beat_bytes,
            increments=SERIES_STATUS_INCREMENTS,
            fault_idx=None,
            expected=DtpJtag2AxiStatus.SUCCESS,
        )
        return dataclasses.replace(plan, base=self.random_series_base(target, rng, span=plan.span))

    def arm_series_status_fault(
        self, plan: DtpSeriesStatusPlan, rng: random.Random, *, read: bool
    ) -> DtpSeriesStatusPlan:
        """Arm a random SLVERR or DECERR on a random first-visit beat of the stream.

        ``DTP_J2A_STATUS_BIT_NEGATIVE=1`` keeps the expectation but leaves the
        responder unarmed, so the fault beat's checks must fail.
        """
        fault_idx = rng.choice(plan.first_visit_beats())
        resp = rng.choice((AXI_RESP_SLVERR, AXI_RESP_DECERR))
        armed = dataclasses.replace(
            plan, fault_idx=fault_idx, expected=self.axi_resp_to_jtag_status(resp)
        )
        if OcahKnobs.is_set(STATUS_BIT_NEGATIVE_KNOB):
            self.log.warning(
                "NEGATIVE VALIDATION: fault beat %d at 0x%x left unarmed; "
                "the fault beat's checks must fail",
                fault_idx,
                armed.fault_addr,
            )
        else:
            self.configure_target_error(
                plan.target, armed.fault_addr, resp, read=read, write=not read
            )
        return armed

    @staticmethod
    def series_status_recovery_addr(plan: DtpSeriesStatusPlan) -> int:
        """An aligned slot outside the stream's footprint for the recovery access."""
        return plan.base - plan.stride if plan.base >= plan.stride else plan.base + plan.span

    def check_series_status_bit(
        self, plan: DtpSeriesStatusPlan, shift: int, observed: int, *, context: str
    ) -> None:
        """Judge the WITH_ERROR_STATUS bit returned by ``shift`` (1 = the previous beat failed)."""
        expected = plan.expected_status_bit(shift)
        name = f"{context}.status_bit#{shift}"
        detail = f"addr=0x{plan.addr(shift):x}"
        scoreboard = self.axi_scoreboard
        if scoreboard is not None:
            scoreboard.expect_equal(
                STATUS_BIT_CHECK_ID,
                observed,
                expected,
                context=f"{name} target={plan.target} {detail}",
            )
        self.assert_equal(name, observed, expected, detail)

    async def _series_status_shift(
        self, plan: DtpSeriesStatusPlan, shift: int, data: int, *, read: bool, context: str
    ) -> tuple[int, int]:
        """One shift of a WITH_ERROR_STATUS stream; the shift past the last beat holds the address.

        Returns once the port completes the shift's transaction.
        """
        increment = plan.increments[shift] if shift < plan.beats else 0
        addr = plan.addr(shift)
        lane = addr % self.target_cfg(plan.target).beat_bytes
        payload = data & self.data_mask(plan.size)
        completed = self.port_history(plan.target).count(read=read)
        before = await self.target_activity_counts(plan.target)
        rdata, status_bit = await self.series_data_with_status(
            payload, size=plan.size, increment=increment, target=plan.target, back_to_rti=True
        )
        await self.wait_for_target_activity(
            plan.target, before=before, read=read, context=f"{context}.axi#{shift}"
        )
        if not await self.wait_port_completion(plan.target, read=read, above=completed):
            raise AssertionError(
                f"{context}.commit#{shift}: {plan.target} transaction did not complete"
            )
        await self.expect_bus_request(
            plan.target,
            read=read,
            addr=addr,
            size=plan.size,
            context=f"{context}#{shift}",
            data=payload << (8 * lane),
            wstrb=self.full_wstrb(plan.size) << lane,
        )
        self.check_series_status_bit(plan, shift, status_bit, context=context)
        return rdata, status_bit

    async def run_series_status_write(
        self, plan: DtpSeriesStatusPlan, words: list[int], *, context: str
    ) -> None:
        """Drive one WITH_ERROR_STATUS write stream and judge every shift.

        Each shift returns the previous beat's status bit and a trailing shift
        returns the last beat's. The responder drops the fault beat, so that
        slot keeps its prior word. The SERIES_CTRL capture must show the
        pattern's final address.
        """
        target = plan.target
        fault_before = 0
        if plan.fault_idx is not None:
            fault_before = self.read_target_mem_int(target, plan.fault_addr, plan.size)
        await self.jtag2axi_series_ctrl(
            DtpJtag2AxiOp.WRITE, plan.base, size=plan.size, target=target, back_to_rti=True
        )
        for idx, (data, increment) in enumerate(zip(words, plan.increments, strict=True)):
            addr = plan.addr(idx)
            self.log_iteration(
                idx + 1,
                plan.beats,
                "with-status write addr=0x%08x inc=%d data=0x%x resp=%s",
                addr,
                increment,
                data,
                plan.beat_resp_name(idx),
            )
            await self._series_status_shift(plan, idx, data, read=False, context=context)
            if plan.is_fault(idx):
                self.check_target_word(
                    target,
                    addr,
                    fault_before,
                    size=plan.size,
                    context=f"{context}.mem_dropped#{idx}",
                )
            else:
                self.check_target_word(
                    target, addr, data, size=plan.size, context=f"{context}.mem#{idx}"
                )
        await self._series_status_shift(plan, plan.beats, 0, read=False, context=context)
        _, addr_after, _, _, _ = await self.read_series_ctrl(size=plan.size, target=target)
        self.assert_equal(
            f"{context}.addr_after",
            addr_after,
            self.masked_addr(target, plan.final_addr),
        )

    async def run_series_status_read(
        self, plan: DtpSeriesStatusPlan, expected: list[int], *, context: str
    ) -> None:
        """Drive one WITH_ERROR_STATUS read stream from a single SERIES_CTRL preload.

        Every shift launches a read and returns the previous read's word and
        status bit, so shift k judges read k-1 and a trailing shift judges the
        last beat. ``expected`` holds each beat's word when the stream starts;
        once a read completes, a beat that re-reads its address gets a fresh
        seeded word written there, so that read's capture cannot repeat the
        earlier one. The fault beat answers a zero errored-beat word and is
        not judged.
        """
        target = plan.target
        expected = list(expected)
        rng = self.rng(f"{target}.series_status_fresh")
        await self.jtag2axi_series_ctrl(
            DtpJtag2AxiOp.READ, plan.base, size=plan.size, target=target, back_to_rti=True
        )
        for shift in range(plan.beats + 1):
            if shift < plan.beats:
                self.log_iteration(
                    shift + 1,
                    plan.beats,
                    "with-status read addr=0x%08x inc=%d resp=%s",
                    plan.addr(shift),
                    plan.increments[shift],
                    plan.beat_resp_name(shift),
                )
            rdata, _ = await self._series_status_shift(plan, shift, 0, read=True, context=context)
            beat = shift - 1
            if beat >= 0 and not plan.is_fault(beat):
                self.assert_equal(
                    f"{context}.rdata#{beat}", rdata, expected[beat], f"addr=0x{plan.addr(beat):x}"
                )
            if shift + 1 < plan.beats and plan.addr(shift + 1) == plan.addr(shift):
                fresh = self.random_distinct_word(rng, target, expected[shift])
                self.log.info(
                    "%s: held address 0x%x takes 0x%x for read %d",
                    context,
                    plan.addr(shift),
                    fresh,
                    shift + 1,
                )
                self.write_target_mem_int(target, plan.addr(shift), fresh, plan.size)
                expected[shift + 1] = fresh
        _, addr_after, _, _, _ = await self.read_series_ctrl(size=plan.size, target=target)
        self.assert_equal(
            f"{context}.addr_after",
            addr_after,
            self.masked_addr(target, plan.final_addr),
        )

    def emit_series_status_nonvacuity(
        self, label: str, plan: DtpSeriesStatusPlan, operations: int
    ) -> None:
        """CHK-AXI-NONVAC: the stream ran and a real bus response consumed its fault credit."""
        scoreboard = self.axi_scoreboard
        if scoreboard is None:
            return
        unconsumed = scoreboard.unconsumed_credits()
        scoreboard.expect_nonvacuous(
            operations >= plan.beats and plan.fault_idx is not None and unconsumed == 0,
            context=(
                f"scenario={label} target={plan.target} operations={operations} "
                f"fault_beat={plan.fault_idx} resp={plan.expected.name} "
                f"credits_unconsumed={unconsumed}"
            ),
        )

    # --- AXI activity helpers -------------------------------------------------
    async def axi_activity_counts(self) -> dict[str, int]:
        """Sample the SMC AXI request activity counters on dtp_tb_if."""
        await ReadOnly()
        tb = self.cfg.tb_if
        counts = {
            "aw": tb.sample("smc_axi_awvalid_count"),
            "w": tb.sample("smc_axi_wvalid_count"),
            "ar": tb.sample("smc_axi_arvalid_count"),
        }
        await ClockCycles(tb.clk, 1)
        return counts

    async def target_activity_counts(self, target: str) -> dict[str, int]:
        """Sample request activity counters for one JTAG2AXI target."""
        cfg = self.target_cfg(target)
        await ReadOnly()
        tb = self.cfg.tb_if
        counts = {
            "aw": tb.sample(f"{cfg.activity_prefix}_awvalid_count"),
            "w": tb.sample(f"{cfg.activity_prefix}_wvalid_count"),
            "ar": tb.sample(f"{cfg.activity_prefix}_arvalid_count"),
        }
        await ClockCycles(tb.clk, 1)
        return counts

    async def target_stall_counts(self, target: str) -> dict[str, int]:
        """Sample the READY-stall counters for one JTAG2AXI target."""
        cfg = self.target_cfg(target)
        await ReadOnly()
        tb = self.cfg.tb_if
        counts = {
            channel: tb.sample(f"{cfg.activity_prefix}_{channel}_stall_count")
            for channel in ("aw", "w", "ar")
        }
        await ClockCycles(tb.clk, 1)
        return counts

    async def expect_no_smc_axi_activity(self, cycles: int, *, context: str) -> None:
        """Verify no SMC AXI request-valid pulse occurs across a bounded window."""
        before = await self.axi_activity_counts()
        await self.wait_sys_cycles(cycles)
        after = await self.axi_activity_counts()
        self.log.info("%s AXI activity before=%s after=%s", context, before, after)
        self.assert_equal(f"{context}.aw_count", after["aw"], before["aw"])
        self.assert_equal(f"{context}.w_count", after["w"], before["w"])
        self.assert_equal(f"{context}.ar_count", after["ar"], before["ar"])

    async def expect_no_target_activity(self, target: str, cycles: int, *, context: str) -> None:
        """Verify no target request-valid pulse occurs across a bounded window."""
        before = await self.target_activity_counts(target)
        await self.wait_sys_cycles(cycles)
        after = await self.target_activity_counts(target)
        self.log.info("%s %s activity before=%s after=%s", context, target, before, after)
        self.assert_equal(f"{context}.aw_count", after["aw"], before["aw"])
        self.assert_equal(f"{context}.w_count", after["w"], before["w"])
        self.assert_equal(f"{context}.ar_count", after["ar"], before["ar"])

    async def expect_smc_axi_activity(
        self,
        *,
        before: dict[str, int],
        read: bool,
        context: str,
    ) -> None:
        """Verify a read or write produced SMC AXI request activity."""
        after = await self.axi_activity_counts()
        self.log.info("%s AXI activity before=%s after=%s", context, before, after)
        key = "ar" if read else "aw"
        assert after[key] > before[key], f"{context}: expected {key.upper()} activity"

    async def expect_target_activity(
        self,
        target: str,
        *,
        before: dict[str, int],
        read: bool,
        context: str,
    ) -> None:
        """Verify a target read or write produced request activity."""
        after = await self.target_activity_counts(target)
        self.log.info("%s %s activity before=%s after=%s", context, target, before, after)
        key = "ar" if read else "aw"
        assert after[key] > before[key], f"{context}: expected {target} {key.upper()} activity"

    async def wait_for_target_activity(
        self,
        target: str,
        *,
        before: dict[str, int],
        read: bool,
        context: str,
        timeout_cycles: int = 100,
    ) -> dict[str, int]:
        """Wait until a series operation has reached the target request channel."""
        key = "ar" if read else "aw"
        for _ in range(timeout_cycles):
            after = await self.target_activity_counts(target)
            if after[key] > before[key]:
                self.log.info("%s %s activity before=%s after=%s", context, target, before, after)
                return after
            await self.wait_sys_cycles(1)
        after = await self.target_activity_counts(target)
        raise AssertionError(
            f"{context}: expected {target} {key.upper()} activity within {timeout_cycles} "
            f"cycles, before={before}, after={after}"
        )
