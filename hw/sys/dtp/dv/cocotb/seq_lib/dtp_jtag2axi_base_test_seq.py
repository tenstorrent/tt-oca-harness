# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""JTAG2AXI helper base sequence for DTP tests.

Each bridge is reached through its DTMCS and DMI TDRs: a DMI scan performs one
Debug Module register operation and captures the result of the one before it,
and the Debug Module's System Bus Access registers issue one bus beat per
access.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

import cocotb
from cocotb.utils import get_sim_time
from env.dtp_axi_port_history import DtpAxiPortHistory
from env.dtp_jtag2axi_model import strobe_lanes
from env.dtp_types import (
    DMI_LEN,
    DTP_EXPECTED_DTMCS,
    JTAG2AXI_TARGETS,
    RESET_COUNT_CHECK_ID,
    DtpDmiOp,
    DtpDmiStatus,
    DtpDmReg,
    DtpJtag2AxiTargetCfg,
    get_jtag2axi_target,
    pack_dmi,
    pack_sbcs,
    unpack_dmi,
    unpack_dtmcs,
    unpack_sbcs,
)
from ocah_axi_vip import (
    OcahAxiDelays,
    OcahAxiItem,
    OcahAxiLiteSlaveSequence,
    OcahAxiScoreboard,
    OcahAxiSlaveSequence,
)
from ocah_checker import OcahChecker
from ocah_jtag_vip import OcahJtagChecker
from ocah_lib import OcahKnobs

from .dtp_base_test_seq import dtp_base_test_seq

GEOMETRY_CHECK_ID = "CHK-J2A-GEOMETRY"
FAULT_STATUS_CHECK_ID = "CHK-J2A-FAULT-STATUS"
DTM_CAPTURE_CHECK_ID = "CHK-J2A-DTM-CAPTURE"
BUS_REQ_CHECK_ID = "CHK-J2A-BUS-REQ"
AXI_ATTR_CHECK_ID = "CHK-J2A-AXI-ATTR"
ONE_XFER_CHECK_ID = "CHK-J2A-ONE-XFER"
RDATA_CHECK_ID = "CHK-AXI-RDATA"
WMEM_CHECK_ID = "CHK-AXI-WMEM"
COMPLETION_CHECK_ID = "CHK-AXI-COMPLETION"
GEOMETRY_NEGATIVE_KNOB = "DTP_J2A_GEOMETRY_NEGATIVE"
BUS_REQ_NEGATIVE_KNOB = "DTP_J2A_BUS_REQ_NEGATIVE"
AXI_ATTR_NEGATIVE_KNOB = "DTP_J2A_AXI_ATTR_NEGATIVE"
ONE_XFER_NEGATIVE_KNOB = "DTP_J2A_ONE_XFER_NEGATIVE"
# The AxCACHE of every request the AXI4 bridge drives.
J2A_AXI_CACHE = 0b0010
# AxBURST INCR.
_AXI_BURST_INCR = 1
FAULT_STATUS_NEGATIVE_KNOB = "DTP_J2A_FAULT_STATUS_NEGATIVE"
DTM_CAPTURE_NEGATIVE_KNOB = "DTP_J2A_DTM_CAPTURE_NEGATIVE"
# System cycles a port transaction has to complete in once its access started.
PORT_COMPLETION_CYCLES = 200
# sbcs reads a bus access has to clear sbbusy in.
SBA_POLLS = 8
# TCK cycles in Run-Test/Idle after a raw DMI scan, beyond DTP_DMI_SETTLE_TCK,
# so the next scan finds its operation complete.
RAW_SCAN_IDLE_TCK = 64
DTMCS_DMIRESET = 1 << 16
DTMCS_DMIHARDRESET = 1 << 17
_DTMCS_DMISTAT_LSB = 10
_WORD = 0xFFFF_FFFF


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
    """DMI and System Bus Access helpers for DTP JTAG2AXI tests."""

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
        """Compare each bridge's DTMCS and sbcs geometry with ``JTAG2AXI_TARGETS``.

        DTMCS publishes the DMI version, address width and idle hint; with the
        Debug Module active, sbcs publishes the SBA version, address width and
        access sizes. Records ``CHK-J2A-GEOMETRY`` per bridge and fails the
        pass on a mismatch, before any bus access is packed with the table's
        widths. ``DTP_J2A_GEOMETRY_NEGATIVE=1`` corrupts the expected address
        width, so the run must fail.
        """
        checker = OcahJtagChecker(
            name=f"{self.get_name()}.geometry",
            raise_on_error=False,
            required_ids={GEOMETRY_CHECK_ID},
            logger=cocotb.log,
        )
        if OcahKnobs.is_set(GEOMETRY_NEGATIVE_KNOB):
            self.log.warning("NEGATIVE VALIDATION: geometry gate expectations will be corrupted")
        await self.reset_tap()
        for cfg in JTAG2AXI_TARGETS.values():
            dtmcs = await self.read_tdr(cfg.dtmcs_reg)
            await self.activate_dm(cfg.name)
            sbcs = await self.dmi_read(cfg.name, DtpDmReg.SBCS, context="geometry")
            self.log.info("GEOMETRY %s dtmcs=0x%08x sbcs=0x%08x", cfg.name, dtmcs, sbcs)
            checker.expect_equal(
                GEOMETRY_CHECK_ID,
                {"dtmcs": dtmcs, **self.sbcs_geometry(sbcs)},
                {"dtmcs": DTP_EXPECTED_DTMCS, **self.expected_geometry(cfg.name)},
                context=f"{cfg.name} DTMCS and sbcs geometry",
            )
        checker.finalize()

    @staticmethod
    def sbcs_geometry(sbcs: int) -> dict[str, object]:
        """The geometry fields of an ``sbcs`` value: the SBA version, address width and
        access sizes."""
        fields = unpack_sbcs(sbcs)
        return {
            "sbversion": fields["sbversion"],
            "sbasize": fields["sbasize"],
            "sbaccess": [fields[f"sbaccess{bits}"] for bits in (128, 64, 32, 16, 8)],
        }

    def expected_geometry(self, target: str) -> dict[str, object]:
        """The ``sbcs`` geometry of ``target`` in ``JTAG2AXI_TARGETS``.

        ``DTP_J2A_GEOMETRY_NEGATIVE=1`` corrupts the expected address width, so
        the run must fail.
        """
        cfg = self.target_cfg(target)
        return {
            "sbversion": 1,
            "sbasize": cfg.addr_width ^ int(OcahKnobs.is_set(GEOMETRY_NEGATIVE_KNOB)),
            "sbaccess": [int(cfg.data_width >= bits) for bits in (128, 64, 32, 16, 8)],
        }

    def check_sbcs_geometry(self, target: str, sbcs: int, *, context: str) -> None:
        """``CHK-J2A-GEOMETRY`` on one ``sbcs`` read of an active Debug Module."""
        self.check_equal(
            self.target_evidence(target),
            GEOMETRY_CHECK_ID,
            self.sbcs_geometry(sbcs),
            self.expected_geometry(target),
            context=f"{context} target={target} sbcs=0x{sbcs:08x}",
        )

    # --- DMI access ------------------------------------------------------------
    async def dmi_scan(
        self,
        target: str,
        address: int,
        data: int,
        op: DtpDmiOp,
        *,
        context: str,
        status: DtpDmiStatus = DtpDmiStatus.SUCCESS,
    ) -> int:
        """One DMI scan of ``{address, data, op}``; returns the captured data.

        The capture carries the sticky status, which ``CHK-J2A-FAULT-STATUS``
        compares with ``status``.
        """
        captured = await self.read_tdr(self.target_cfg(target).dmi_reg, pack_dmi(address, data, op))
        _, captured_data, captured_status = unpack_dmi(captured)
        self.check_dmi_status(
            target, captured_status, status, context=f"{context} dmi_capture=0x{captured:x}"
        )
        return captured_data

    def check_dmi_status(
        self, target: str, observed: int, expected: DtpDmiStatus, *, context: str
    ) -> None:
        """``CHK-J2A-FAULT-STATUS`` on a captured DMI status or DTMCS ``dmistat``.

        ``DTP_J2A_FAULT_STATUS_NEGATIVE=1`` swaps the expected status between
        success and busy, so the run must fail.
        """
        if OcahKnobs.is_set(FAULT_STATUS_NEGATIVE_KNOB):
            expected = DtpDmiStatus(int(expected) ^ int(DtpDmiStatus.BUSY))
        self.check_equal(
            self.target_evidence(target),
            FAULT_STATUS_CHECK_ID,
            observed,
            int(expected),
            context=f"{context} target={target} status",
        )

    def check_dtm_capture(self, target: str, observed: int, expected: int, *, context: str) -> None:
        """``CHK-J2A-DTM-CAPTURE`` on a capture without its status: a DMI capture's address
        and data, or a DTMCS capture's other fields.

        ``DTP_J2A_DTM_CAPTURE_NEGATIVE=1`` flips the expected bit 0, so the run
        must fail.
        """
        if OcahKnobs.is_set(DTM_CAPTURE_NEGATIVE_KNOB):
            expected ^= 0x1
        self.check_equal(
            self.target_evidence(target),
            DTM_CAPTURE_CHECK_ID,
            observed,
            expected,
            context=f"{context} target={target} observed=0x{observed:x} expected=0x{expected:x}",
        )

    async def dtmcs_scan(
        self, target: str, shift_value: int, *, status: DtpDmiStatus, context: str
    ) -> int:
        """One DTMCS scan shifting ``shift_value``; judges the captured fields and dmistat."""
        captured = await self.read_tdr(self.target_cfg(target).dtmcs_reg, shift_value)
        dmistat = unpack_dtmcs(captured)["dmistat"]
        self.check_dmi_status(target, dmistat, status, context=f"{context}.dmistat")
        self.check_dtm_capture(
            target,
            captured & ~(0x3 << _DTMCS_DMISTAT_LSB),
            DTP_EXPECTED_DTMCS,
            context=f"{context}.dtmcs",
        )
        return captured

    # --- raw DMI scans -----------------------------------------------------------
    async def select_dmi(self, target: str) -> None:
        """Load ``target``'s DMI instruction and stop in Run-Test/Idle."""
        await self.load_ir(self.target_cfg(target).dmi_instr)

    async def dmi_raw(
        self,
        target: str,
        address: int,
        data: int,
        op: DtpDmiOp,
        *,
        status: DtpDmiStatus,
        context: str,
        expect: tuple[int, int] | None = None,
        chain: bool = False,
    ) -> None:
        """One DMI scan of ``{address, data, op}`` under the loaded DMI instruction.

        From Run-Test/Idle or Select-DR-Scan; ends in Select-DR-Scan with
        ``chain`` and in Run-Test/Idle otherwise, with no idle cycles. Judges
        the captured status against ``status`` and, given ``expect``, the
        captured (address, data) against it.
        """
        item = await self.shift_dr(pack_dmi(address, data, op), DMI_LEN, back_to_rti=not chain)
        captured = item.result
        cap_address, cap_data, cap_status = unpack_dmi(captured)
        context = f"{context} op={op.name} dmi_capture=0x{captured:x}"
        self.check_dmi_status(target, cap_status, status, context=context)
        if expect is not None:
            self.check_dtm_capture(
                target,
                pack_dmi(cap_address, cap_data, 0) >> 2,
                pack_dmi(expect[0], expect[1], 0) >> 2,
                context=context,
            )

    async def dmi_zero_shift(self, *, chain: bool = False) -> None:
        """A DMI scan from Select-DR-Scan that shifts no bit, so its update loads its capture.

        Ends in Select-DR-Scan with ``chain`` and in Run-Test/Idle otherwise.
        """
        for tms in (0, 1, 1, int(chain)):
            await self.tms_step(tms)

    async def run_test_idle(self, cycles: int = RAW_SCAN_IDLE_TCK) -> None:
        """Clock ``cycles`` TCK cycles in Run-Test/Idle."""
        for _ in range(cycles):
            await self.tms_step(0)

    async def dmi_write(self, target: str, address: DtpDmReg, data: int, *, context: str) -> None:
        """Write one Debug Module register."""
        await self.dmi_scan(target, address, data, DtpDmiOp.WRITE, context=context)

    async def dmi_read(self, target: str, address: DtpDmReg, *, context: str) -> int:
        """Read one Debug Module register: the read, then a NOP scan that captures its data."""
        await self.dmi_scan(target, address, 0, DtpDmiOp.READ, context=context)
        return await self.dmi_scan(target, 0, 0, DtpDmiOp.NOP, context=f"{context}.fetch")

    async def activate_dm(self, target: str) -> None:
        """Set dmactive, which releases the System Bus Access registers from reset."""
        await self.dmi_write(target, DtpDmReg.DMCONTROL, 0x1, context="activate_dm")

    # --- System Bus Access -------------------------------------------------------
    async def sba_setup(
        self,
        target: str,
        addr: int,
        size: int,
        *,
        read: bool,
        context: str,
        autoincrement: bool = False,
    ) -> None:
        """Program sbcs for ``size`` accesses, then sbaddress; with ``read`` the
        sbaddress0 write starts the read."""
        await self.dmi_write(
            target,
            DtpDmReg.SBCS,
            pack_sbcs(sbreadonaddr=int(read), sbaccess=size, sbautoincrement=int(autoincrement)),
            context=f"{context}.sbcs",
        )
        addr = self.masked_addr(target, addr)
        if self.target_cfg(target).addr_width > 32:
            await self.dmi_write(
                target, DtpDmReg.SBADDRESS1, addr >> 32, context=f"{context}.sbaddress1"
            )
        await self.dmi_write(
            target, DtpDmReg.SBADDRESS0, addr & _WORD, context=f"{context}.sbaddress0"
        )

    async def wait_sba_idle(
        self, target: str, *, context: str, sbbusyerror: int = 0, sberror: int = 0
    ) -> None:
        """Poll sbcs until sbbusy clears, then require sberror ``sberror`` and
        sbbusyerror ``sbbusyerror``.

        ``CHK-AXI-COMPLETION`` judges the ``SBA_POLLS`` bound and
        ``CHK-J2A-FAULT-STATUS`` the two error fields.
        """
        start_ns = get_sim_time("ns")
        for _ in range(SBA_POLLS):
            sbcs = unpack_sbcs(await self.dmi_read(target, DtpDmReg.SBCS, context=context))
            if not sbcs["sbbusy"]:
                break
        self.check_completed(
            target,
            not sbcs["sbbusy"],
            timeout_ns=get_sim_time("ns") - start_ns,
            context=f"{context} sbcs polls={SBA_POLLS}",
        )
        self.check_equal(
            self.target_evidence(target),
            FAULT_STATUS_CHECK_ID,
            (sbcs["sberror"], sbcs["sbbusyerror"]),
            (sberror, sbbusyerror),
            context=f"{context} target={target} (sberror, sbbusyerror)",
        )

    async def sba_write(
        self, target: str, addr: int, data: int, *, size: int, context: str
    ) -> None:
        """Write ``data`` at ``addr`` through System Bus Access and judge the bus request."""
        await self.sba_setup(target, addr, size, read=False, context=context)
        await self.sba_write_data(target, addr, data, size=size, context=context)

    async def sba_write_data(
        self, target: str, addr: int, data: int, *, size: int, context: str, sberror: int = 0
    ) -> None:
        """Write ``data`` to sbdata, which starts the ``size`` write at ``addr``, the address
        sbaddress holds, and judge the bus request; the write ends with ``sberror``."""
        offset = addr % self.target_cfg(target).beat_bytes
        wstrb = self.full_wstrb(size) << offset
        if self.target_enabled(target):
            self.scoreboard_arm_strobes(target, wstrb, addr, context=context)
        data &= self.data_mask(size)
        if size == 3:
            await self.dmi_write(target, DtpDmReg.SBDATA1, data >> 32, context=f"{context}.sbdata1")
        await self.dmi_write(target, DtpDmReg.SBDATA0, data & _WORD, context=f"{context}.sbdata0")
        await self.wait_sba_idle(target, context=context, sberror=sberror)
        await self.expect_bus_request(
            target,
            read=False,
            addr=addr,
            size=size,
            data=data << (8 * offset),
            wstrb=wstrb,
            context=context,
        )

    async def sba_read(
        self, target: str, addr: int, *, size: int, context: str, autoincrement: bool = False
    ) -> int:
        """Read the ``size`` word at ``addr`` through System Bus Access and judge the bus request."""
        await self.sba_read_request(
            target, addr, size=size, context=context, autoincrement=autoincrement
        )
        data = await self.dmi_read(target, DtpDmReg.SBDATA0, context=f"{context}.sbdata0")
        if size == 3:
            data |= (
                await self.dmi_read(target, DtpDmReg.SBDATA1, context=f"{context}.sbdata1")
            ) << 32
        return data

    async def sba_read_request(
        self,
        target: str,
        addr: int,
        *,
        size: int,
        context: str,
        autoincrement: bool = False,
        sberror: int = 0,
    ) -> None:
        """Start the ``size`` read at ``addr`` with an sbaddress0 write and judge the bus
        request; the read ends with ``sberror``."""
        await self.sba_setup(
            target, addr, size, read=True, context=context, autoincrement=autoincrement
        )
        await self.wait_sba_idle(target, context=context, sberror=sberror)
        await self.expect_bus_request(target, read=True, addr=addr, size=size, context=context)

    async def read_sbaddress(self, target: str, *, context: str) -> int:
        """sbaddress over the bridge's address width."""
        value = await self.dmi_read(target, DtpDmReg.SBADDRESS0, context=f"{context}.sbaddress0")
        if self.target_cfg(target).addr_width > 32:
            value |= (
                await self.dmi_read(target, DtpDmReg.SBADDRESS1, context=f"{context}.sbaddress1")
            ) << 32
        return value

    def inject_bus_error(
        self, target: str, addr: int, resp: int, *, read: bool, context: str
    ) -> None:
        """The responder answers the next read, or with ``read`` False the next write, of the
        beat at ``addr`` with ``resp``, and the AXI scoreboard expects that response."""
        beat = self.target_cfg(target).beat_bytes
        aligned = self.masked_addr(target, addr) & ~(beat - 1)
        self.target_memory(target).inject_error(aligned, resp, read=read, write=not read)
        self.cfg.axi_models[target].expect_error(aligned, resp, read=read, write=not read)
        self.axi_scoreboard.arm_expected_resp(
            resp,
            address=aligned,
            direction="read" if read else "write",
            stream=target,
            context=f"{context} target={target}",
        )

    async def write_neighbour_then_read(
        self, target: str, addr: int, rng: random.Random, *, context: str
    ) -> tuple[int, int]:
        """Write a seeded word at ``addr`` and another at the next beat, then read ``addr`` back.

        The words differ, so a read that returns the first one read ``addr``.
        Every write is judged in the subordinate's memory and the read on the
        data the debugger fetches. Returns the data read and the word written
        at ``addr``.
        """
        cfg = self.target_cfg(target)
        size = cfg.default_size
        data = self.random_distinct_word(rng, target)
        other = self.random_distinct_word(rng, target, data)
        for word_addr, word, label in (
            (addr, data, "write"),
            (addr + cfg.beat_bytes, other, "neighbour"),
        ):
            await self.sba_write(target, word_addr, word, size=size, context=f"{context}.{label}")
            self.check_target_word(
                target, word_addr, word, size=size, context=f"{context}.{label}.mem"
            )
        rdata = await self.sba_read(target, addr, size=size, context=f"{context}.read")
        self.check_bridge_rdata(target, rdata, data, context=f"{context}.read")
        return rdata, data

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

    @staticmethod
    def target_cfg(target: str) -> DtpJtag2AxiTargetCfg:
        return get_jtag2axi_target(target)

    def target_enabled(self, target: str) -> bool:
        """Whether ``target``'s debug disable is clear, so its accesses reach the port."""
        return not self.cfg.tb_if.dbg_field(self.target_cfg(target).dbg_disable_bit)

    def target_memory(self, target: str) -> OcahAxiSlaveSequence | OcahAxiLiteSlaveSequence:
        cfg = self.target_cfg(target)
        memory = getattr(self.cfg, cfg.memory_attr)
        assert memory is not None, f"{cfg.memory_attr} is not ready"
        return memory

    def target_mem_size(self, target: str) -> int:
        return int(self.cfg.axi_mem_size if target == "smc_axi" else self.cfg.otp_axil_mem_size)

    def target_slot(self, target: str, addr: int) -> int:
        """The responder memory offset of ``addr``.

        Every responder stores an access at its address modulo its window.
        """
        return addr % self.target_mem_size(target)

    def masked_addr(self, target: str, addr: int) -> int:
        """``addr`` as the bridge's address register holds it."""
        return addr & ((1 << self.target_cfg(target).addr_width) - 1)

    def random_target_addr(self, target: str, rng: random.Random) -> int:
        """A seeded beat-aligned address: a responder slot under seeded upper address bits.

        The responder memory never sees the upper bits; ``CHK-J2A-BUS-REQ``
        judges them on the bus.
        """
        cfg = self.target_cfg(target)
        mem = self.target_mem_size(target)
        upper = rng.getrandbits(cfg.addr_width - (mem.bit_length() - 1)) << (mem.bit_length() - 1)
        return upper | (rng.randrange(mem // cfg.beat_bytes) * cfg.beat_bytes)

    def random_distinct_word(self, rng: random.Random, target: str, *avoid: int) -> int:
        """A seeded data-width word, nonzero and different from every ``avoid`` word."""
        width = self.target_cfg(target).data_width
        excluded = {0, *(int(word) & ((1 << width) - 1) for word in avoid)}
        while True:
            word = rng.getrandbits(width)
            if word not in excluded:
                return word

    # --- shared-VIP AXI scoreboard glue ---------------------------------------
    @property
    def axi_scoreboard(self) -> OcahAxiScoreboard:
        """The shared OcahAxiScoreboard every JTAG2AXI test enables."""
        scoreboard = self.cfg.axi_scoreboard
        if scoreboard is None:
            raise RuntimeError(f"{self.get_name()} needs use_axi_scoreboard = True in its test")
        return scoreboard

    def target_evidence(self, target: str) -> OcahChecker | OcahAxiScoreboard:
        """The recorder of the sequence's judgements of ``target``: the bridge's own
        checker when the test names per-bridge IDs, else the shared scoreboard."""
        checker = self.cfg.axi_target_evidence.get(target)
        return checker if checker is not None else self.axi_scoreboard

    def check_bridge_rdata(
        self, target: str, observed: int, expected: int, *, context: str
    ) -> None:
        """CHK-AXI-RDATA: the data the debugger fetched from the bridge."""
        self.check_equal(
            self.axi_scoreboard,
            RDATA_CHECK_ID,
            observed,
            expected,
            context=f"{context} target={target} source=bridge_capture",
        )

    def check_target_word(
        self, target: str, addr: int, expected: int, *, size: int, context: str
    ) -> None:
        """CHK-AXI-WMEM: the subordinate word at ``addr`` equals ``expected``, taken from the stimulus."""
        nbytes = self.size_bytes(size)
        if not self.axi_scoreboard.check_memory(
            dut_bytes=bytes(
                self.target_memory(target).read(self.target_slot(target, addr), nbytes)
            ),
            address=addr,
            length=nbytes,
            stream=target,
            context=f"{context} target={target}",
            expected=(expected & self.data_mask(size)).to_bytes(nbytes, "little"),
        ):
            raise AssertionError(f"{WMEM_CHECK_ID} FAIL: {context} target={target}")

    def scoreboard_arm_strobes(self, target: str, wstrb: int, addr: int, *, context: str) -> None:
        """Arm the intent write strobes for the next observed write."""
        beat = self.target_cfg(target).beat_bytes
        self.axi_scoreboard.arm_expected_strobes(
            (wstrb,),
            address=addr - (addr % beat),
            stream=target,
            context=f"{context} target={target} source=stimulus-wstrb",
        )

    def check_completed(self, target: str, done: bool, *, timeout_ns: float, context: str) -> None:
        """CHK-AXI-COMPLETION: a wait on ``target`` ended within ``timeout_ns``."""
        if not self.axi_scoreboard.expect_not_timed_out(
            COMPLETION_CHECK_ID,
            timed_out=not done,
            timeout_ns=float(timeout_ns),
            context=f"{context} target={target}",
        ):
            raise AssertionError(f"{COMPLETION_CHECK_ID} FAIL: {context} target={target}")

    def check_reset_counted(self, counter: str, before: int, after: int, context: str) -> None:
        """``CHK-RESET-COUNT`` on the shared AXI scoreboard."""
        self.check_equal(
            self.axi_scoreboard,
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

    def expect_no_bus_request(self, target: str, *, context: str) -> None:
        """CHK-J2A-BUS-REQ: the port holds the counts of the pass's last judged access.

        A no-op unless this pass's ledger accounts ``target``.
        """
        ledger = self._bus_ledger
        if ledger is None or ledger.target != target:
            return
        self._check_bus_counts(target, (ledger.writes, ledger.reads), context=context)

    def _check_bus_counts(self, target: str, expected: tuple[int, int], *, context: str) -> None:
        """Record the port's write and read counts against ``expected``; raise on a mismatch."""
        observed = self.port_history(target).counts()
        self._record_bus_fields(
            target,
            [("writes", observed[0], expected[0]), ("reads", observed[1], expected[1])],
            context=context,
        )

    def _record_bus_fields(
        self,
        target: str,
        fields: list[tuple[str, int, int]],
        *,
        context: str,
        check_id: str = BUS_REQ_CHECK_ID,
    ) -> None:
        """Record every (field, observed, expected) under ``check_id``, then raise on a mismatch."""
        failed = [
            field
            for field, observed, expected in fields
            if not self.axi_scoreboard.expect_equal(
                check_id,
                observed,
                expected,
                context=f"{context} target={target} field={field}",
            )
        ]
        if failed:
            raise AssertionError(f"{check_id} FAIL: {context} target={target} {failed}")

    async def wait_port_completion(self, target: str, *, read: bool, above: int) -> bool:
        """Wait until the port completes a transaction of one direction beyond ``above``.

        The monitor completes a write at its B and a read at its last R, so
        the transaction's effect on the subordinate is final. Returns False
        when none completes within ``PORT_COMPLETION_CYCLES`` system cycles.
        """
        history = self.port_history(target)
        for _ in range(PORT_COMPLETION_CYCLES):
            if history.count(read=read) > above:
                return True
            await self.wait_sys_cycles(1)
        return history.count(read=read) > above

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
        """CHK-J2A-BUS-REQ: the access just issued completed exactly one transaction, the one it requested.

        Against the stimulus: the port's exact write and read counts, the
        address over the full bridge width, a single beat, the AXI4 size, and
        for a write the strobes and the strobed data, ``data`` and ``wstrb``
        being the bus lanes the request drives. A no-op unless this pass's ledger
        accounts ``target``. ``DTP_J2A_BUS_REQ_NEGATIVE=1`` corrupts the
        expected address, so the run must fail. The same transaction's
        attributes are then judged under CHK-J2A-AXI-ATTR.
        """
        ledger = self._bus_ledger
        if ledger is None or ledger.target != target:
            return
        await self.wait_port_completion(target, read=read, above=ledger.count(read=read))
        self._check_bus_counts(target, ledger.account(read=read), context=context)
        item = self.port_history(target).last(read=read)
        expected_addr = self.masked_addr(target, addr)
        if OcahKnobs.is_set(BUS_REQ_NEGATIVE_KNOB):
            expected_addr ^= 0x4
        fields = [("address", item.address, expected_addr), ("beats", item.beat_count, 1)]
        if self.target_cfg(target).bus_type == 0:  # AXI4; AXI4-Lite carries no AxSIZE
            fields.append(("size", item.size, size))
        if not read:
            lanes = strobe_lanes(wstrb)
            fields.append(("strobes", item.strobes[0] if item.strobes else -1, wstrb))
            fields.append(("data", item.first_data & lanes, data & lanes))
        self._record_bus_fields(target, fields, context=context)
        self._check_axi_attrs(target, item, read=read, context=context)

    def _check_axi_attrs(self, target: str, item: OcahAxiItem, *, read: bool, context: str) -> None:
        """CHK-J2A-AXI-ATTR: the request's transfer attributes.

        Every bridge drives AxPROT 0; the AXI4 bridge also one INCR beat with
        AxCACHE 0b0010 and AxID, AxUSER and WUSER 0.
        ``DTP_J2A_AXI_ATTR_NEGATIVE=1`` flips the expected AxPROT bit 0, so the
        run must fail.
        """
        expected_prot = 0x1 if OcahKnobs.is_set(AXI_ATTR_NEGATIVE_KNOB) else 0
        fields = [("prot", item.prot, expected_prot)]
        if self.target_cfg(target).bus_type == 0:  # AXI4
            fields += [
                ("len", item.metadata.get("expected_beats", 0) - 1, 0),
                ("burst", item.burst, _AXI_BURST_INCR),
                ("cache", item.cache, J2A_AXI_CACHE),
                ("id", item.transaction_id, 0),
                ("user", item.user, 0),
            ]
            if not read:
                fields.append(("wuser", item.wusers[0] if item.wusers else -1, 0))
        self._record_bus_fields(target, fields, context=context, check_id=AXI_ATTR_CHECK_ID)

    # --- responder timing and one transfer at a time --------------------------
    def apply_responder_timing(
        self,
        target: str,
        *,
        aw: OcahAxiDelays,
        w: OcahAxiDelays,
        ar: OcahAxiDelays,
        b: OcahAxiDelays,
        r: OcahAxiDelays,
    ) -> None:
        """Stall ``target``'s responder READY on AW, W and AR, and delay its B and R,
        each channel from its own seeded stream."""
        responder = self.target_memory(target)
        for channel, stalls in (("aw", aw), ("w", w), ("ar", ar)):
            responder.enable_random_backpressure(channels=[channel], stalls=stalls)
        responder.set_response_delay(b, read=False, write=True)
        responder.set_response_delay(r, read=True, write=False)

    def clear_responder_timing(self, target: str) -> None:
        """Return ``target``'s responder to READY high and immediate responses."""
        responder = self.target_memory(target)
        responder.disable_backpressure()
        responder.clear_response_delay()

    def open_request_count(self, target: str) -> int:
        """Cycles in which ``target``'s port raised AWVALID or ARVALID while an
        accepted request awaited its last response."""
        prefix = self.target_cfg(target).activity_prefix
        return self.cfg.tb_if.sample(f"{prefix}_open_request_count")

    def check_one_transfer(self, target: str, since: int, *, context: str) -> None:
        """CHK-J2A-ONE-XFER: ``target``'s port raised no request while one was open
        since ``open_request_count`` read ``since``.

        ``DTP_J2A_ONE_XFER_NEGATIVE=1`` expects one such cycle, so the run must
        fail.
        """
        expected = 1 if OcahKnobs.is_set(ONE_XFER_NEGATIVE_KNOB) else 0
        self.check_equal(
            self.target_evidence(target),
            ONE_XFER_CHECK_ID,
            self.open_request_count(target) - since,
            expected,
            context=f"{context} target={target} requests_while_open",
        )
