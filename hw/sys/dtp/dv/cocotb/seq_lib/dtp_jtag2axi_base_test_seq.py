# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""JTAG2AXI helper base sequence for DTP tests."""

from __future__ import annotations

import dataclasses
import random
from dataclasses import dataclass

import cocotb
from cocotb.triggers import ClockCycles, ReadOnly
from env.dtp_jtag_item import DtpJtagItem, DtpJtagOp
from env.dtp_tap_device import unpack_jtag2axi_caps
from env.dtp_types import (
    JTAG2AXI_TARGETS,
    MEM_IMAGE_CHECK_ID,
    SMC_DBG_AXSIZE_8B,
    DtpJtag2AxiOp,
    DtpJtag2AxiStatus,
    DtpJtagInstr,
    get_jtag2axi_target,
    pack_series_ctrl,
    pack_series_data,
    pack_single_op,
    unpack_series_ctrl,
    unpack_series_data,
    unpack_single_op,
)
from ocah_axi_vip import OcahAxiItem
from ocah_jtag_vip import OcahJtagChecker
from ocah_lib import OcahKnobs

from .dtp_base_test_seq import dtp_base_test_seq

AXI_MEM_SIZE = 2**16
AXI_BEAT_BYTES = 8
GEOMETRY_CHECK_ID = "CHK-J2A-GEOMETRY"
STATUS_BIT_CHECK_ID = "CHK-J2A-STATUS-BIT"
ERR_RDATA_CHECK_ID = "CHK-J2A-ERR-RDATA"
SERIES_ADDR_CHECK_ID = "CHK-J2A-SERIES-ADDR"
BLOCKED_CHECK_ID = "CHK-AXI-BLOCKED"
STATUS_BIT_NEGATIVE_KNOB = "DTP_J2A_STATUS_BIT_NEGATIVE"
AXI_RESP_SLVERR = 2
AXI_RESP_DECERR = 3
# Increment flag per beat of the WITH_ERROR_STATUS streams: the second beat
# re-writes the held address.
SERIES_STATUS_INCREMENTS = (1, 0, 1, 1)


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


class dtp_jtag2axi_base_test_seq(dtp_base_test_seq):
    """Helpers for DTP JTAG2AXI single-operation and series-operation tests."""

    async def pre_body(self) -> None:
        """Gate every pass on the DUT publishing the geometry the DV table holds."""
        await super().pre_body()
        await self.verify_bridge_geometry()

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
        """Pick a bridge-beat-aligned address inside the OSS AXI RAM window.

        The SMC fabric bridge exposes 64-bit data beats. Keeping randomized
        sub-beat transfers on the same beat boundary avoids ambiguous WSTRB
        placement and makes each random choice directly replayable from logs.
        """
        max_addr = AXI_MEM_SIZE - AXI_BEAT_BYTES
        return rng.randrange(0, (max_addr // AXI_BEAT_BYTES) + 1) * AXI_BEAT_BYTES

    def read_mem_int(self, addr: int, size: int) -> int:
        """Read the backdoor AXI RAM for the transfer size."""
        return int.from_bytes(self.cfg.axi_ram.read(addr, self.size_bytes(size)), "little")

    def write_mem_int(self, addr: int, value: int, size: int) -> None:
        """Backdoor-preload the AXI RAM for read-side scenarios."""
        payload = (value & self.data_mask(size)).to_bytes(self.size_bytes(size), "little")
        self.cfg.axi_ram.write(addr, payload)
        self._mirror_model_preload("smc_axi", addr, payload)

    # --- shared-VIP AXI scoreboard glue ---------------------------------------
    @property
    def axi_scoreboard(self):
        """The shared OcahAxiScoreboard, or None when the test did not opt in."""
        return getattr(self.cfg, "axi_scoreboard", None)

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
            dut_bytes=bytes(self.target_memory(target).read(addr, length)),
            address=addr,
            length=length,
            stream=target,
            context=context,
            expected=expected,
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

    def scoreboard_expect_completion(self, target: str, status: int, *, context: str) -> None:
        """Emit CHK-AXI-COMPLETION: the bridge left BUSY within the poll bound."""
        scoreboard = self.axi_scoreboard
        if scoreboard is None:
            return
        cfg = self.target_cfg(target)
        # Bound: 16 status polls, each one wide TDR scan plus TAP navigation.
        bound_ns = 16 * (cfg.single_op_len + 16) * self.cfg.jtag_period_ns
        scoreboard.expect_not_timed_out(
            "CHK-AXI-COMPLETION",
            timed_out=(int(status) == int(DtpJtag2AxiStatus.BUSY_OR_FULL)),
            timeout_ns=float(bound_ns),
            context=f"{context} target={target} polls=16",
        )

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
    ) -> DtpJtag2AxiStatus:
        """Configure a one-shot target response error and return expected status.

        ``arm=False`` injects the responder error WITHOUT arming the reference
        model or a scoreboard credit — for gated attempts whose op must never
        reach the bus (an armed credit that is never consumed correctly fails
        CHK-AXI-CREDITS at finalization).
        """
        cfg = self.target_cfg(target)
        aligned = addr - (addr % cfg.beat_bytes)
        self.log.info(
            "Configure %s error addr=0x%08x aligned=0x%08x resp=%d read=%d write=%d",
            target,
            addr,
            aligned,
            resp,
            read,
            write,
        )
        self.target_responder(target).inject_error(aligned, resp, read=read, write=write)
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

    def target_mem_size(self, target: str) -> int:
        return int(self.cfg.axi_mem_size if target == "smc_axi" else self.cfg.otp_axil_mem_size)

    def random_target_aligned_addr(self, target: str, rng, size: int | None = None) -> int:
        cfg = self.target_cfg(target)
        align = cfg.beat_bytes if size is None else max(cfg.beat_bytes, self.size_bytes(size))
        max_addr = self.target_mem_size(target) - align
        return rng.randrange(0, (max_addr // align) + 1) * align

    def read_target_mem_int(self, target: str, addr: int, size: int) -> int:
        return int.from_bytes(
            self.target_memory(target).read(addr, self.size_bytes(size)), "little"
        )

    def write_target_mem_int(self, target: str, addr: int, value: int, size: int) -> None:
        payload = (value & self.data_mask(size)).to_bytes(self.size_bytes(size), "little")
        self.target_memory(target).write(addr, payload)
        self._mirror_model_preload(target, addr, payload)

    # --- end-state byte image of a random write stream ---------------------------
    def snapshot_target_word(
        self, target: str, image: dict[int, int], addr: int, size: int
    ) -> None:
        """Record the bytes of the word at ``addr`` that the image lacks."""
        word = self.read_target_mem_int(target, addr, size)
        for byte_idx in range(self.size_bytes(size)):
            image.setdefault(addr + byte_idx, (word >> (8 * byte_idx)) & 0xFF)

    @staticmethod
    def image_write(image: dict[int, int], addr: int, data: int, wstrb: int, size: int) -> None:
        """Apply one write's enabled lanes to the byte image."""
        for byte_idx in range(1 << size):
            if (wstrb >> byte_idx) & 0x1:
                image[addr + byte_idx] = (data >> (8 * byte_idx)) & 0xFF

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
        """Issue one single-op write and verify status plus enabled byte lanes."""
        wstrb = self.full_wstrb(size) if wstrb is None else wstrb
        data &= self.data_mask(size)
        self.log_jtag2axi_op(context, addr=addr, data=data, size=size, wstrb=wstrb)
        self.scoreboard_arm_strobes("smc_axi", wstrb, addr, context=context)
        item = await self.jtag2axi_write(addr, data, wstrb=wstrb, size=size)
        self.scoreboard_expect_completion("smc_axi", item.status, context=context)
        self.assert_equal(f"{context}.status", item.status, DtpJtag2AxiStatus.SUCCESS)
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
        """Issue one single-op read and verify status plus returned data."""
        expected &= self.data_mask(size)
        self.log_jtag2axi_op(context, addr=addr, size=size)
        item = await self.jtag2axi_read(addr, size=size)
        self.scoreboard_expect_completion("smc_axi", item.status, context=context)
        self.assert_equal(f"{context}.status", item.status, DtpJtag2AxiStatus.SUCCESS)
        self.assert_equal(
            f"{context}.rdata",
            item.rdata & self.data_mask(size),
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
        attempts whose write must never reach the bus (an armed strobe credit
        that is never consumed correctly fails CHK-AXI-CREDITS).
        """
        cfg = self.target_cfg(target)
        size = cfg.default_size if size is None else size
        if op == DtpJtag2AxiOp.WRITE and arm_strobes:
            # Intent strobes for CHK-AXI-STRB: the wstrb programmed into the
            # TDR is the stimulus truth the observed bus strobes must match.
            self.scoreboard_arm_strobes(target, wstrb, addr, context="single_op")
        value = pack_single_op(op, addr, data, wstrb=wstrb, size=size, target=cfg)
        await self.write_tdr(cfg.single_op_reg, value)

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
        """Issue one target write and verify status plus enabled byte lanes."""
        cfg = self.target_cfg(target)
        size = cfg.default_size if size is None else size
        wstrb = self.target_full_wstrb(target, size) if wstrb is None else wstrb
        data &= self.target_data_mask(target, size)
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
        """Poll an issued write to its settled status and judge SUCCESS plus the enabled byte lanes in memory."""
        cfg = self.target_cfg(target)
        data &= self.target_data_mask(target, size)
        status, rdata = await self.poll_target_single_status(target)
        self.scoreboard_expect_completion(target, status, context=context)
        self.assert_equal(f"{context}.status", status, DtpJtag2AxiStatus.SUCCESS)
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
        """Poll an issued read to its settled status and judge SUCCESS plus the returned data."""
        cfg = self.target_cfg(target)
        status, rdata = await self.poll_target_single_status(target)
        self.scoreboard_expect_completion(target, status, context=context)
        self.assert_equal(f"{context}.status", status, DtpJtag2AxiStatus.SUCCESS)
        self.assert_equal(
            f"{context}.rdata",
            rdata & self.target_data_mask(target, size),
            expected,
            f"target={cfg.name} addr=0x{addr:x} size={size}",
        )
        return status, rdata

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

    async def verify_not_stuck_busy(
        self,
        target: str,
        *,
        context: str,
        max_polls: int = 8,
    ) -> int:
        """Re-read SINGLE_OP and prove the bridge eventually leaves BUSY_OR_FULL."""
        status = DtpJtag2AxiStatus.BUSY_OR_FULL
        rdata = 0
        for poll_idx in range(1, max_polls + 1):
            status, rdata = await self.poll_target_single_status(target)
            self.log.info("%s poll %d status=%s", context, poll_idx, DtpJtag2AxiStatus(status).name)
            if status != DtpJtag2AxiStatus.BUSY_OR_FULL:
                return status
        raise AssertionError(f"{context}: target {target} remained BUSY_OR_FULL")

    # --- errored-beat evidence ------------------------------------------------
    def last_observed_read(self, target: str) -> OcahAxiItem | None:
        """The newest read the shared monitor completed on ``target``; None without a monitor."""
        monitor = getattr(self.cfg, "axi_monitors", {}).get(target)
        if monitor is None:
            return None
        reads = monitor.get_read_transactions()
        if not reads:
            raise AssertionError(f"no read observed on {target}")
        return reads[-1]

    def check_error_rdata(
        self,
        target: str,
        addr: int,
        rdata: int,
        *,
        resp: int,
        preload: int,
        size: int,
        context: str,
    ) -> None:
        """Emit CHK-J2A-ERR-RDATA: the SINGLE_OP rdata is the RDATA of the errored beat.

        The bridge latches the errored R beat's data together with its
        status, so the capture returns the word the responder drove on that
        beat: it equals the beat the monitor observed at ``addr`` with
        ``resp`` and differs from the word preloaded in the slot.
        """
        item = self.last_observed_read(target)
        if item is None:
            return
        cfg = self.target_cfg(target)
        mask = self.target_data_mask(target, size)
        observed = rdata & mask
        beat_addr = int(item.address) - int(item.address) % cfg.beat_bytes
        beat_word = int(item.data_words[0]) & mask
        detail = f"{context} target={target} addr=0x{addr:x} preload=0x{preload & mask:x}"
        scoreboard = self.axi_scoreboard
        if scoreboard is not None:
            scoreboard.expect_equal(
                ERR_RDATA_CHECK_ID,
                beat_addr,
                addr - addr % cfg.beat_bytes,
                context=f"{detail} field=beat_addr",
            )
            scoreboard.expect_equal(
                ERR_RDATA_CHECK_ID, int(item.resp), int(resp), context=f"{detail} field=beat_resp"
            )
            scoreboard.expect_equal(
                ERR_RDATA_CHECK_ID, observed, beat_word, context=f"{detail} field=rdata"
            )
            scoreboard.expect_true(
                ERR_RDATA_CHECK_ID,
                observed != (preload & mask),
                context=f"{detail} field=rdata_not_preload",
            )
        self.assert_equal(
            f"{context}.err_rdata",
            observed,
            beat_word,
            f"addr=0x{addr:x} beat_addr=0x{beat_addr:x}",
        )

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
        cfg = self.target_cfg(target)
        expected = expected_addr & ((1 << cfg.addr_width) - 1)
        _, addr_after, _, _, status = await self.read_series_ctrl(size=size, target=target)
        scoreboard = self.axi_scoreboard
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
        increment: int | None = None,
        back_to_rti: bool = False,
    ) -> tuple[int, int]:
        value, width = pack_series_data(data, size, increment=increment)
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
            increment=increment,
            back_to_rti=back_to_rti,
        )
        return unpack_series_data(result, size, with_status=True)

    # --- WITH_ERROR_STATUS streams ---------------------------------------------
    def plan_series_status(self, target: str, rng: random.Random) -> DtpSeriesStatusPlan:
        """Choose a clean WITH_ERROR_STATUS stream whose footprint fits the target window."""
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
        base = min(
            self.random_target_aligned_addr(target, rng), self.target_mem_size(target) - plan.span
        )
        return dataclasses.replace(plan, base=base)

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
        """One shift of a WITH_ERROR_STATUS stream; the shift past the last beat holds the address."""
        increment = plan.increments[shift] if shift < plan.beats else 0
        before = await self.target_activity_counts(plan.target)
        rdata, status_bit = await self.series_data_with_status(
            data, size=plan.size, increment=increment, target=plan.target, back_to_rti=True
        )
        await self.wait_for_target_activity(
            plan.target, before=before, read=read, context=f"{context}.axi#{shift}"
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
            observed = self.read_target_mem_int(target, addr, plan.size)
            if plan.is_fault(idx):
                self.assert_equal(
                    f"{context}.mem_dropped#{idx}", observed, fault_before, f"addr=0x{addr:x}"
                )
            else:
                self.assert_equal(f"{context}.mem#{idx}", observed, data, f"addr=0x{addr:x}")
        await self._series_status_shift(plan, plan.beats, 0, read=False, context=context)
        _, addr_after, _, _, _ = await self.read_series_ctrl(size=plan.size, target=target)
        self.assert_equal(f"{context}.addr_after", addr_after, plan.final_addr)

    async def run_series_status_read(
        self, plan: DtpSeriesStatusPlan, expected: list[int], *, context: str
    ) -> None:
        """Drive one WITH_ERROR_STATUS read stream from a single SERIES_CTRL preload.

        Every shift launches a read and returns the previous read's word and
        status bit, so shift k judges read k-1 and a trailing shift judges the
        last beat. The fault beat's word is not judged: the responder returns
        no valid data with an error response.
        """
        target = plan.target
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
        _, addr_after, _, _, _ = await self.read_series_ctrl(size=plan.size, target=target)
        self.assert_equal(f"{context}.addr_after", addr_after, plan.final_addr)

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

    async def wait_for_smc_axi_activity(
        self,
        *,
        before: dict[str, int],
        read: bool,
        context: str,
        timeout_cycles: int = 100,
    ) -> dict[str, int]:
        """Wait until a series operation has reached the SMC AXI request channel."""
        key = "ar" if read else "aw"
        for _ in range(timeout_cycles):
            after = await self.axi_activity_counts()
            if after[key] > before[key]:
                self.log.info("%s AXI activity before=%s after=%s", context, before, after)
                return after
            await self.wait_sys_cycles(1)
        after = await self.axi_activity_counts()
        raise AssertionError(
            f"{context}: expected {key.upper()} activity within {timeout_cycles} "
            f"cycles, before={before}, after={after}"
        )

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
