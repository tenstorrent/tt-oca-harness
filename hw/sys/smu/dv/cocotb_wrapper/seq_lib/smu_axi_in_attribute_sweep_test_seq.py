# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Inbound AW/AR attribute sweep on the SMN port, and one outbound write.

``hw/ip/axi_filter/doc/index.adoc`` "Match, Then Permit" lists every condition
an inbound filter entry evaluates: ``entry_enabled``, the address range after
granule widening, ``prot[1] == allow_ns``, the source ID, and
``allow_burst = 1 or AxLEN = 0``. ``AxREGION``, ``AxQOS``, ``AxCACHE``,
``AxLOCK``, ``AxSIZE`` and ``AxBURST`` are not among them, so an entry that
admits a transaction admits it at every value of those fields. The same
chapter fixes what a denial looks like: the transaction is steered to an AXI
error subordinate that answers ``DECERR``, and ``hw/sys/smc/doc/fabric.adoc``
makes unmatched inbound traffic blocked.

S1: with one entry matching secure and one matching non-secure traffic over
    the probe page, all eight AxPROT encodings are admitted on AR and on AW.
    Only ``prot[1]`` takes part in the match, so ``prot[0]`` and ``prot[2]``
    cannot change the outcome.
S2: AxREGION, AxQOS and AxCACHE at 0x0 and 0xF and AxLOCK at 0 and 1 leave
    the response and the data unchanged, on AR and on AW.
S3: AxSIZE 0..3 on the 64-bit port each return the byte slice of the
    VERSION_LO RDL reset value that the size selects.
S4: with ``allow_burst = 0`` the granule is the 8-byte data bus and only
    single-beat transfers match, so AxLEN 0xFF, 0xAA and 0x55 are denied with
    DECERR while AxLEN 0 at the same address is admitted.
S5: under the same entries the denial is independent of AxBURST: FIXED, INCR
    and WRAP multi-beat transfers are all denied.
S6: shrinking SMC BASE_CONFIG.REGION_SIZE puts the adopter external window
    outside the local aperture, so a JTAG2AXI write to it leaves the chiplet
    on ``smu_axi_out``. The bench responder's memory must hold the written
    word and the B response must come back OKAY through the chiplet.
S7: REGION_SIZE written back to its reset value regrows the aperture, reaches
    ``smc_region_size_o`` and reads back. REGION_SIZE at zero is not driven: the
    crossbar rule it produces has ``start == end``, which the address decoder's
    own map check rejects (``addr_decode_dync`` ``check_start`` accepts only
    ``start < end`` or ``end == 0``), so whether a zero window is a legal state
    is a design question the coverage policy carries.

AxATOP is not driven: ``tb/tb_wrapper_top.sv`` ties ``smu_axi_in_req.aw.atop``
to ``'0`` and the package has no ATOP driver, so this leaf makes no ATOP
claim. AxSIZE[2] is not driven either: 8 bytes is the whole 64-bit beat, so a
larger AxSIZE is not a legal AXI4 transfer on this port.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge, with_timeout
from ocah_axi_vip import PROT_NONSECURE, RESP_OKAY, resp_name, worst_resp
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import (
    SMC_CHIP_CONFIG_VERSION_LO,
    SMC_CHIP_CONFIG_VERSION_LO_RESET,
    filter_ctrl_bm,
    filter_ctrl_field_reset_encode,
    smc_addr,
    smc_indexed_addr,
)
from seq_lib.smu_axi_helpers import AXI_TIMEOUT_NS, make_smu_axi_master
from seq_lib.smu_boundary_regs import smc_base_config_u32
from seq_lib.smu_filter_helpers import (
    page_align_window,
    program_smc_aperture_local_alias,
)
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    J2A_STATUS_SUCCESS,
    SMC_DBG_AXSIZE_4B,
    jtag2axi_single_read,
    jtag2axi_single_write,
    make_smu_jtag_tap,
    require_jtag_tdo_resolved,
)
from seq_lib.smu_tb_pins import smc_primary_reset, smu_axi_in_prefix

VERSION_LO = SMC_CHIP_CONFIG_VERSION_LO
VERSION_LO_RESET = SMC_CHIP_CONFIG_VERSION_LO_RESET
SCRATCH_COLD = smc_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_BASE_ADDR")

_IN_CFG = "SMC_TOP_SMC_INBOUND_FILTER_CTRL_FILTER_CONFIG_BASE_ADDR"
_IN_START = "SMC_TOP_SMC_INBOUND_FILTER_CTRL_START_ADDR_BASE_ADDR"
_IN_END = "SMC_TOP_SMC_INBOUND_FILTER_CTRL_END_ADDR_BASE_ADDR"

_F_READ = filter_ctrl_bm("FILTER_CTRL__FILTER_CONFIG__READ_ALLOWED_bm")
_F_WRITE = filter_ctrl_bm("FILTER_CTRL__FILTER_CONFIG__WRITE_ALLOWED_bm")
_F_ENTRY = filter_ctrl_bm("FILTER_CTRL__FILTER_CONFIG__ENTRY_ENABLED_bm")
_F_ALLOW_NS = filter_ctrl_bm("FILTER_CTRL__FILTER_CONFIG__ALLOW_NS_bm")
_F_ALLOW_BURST = filter_ctrl_bm("FILTER_CTRL__FILTER_CONFIG__ALLOW_BURST_bm")
_F_BUS_WIDTH_64 = filter_ctrl_field_reset_encode("DATA_BUS_WIDTH")
_CFG_CMP_MASK = (
    _F_READ
    | _F_WRITE
    | _F_ENTRY
    | _F_ALLOW_NS
    | _F_ALLOW_BURST
    | filter_ctrl_bm("FILTER_CTRL__FILTER_CONFIG__DATA_BUS_WIDTH_bm")
)

# Burst-capable pair over the probe page: one entry per prot[1] polarity.
CFG_BURST_SECURE = _F_READ | _F_WRITE | _F_ENTRY | _F_BUS_WIDTH_64 | _F_ALLOW_BURST
CFG_BURST_NS = CFG_BURST_SECURE | _F_ALLOW_NS
# Single-beat pair: allow_burst=0 narrows the granule to the 8-byte data bus
# and drops every AxLEN != 0 out of the match.
CFG_SINGLE_NS = _F_READ | _F_WRITE | _F_ENTRY | _F_BUS_WIDTH_64 | _F_ALLOW_NS

# hw/ip/axi_filter/doc/index.adoc, "Address Range Granule": allow_burst=0
# ignores address bits [2:0].
SINGLE_GRANULE_MASK = 0x7

PROT_LABELS = {
    0x0: "Data,Secure,User",
    0x1: "Data,Secure,Privileged",
    0x2: "Data,NonSecure,User",
    0x3: "Data,NonSecure,Privileged",
    0x4: "Instruction,Secure,User",
    0x5: "Instruction,Secure,Privileged",
    0x6: "Instruction,NonSecure,User",
    0x7: "Instruction,NonSecure,Privileged",
}

# AxREGION / AxQOS / AxCACHE walk every bit of their 4-bit field in one pair of
# values; AxLOCK is one bit.
QUALIFIER_CELLS = (
    ("region", 0x0),
    ("region", 0xF),
    ("qos", 0x0),
    ("qos", 0xF),
    ("cache", 0x0),
    ("cache", 0xF),
    ("lock", 0x0),
    ("lock", 0x1),
)

# AxSIZE 3 is the full 64-bit beat; 0..3 is every legal encoding on this port.
SIZE_CELLS = (0, 1, 2, 3)
# AxLEN values whose union walks [7:0] both ways.
LEN_CELLS = (0xFF, 0xAA, 0x55)
AXI_BURST_FIXED = 0
AXI_BURST_INCR = 1
AXI_BURST_WRAP = 2
# WRAP is legal only at 2, 4, 8 or 16 beats.
BURST_TYPE_BEATS = 4

SCRATCH_PROT_BASE = 0x5A00_0000
SCRATCH_QUAL_BASE = 0x5B00_0000
SCRATCH_SINGLE = 0x5C5C_A5A5
OUTBOUND_PATTERN = 0x5D5D_B6B6

FILTER_READY_POLLS = 64
FILTER_READY_STEP = 4
# clk_smu edges allowed for the outbound boundary counter to move.
EGRESS_POLL_CYCLES = 4000

REGION_SIZE_ADDR = smc_addr("SMC_TOP_SMC_BASE_CONFIG_REGION_SIZE_BASE_ADDR")
REGION_SIZE_RESET = smc_base_config_u32("SMC_BASE_CONFIG__REGION_SIZE__SIZE_reset")
LOCAL_BASE_RESET = smc_base_config_u32("SMC_BASE_CONFIG__LOCAL_BASE__BASE_reset")
# hw/sys/smc/doc/memmap.adoc, "AXI-Lite External Window": the window sits at
# SMC BASE + 0x040_0000 and passes what no block claims through to the adopter
# external port. Ending the local aperture at the window base makes it the
# first address the SMC routes out of the chiplet.
EXTERNAL_BASE = smc_addr("SMC_TOP_SMC_EXTERNAL_BASE_ADDR")
REGION_SIZE_SHRUNK = EXTERNAL_BASE - LOCAL_BASE_RESET
OUTBOUND_TARGET = EXTERNAL_BASE


def _require_probe_map() -> None:
    """Refuse to run if the probe addresses do not sit where the steps need them."""
    facts = (
        (VERSION_LO >> 12 == SCRATCH_COLD >> 12, "probe registers are not in one 4 KB granule"),
        (VERSION_LO % 8 == 0, "VERSION_LO is not 8-byte aligned"),
        (SCRATCH_COLD % 8 == 0, "SCRATCH_COLD is not 8-byte aligned"),
        (
            (VERSION_LO & 0xFFF) + max(LEN_CELLS) + 1 <= 0x1000,
            "the longest AxLEN read crosses the 4 KB boundary at VERSION_LO",
        ),
        (
            (SCRATCH_COLD & 0xFFF) + max(LEN_CELLS) + 1 <= 0x1000,
            "the longest AxLEN write crosses the 4 KB boundary at SCRATCH_COLD",
        ),
        (
            (VERSION_LO & ~SINGLE_GRANULE_MASK) != (SCRATCH_COLD & ~SINGLE_GRANULE_MASK),
            "the probe registers share one 8-byte granule",
        ),
        (
            REGION_SIZE_SHRUNK > 0
            and (REGION_SIZE_SHRUNK & (REGION_SIZE_SHRUNK - 1)) == 0
            and LOCAL_BASE_RESET % REGION_SIZE_SHRUNK == 0,
            "shrunk REGION_SIZE is not a power of two LOCAL_BASE is aligned to",
        ),
        (REGION_SIZE_SHRUNK < REGION_SIZE_RESET, "shrunk REGION_SIZE does not shrink the reset"),
        (OUTBOUND_TARGET % 8 == 0, "the outbound target is not 8-byte aligned"),
    )
    bad = [msg for ok, msg in facts if not ok]
    if bad:
        raise RuntimeError("attribute sweep probe map: " + "; ".join(bad))


_require_probe_map()


class _HandshakeCounter:
    """Handshakes on one channel of the inbound port, sampled on the DUT pins.

    The count is what the port took, not what the master queued, so a step
    that reports N cells is reconciled against N accepted address phases.
    """

    def __init__(self, dut, clk, channel: str) -> None:
        prefix = smu_axi_in_prefix(dut)
        pins = []
        for suffix in ("valid", "ready"):
            name = f"{prefix}_{channel}{suffix}"
            pin = getattr(dut, name, None)
            if pin is None:
                raise AssertionError(f"{name} unobservable on this tb_top")
            pins.append(pin)
        self._valid, self._ready = pins
        self._clk = clk
        self.count = 0
        self._task = cocotb.start_soon(self._watch())

    async def _watch(self) -> None:
        while True:
            await RisingEdge(self._clk)
            if str(self._valid.value) == "1" and str(self._ready.value) == "1":
                self.count += 1

    def take(self) -> int:
        """Return the count so far and restart from zero."""
        seen = self.count
        self.count = 0
        return seen

    def stop(self) -> None:
        if not self._task.done():
            self._task.cancel()


class _OutboundWriteWatcher:
    """One write transaction on the outbound boundary interface."""

    def __init__(self, dut) -> None:
        self._if = dut.u_axi_out_if
        self._clk = dut.clk_smu_i
        self.aw_addr: int | None = None
        self.last_wdata: int | None = None
        self.last_wstrb: int | None = None
        self.w_last_seen = False
        self.bresp: int | None = None
        self._task = cocotb.start_soon(self._watch())

    def _bit(self, name: str) -> bool:
        return str(getattr(self._if, name).value) == "1"

    def _int(self, name: str) -> int:
        val = getattr(self._if, name).value
        if not val.is_resolvable:
            raise AssertionError(f"X/Z on u_axi_out_if.{name}: {val}")
        return int(val)

    async def _watch(self) -> None:
        while True:
            await RisingEdge(self._clk)
            if self.aw_addr is None and self._bit("awvalid") and self._bit("awready"):
                self.aw_addr = self._int("awaddr")
            if self._bit("wvalid") and self._bit("wready"):
                self.last_wdata = self._int("wdata")
                self.last_wstrb = self._int("wstrb")
                if self._bit("wlast"):
                    self.w_last_seen = True
            if self.bresp is None and self._bit("bvalid") and self._bit("bready"):
                self.bresp = self._int("bresp")

    def stop(self) -> None:
        if not self._task.done():
            self._task.cancel()


class smu_axi_in_attribute_sweep_test_seq:
    """Inbound AW/AR attribute acceptance, and one SMC write out of the chiplet."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.s1_ok = False
        self.s2_ok = False
        self.s3_ok = False
        self.s4_ok = False
        self.s5_ok = False
        self.s6_ok = False
        self.s7_ok = False

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    def _sample_int(self, name: str) -> int:
        pin = getattr(self.dut, name, None)
        if pin is None:
            raise AssertionError(f"{name} unobservable on this tb_top")
        val = pin.value
        if not val.is_resolvable:
            raise AssertionError(f"X/Z on {name}: {val}")
        return int(val)

    # ------------------------------------------------------------------
    # Inbound AXI: the shared master with the optional qualifiers exposed.
    # ------------------------------------------------------------------

    async def _ax(self, master, *, write: bool, addr: int, label: str, payload=None, **attrs):
        """Drive one AXI transfer and return (resp, data) from the response.

        ``payload`` is the byte payload of a write and the transfer length in
        bytes of a read. ``attrs`` are the driver's AW/AR qualifier arguments
        -- ``prot``, ``lock``, ``cache``, ``qos``, ``region``, ``burst`` and
        ``size``; the blocking result API carries only ``burst``, ``prot`` and
        ``size``, so the sweep waits on the driver pass-through's event.
        """
        if write:
            event = master.init_write(addr, payload, **attrs)
        else:
            event = master.init_read(addr, payload, **attrs)
        try:
            await with_timeout(event.wait(), AXI_TIMEOUT_NS, "ns")
        except Exception as exc:
            raise AssertionError(
                f"TIMEOUT {label} addr=0x{addr:08x} attrs={attrs} bound={AXI_TIMEOUT_NS}ns: {exc}"
            ) from exc
        raw = event.data
        resp = worst_resp(getattr(raw, "resp", None))
        data = int.from_bytes(bytes(getattr(raw, "data", b"")), "little")
        return resp, data

    async def _read(self, master, addr: int, *, label: str, length: int = 4, **attrs):
        return await self._ax(master, write=False, addr=addr, payload=length, label=label, **attrs)

    async def _write(self, master, addr: int, value: int, *, label: str, **attrs):
        resp, _ = await self._ax(
            master,
            write=True,
            addr=addr,
            payload=int(value).to_bytes(4, "little"),
            label=label,
            **attrs,
        )
        return resp

    async def _await_resp(self, master, addr: int, want: int, *, label: str, **attrs) -> None:
        """Poll until the filter program has taken effect; fail-closed on expiry."""
        last = None
        for poll in range(FILTER_READY_POLLS):
            resp, _ = await self._read(master, addr, label=label, **attrs)
            last = resp
            if resp == want:
                self._log(f"FILTER_READY {label} want={resp_name(want)} poll={poll}")
                return
            await ClockCycles(self.dut.clk_smu_i, FILTER_READY_STEP)
        raise AssertionError(
            f"TIMEOUT FILTER_READY {label}: want={resp_name(want)} "
            f"last={resp_name(last) if last is not None else None} "
            f"polls={FILTER_READY_POLLS} step={FILTER_READY_STEP} addr=0x{addr:08x}"
        )

    # ------------------------------------------------------------------
    # JTAG2AXI: filter and aperture programming, and the outbound write.
    # ------------------------------------------------------------------

    async def _j2a_wr(self, jtag, addr: int, data: int, name: str, **kwargs) -> None:
        st, _ = await jtag2axi_single_write(jtag, addr, data, require_complete=True, **kwargs)
        require_jtag_tdo_resolved(f"J2A WR {name}")
        if st != J2A_STATUS_SUCCESS:
            raise AssertionError(f"J2A WR {name} @0x{addr:08x} status={st} want SUCCESS")

    async def _j2a_rd(self, jtag, addr: int, name: str, **kwargs) -> int:
        st, rdata = await jtag2axi_single_read(jtag, addr, require_complete=True, **kwargs)
        require_jtag_tdo_resolved(f"J2A RD {name}")
        if st != J2A_STATUS_SUCCESS:
            raise AssertionError(f"J2A RD {name} @0x{addr:08x} status={st} want SUCCESS")
        return int(rdata)

    async def _j2a_rd32(self, jtag, addr: int, name: str) -> int:
        """Read a 32-bit CSR; addr[2] selects the J2A 64-bit lane (see wdt_unlock)."""
        raw = await self._j2a_rd(jtag, addr, name, size=SMC_DBG_AXSIZE_4B)
        return (raw >> 32) & 0xFFFF_FFFF if addr & 0x4 else raw & 0xFFFF_FFFF

    async def _j2a_wr32(self, jtag, addr: int, data: int, name: str) -> None:
        word = int(data) & 0xFFFF_FFFF
        packed, wstrb = (word << 32, 0xF0) if addr & 0x4 else (word, 0x0F)
        await self._j2a_wr(jtag, addr, packed, name, wstrb=wstrb, size=SMC_DBG_AXSIZE_4B)

    async def _program_entry(self, jtag, inst: int, start: int, end: int, config: int, tag: str):
        await self._j2a_wr(jtag, smc_indexed_addr(_IN_START, inst), start, f"{tag}_START")
        await self._j2a_wr(jtag, smc_indexed_addr(_IN_END, inst), end, f"{tag}_END")
        await self._j2a_wr(jtag, smc_indexed_addr(_IN_CFG, inst), config, f"{tag}_CONFIG")
        rb = await self._j2a_rd(jtag, smc_indexed_addr(_IN_CFG, inst), f"{tag}_CONFIG_RB")
        if (rb & _CFG_CMP_MASK) != (config & _CFG_CMP_MASK):
            raise AssertionError(
                f"{tag} CONFIG readback want=0x{config:x} got=0x{rb:x} mask=0x{_CFG_CMP_MASK:x}"
            )

    async def _disable_entry(self, jtag, inst: int) -> None:
        await self._j2a_wr(jtag, smc_indexed_addr(_IN_CFG, inst), 0, f"DISABLE_I{inst}")

    async def _bring_up_tap(self, sb):
        dut = self.dut
        jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await jtag.reset_tap()
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await jtag.step_tms(0)
        idcode = await jtag.read_idcode()
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(f"IDCODE want 0x{DTP_DEFAULT_IDCODE:x} got 0x{idcode:08x}")
        gate = self._sample_int("tb_smc_jtag2axi_security_disable") & 1
        if gate != 0:
            raise AssertionError(f"SMC J2A still gated after TCK sync: security_disable={gate}")
        await program_smc_aperture_local_alias(jtag, scoreboard=sb)
        return jtag

    # ------------------------------------------------------------------
    # Steps.
    # ------------------------------------------------------------------

    async def _step_prot(self, master, sb, ar_count, aw_count) -> None:
        """S1: every AxPROT encoding is admitted when both polarities have an entry."""
        ar_count.take()
        aw_count.take()
        reads = {}
        writes = {}
        for prot in range(8):
            resp, data = await self._read(master, VERSION_LO, label=f"s1_rd_prot{prot}", prot=prot)
            reads[prot] = (resp_name(resp), data & 0xFFFF_FFFF)
            value = SCRATCH_PROT_BASE | prot
            wresp = await self._write(
                master, SCRATCH_COLD, value, label=f"s1_wr_prot{prot}", prot=prot
            )
            rb_resp, rb_data = await self._read(
                master, SCRATCH_COLD, label=f"s1_rb_prot{prot}", prot=prot
            )
            writes[prot] = (resp_name(wresp), resp_name(rb_resp), rb_data & 0xFFFF_FFFF)
            self._log(
                f"CHK-AXIIN-ATTR-PROT cell prot=0x{prot:x} {PROT_LABELS[prot]} "
                f"rd={reads[prot]} wr={writes[prot]}"
            )

        sb.expect_eq(
            "CHK-AXIIN-ATTR-PROT 8 of 8 AxPROT reads are OKAY with the VERSION_LO reset value",
            reads,
            {prot: ("OKAY", VERSION_LO_RESET) for prot in range(8)},
            evidence="CHK-AXIIN-ATTR-PROT",
        )
        sb.expect_eq(
            "CHK-AXIIN-ATTR-PROT 8 of 8 AxPROT writes are OKAY and land in SCRATCH_COLD",
            writes,
            {prot: ("OKAY", "OKAY", SCRATCH_PROT_BASE | prot) for prot in range(8)},
        )
        sb.expect_eq(
            "CHK-AXIIN-ATTR-PROT the port accepted 16 AR and 8 AW address phases",
            (ar_count.take(), aw_count.take()),
            (16, 8),
        )
        self.s1_ok = True

    async def _step_qualifiers(self, master, sb, ar_count, aw_count) -> None:
        """S2: AxREGION, AxQOS, AxCACHE and AxLOCK do not change the outcome."""
        ar_count.take()
        aw_count.take()
        reads = {}
        writes = {}
        for idx, (field, value) in enumerate(QUALIFIER_CELLS):
            cell = f"{field}=0x{value:x}"
            attrs = {field: value}
            resp, data = await self._read(master, VERSION_LO, label=f"s2_rd_{cell}", **attrs)
            reads[cell] = (resp_name(resp), data & 0xFFFF_FFFF)
            payload = SCRATCH_QUAL_BASE | idx
            wresp = await self._write(master, SCRATCH_COLD, payload, label=f"s2_wr_{cell}", **attrs)
            rb_resp, rb_data = await self._read(master, SCRATCH_COLD, label=f"s2_rb_{cell}")
            writes[cell] = (resp_name(wresp), resp_name(rb_resp), rb_data & 0xFFFF_FFFF)
            self._log(f"CHK-AXIIN-ATTR-QUAL cell {cell} rd={reads[cell]} wr={writes[cell]}")

        sb.expect_eq(
            "CHK-AXIIN-ATTR-QUAL 8 of 8 qualifier reads are OKAY with the VERSION_LO reset value",
            reads,
            {f"{f}=0x{v:x}": ("OKAY", VERSION_LO_RESET) for f, v in QUALIFIER_CELLS},
            evidence="CHK-AXIIN-ATTR-QUAL",
        )
        sb.expect_eq(
            "CHK-AXIIN-ATTR-QUAL 8 of 8 qualifier writes are OKAY and land in SCRATCH_COLD",
            writes,
            {
                f"{f}=0x{v:x}": ("OKAY", "OKAY", SCRATCH_QUAL_BASE | idx)
                for idx, (f, v) in enumerate(QUALIFIER_CELLS)
            },
        )
        sb.expect_eq(
            "CHK-AXIIN-ATTR-QUAL the port accepted 16 AR and 8 AW address phases",
            (ar_count.take(), aw_count.take()),
            (16, 8),
        )
        self.s2_ok = True

    async def _step_size(self, master, sb, ar_count) -> None:
        """S3: every legal AxSIZE returns the byte slice of VERSION_LO it selects."""
        ar_count.take()
        reads = {}
        for size in SIZE_CELLS:
            nbytes = 1 << size
            resp, data = await self._read(
                master, VERSION_LO, label=f"s3_rd_size{size}", length=nbytes, size=size
            )
            keep = min(nbytes, 4)
            reads[size] = (resp_name(resp), data & ((1 << (8 * keep)) - 1))
            self._log(f"CHK-AXIIN-ATTR-SIZE cell size={size} ({nbytes}B) {reads[size]}")

        sb.expect_eq(
            "CHK-AXIIN-ATTR-SIZE 4 of 4 AxSIZE reads return the VERSION_LO reset slice",
            reads,
            {
                size: ("OKAY", VERSION_LO_RESET & ((1 << (8 * min(1 << size, 4))) - 1))
                for size in SIZE_CELLS
            },
            evidence="CHK-AXIIN-ATTR-SIZE",
        )
        sb.expect_eq(
            "CHK-AXIIN-ATTR-SIZE the port accepted 4 AR address phases",
            ar_count.take(),
            len(SIZE_CELLS),
        )
        self.s3_ok = True

    async def _step_len(self, master, sb, ar_count, aw_count) -> None:
        """S4: with allow_burst=0 only AxLEN 0 matches; longer transfers are DECERR."""
        ar_count.take()
        aw_count.take()
        reads = {}
        writes = {}
        for length in LEN_CELLS:
            beats = length + 1
            resp, _ = await self._read(
                master,
                VERSION_LO,
                label=f"s4_rd_len0x{length:02x}",
                length=beats,
                size=0,
                prot=PROT_NONSECURE,
            )
            reads[length] = resp_name(resp)
            resp, _ = await self._ax(
                master,
                write=True,
                addr=SCRATCH_COLD,
                payload=bytes((SCRATCH_SINGLE >> 8 * (i % 4)) & 0xFF for i in range(beats)),
                label=f"s4_wr_len0x{length:02x}",
                size=0,
                prot=PROT_NONSECURE,
            )
            writes[length] = resp_name(resp)
            self._log(
                f"CHK-AXIIN-ATTR-LEN cell len=0x{length:02x} rd={reads[length]} wr={writes[length]}"
            )

        # Single-beat control at the same addresses under the same entries.
        ctrl_resp, ctrl_data = await self._read(
            master, VERSION_LO, label="s4_rd_len0", prot=PROT_NONSECURE
        )
        reads[0x00] = resp_name(ctrl_resp)
        wr_ctrl = await self._write(
            master, SCRATCH_COLD, SCRATCH_SINGLE, label="s4_wr_len0", prot=PROT_NONSECURE
        )
        writes[0x00] = resp_name(wr_ctrl)
        rb_resp, rb_data = await self._read(
            master, SCRATCH_COLD, label="s4_rb_len0", prot=PROT_NONSECURE
        )

        sb.expect_eq(
            "CHK-AXIIN-ATTR-LEN 3 of 3 burst AxLEN reads are DECERR and AxLEN 0 is OKAY",
            reads,
            {**{length: "DECERR" for length in LEN_CELLS}, 0x00: "OKAY"},
            evidence="CHK-AXIIN-ATTR-LEN",
        )
        sb.expect_eq(
            "CHK-AXIIN-ATTR-LEN 3 of 3 burst AxLEN writes are DECERR and AxLEN 0 is OKAY",
            writes,
            {**{length: "DECERR" for length in LEN_CELLS}, 0x00: "OKAY"},
        )
        sb.expect_eq(
            "CHK-AXIIN-ATTR-LEN the admitted AxLEN 0 read carries the VERSION_LO reset value",
            (ctrl_data & 0xFFFF_FFFF, resp_name(rb_resp), rb_data & 0xFFFF_FFFF),
            (VERSION_LO_RESET, "OKAY", SCRATCH_SINGLE),
        )
        sb.expect_eq(
            "CHK-AXIIN-ATTR-LEN the port accepted 5 AR and 4 AW address phases",
            (ar_count.take(), aw_count.take()),
            (len(LEN_CELLS) + 2, len(LEN_CELLS) + 1),
        )
        self.s4_ok = True

    async def _step_burst_type(self, master, sb, ar_count, aw_count) -> None:
        """S5: the single-beat entries deny a multi-beat transfer of any AxBURST."""
        ar_count.take()
        aw_count.take()
        reads = {}
        writes = {}
        for burst in (AXI_BURST_FIXED, AXI_BURST_INCR, AXI_BURST_WRAP):
            resp, _ = await self._read(
                master,
                VERSION_LO,
                label=f"s5_rd_burst{burst}",
                length=BURST_TYPE_BEATS,
                size=0,
                burst=burst,
                prot=PROT_NONSECURE,
            )
            reads[burst] = resp_name(resp)
            resp, _ = await self._ax(
                master,
                write=True,
                addr=SCRATCH_COLD,
                payload=bytes(range(BURST_TYPE_BEATS)),
                label=f"s5_wr_burst{burst}",
                size=0,
                burst=burst,
                prot=PROT_NONSECURE,
            )
            writes[burst] = resp_name(resp)
            self._log(
                f"CHK-AXIIN-ATTR-BURST cell burst={burst} rd={reads[burst]} wr={writes[burst]}"
            )

        denied = dict.fromkeys((AXI_BURST_FIXED, AXI_BURST_INCR, AXI_BURST_WRAP), "DECERR")
        sb.expect_eq(
            "CHK-AXIIN-ATTR-BURST 3 of 3 multi-beat AxBURST reads are DECERR",
            reads,
            denied,
            evidence="CHK-AXIIN-ATTR-BURST",
        )
        sb.expect_eq(
            "CHK-AXIIN-ATTR-BURST 3 of 3 multi-beat AxBURST writes are DECERR",
            writes,
            denied,
        )
        sb.expect_eq(
            "CHK-AXIIN-ATTR-BURST the port accepted 3 AR and 3 AW address phases",
            (ar_count.take(), aw_count.take()),
            (3, 3),
        )
        self.s5_ok = True

    async def _await_egress_write(self, baseline: int, label: str) -> int:
        last = baseline
        for _ in range(EGRESS_POLL_CYCLES):
            await RisingEdge(self.dut.clk_smu_i)
            last = self._sample_int("smu_axi_out_write_count_o")
            if last > baseline:
                return last
        raise AssertionError(
            f"TIMEOUT {label}: smu_axi_out_write_count_o stayed at {last} "
            f"(baseline {baseline}) for {EGRESS_POLL_CYCLES} clk_smu cycles"
        )

    async def _step_outbound_write(self, jtag, sb) -> None:
        """S6: an SMC write above the local aperture leaves the chiplet and is answered."""
        size_at_reset = await self._j2a_rd32(jtag, REGION_SIZE_ADDR, "REGION_SIZE")
        sb.expect_eq(
            "CHK-AXIOUT-WRITE REGION_SIZE reads its RDL reset value before the shrink",
            size_at_reset,
            REGION_SIZE_RESET,
        )
        await self._j2a_wr32(jtag, REGION_SIZE_ADDR, REGION_SIZE_SHRUNK, "REGION_SIZE_SHRINK")
        await ClockCycles(self.dut.clk_smu_i, 64)
        sb.expect_eq(
            "CHK-AXIOUT-WRITE the shrunk REGION_SIZE reaches the SMC broadcast port",
            self._sample_int("smc_region_size_o"),
            REGION_SIZE_SHRUNK,
        )

        baseline = self._sample_int("smu_axi_out_write_count_o")
        watcher = _OutboundWriteWatcher(self.dut)
        try:
            await self._j2a_wr32(jtag, OUTBOUND_TARGET, OUTBOUND_PATTERN, "OUTBOUND_WRITE")
            count = await self._await_egress_write(baseline, "s6_outbound_write")
            await ClockCycles(self.dut.clk_smu_i, 16)
        finally:
            watcher.stop()

        sb.expect_eq(
            "CHK-AXIOUT-WRITE exactly one write response crossed the outbound boundary",
            count,
            baseline + 1,
            evidence="CHK-AXIOUT-WRITE",
        )
        sb.expect_eq(
            "CHK-AXIOUT-WRITE the outbound port raised aw_valid, w_valid, w.last and b_valid",
            (
                self._sample_int("smu_axi_out_aw_valid_seen_o"),
                self._sample_int("smu_axi_out_aw_fired_seen_o"),
                self._sample_int("smu_axi_out_w_valid_seen_o"),
                self._sample_int("smu_axi_out_w_last_seen_o"),
                self._sample_int("smu_axi_out_b_valid_seen_o"),
                self._sample_int("smu_axi_out_first_aw_ctrl_x_o"),
            ),
            (1, 1, 1, 1, 1, 0),
        )
        sb.expect_true(
            "CHK-AXIOUT-WRITE the responder drove aw_ready and w_ready on the outbound port",
            self._sample_int("smu_axi_out_aw_ready_cycles_o") > 0
            and self._sample_int("smu_axi_out_w_ready_cycles_o") > 0,
        )
        sb.expect_eq(
            "CHK-AXIOUT-WRITE the write left the chiplet at the address the SMC was given",
            (watcher.aw_addr, watcher.w_last_seen, watcher.bresp),
            (OUTBOUND_TARGET, True, RESP_OKAY),
        )
        observed = self.cfg.axi_out_mem.read32(OUTBOUND_TARGET)
        sb.expect_eq(
            "CHK-AXIOUT-WRITE the bench responder holds the word the SMC wrote out",
            observed,
            OUTBOUND_PATTERN,
        )
        self._log(
            f"CHK-AXIOUT-WRITE: count {baseline}->{count} addr=0x{watcher.aw_addr:x} "
            f"wdata=0x{watcher.last_wdata:x} wstrb=0x{watcher.last_wstrb:x} "
            f"bresp={resp_name(watcher.bresp)} mem=0x{observed:08x}"
        )
        self.s6_ok = True

    async def _step_region_size_regrow(self, jtag, sb) -> None:
        """S7: REGION_SIZE regrown to its reset value after the shrink."""
        await self._j2a_wr32(jtag, REGION_SIZE_ADDR, REGION_SIZE_RESET, "REGION_SIZE_REGROW")
        await ClockCycles(self.dut.clk_smu_i, 64)
        sb.expect_eq(
            "CHK-SMCMAP-SIZE the regrown REGION_SIZE reaches the SMC broadcast port",
            self._sample_int("smc_region_size_o"),
            REGION_SIZE_RESET,
        )
        sb.expect_eq(
            "CHK-SMCMAP-SIZE REGION_SIZE reads back its reset value after the regrow",
            await self._j2a_rd32(jtag, REGION_SIZE_ADDR, "REGION_SIZE_REGROW_RB"),
            REGION_SIZE_RESET,
        )
        self._log(
            f"CHK-SMCMAP-SIZE: shrunk 0x{REGION_SIZE_SHRUNK:x} -> reset 0x{REGION_SIZE_RESET:x} "
            "on smc_region_size_o"
        )
        self.s7_ok = True

    async def run(self) -> None:
        dut = self.dut
        sb = self.test.env.scoreboard
        await self.cfg.reset_done.wait()
        await ClockCycles(dut.clk_smu_i, 16)

        jtag = await self._bring_up_tap(sb)
        master = await make_smu_axi_master(dut, dut.clk_smu_i, smc_primary_reset(dut))

        ar_count = _HandshakeCounter(dut, dut.clk_smu_i, "ar")
        aw_count = _HandshakeCounter(dut, dut.clk_smu_i, "aw")
        try:
            page_lo, page_hi = page_align_window(
                min(VERSION_LO, SCRATCH_COLD), max(VERSION_LO, SCRATCH_COLD)
            )
            await self._program_entry(jtag, 0, page_lo, page_hi, CFG_BURST_SECURE, "PAGE_SECURE")
            await self._program_entry(jtag, 1, page_lo, page_hi, CFG_BURST_NS, "PAGE_NS")
            await self._await_resp(
                master, VERSION_LO, RESP_OKAY, label="page_window_ready", prot=PROT_NONSECURE
            )

            await self._step_prot(master, sb, ar_count, aw_count)
            await self._step_qualifiers(master, sb, ar_count, aw_count)
            await self._step_size(master, sb, ar_count)

            await self._program_entry(
                jtag,
                0,
                VERSION_LO & ~SINGLE_GRANULE_MASK,
                VERSION_LO | SINGLE_GRANULE_MASK,
                CFG_SINGLE_NS,
                "SINGLE_RD",
            )
            await self._program_entry(
                jtag,
                1,
                SCRATCH_COLD & ~SINGLE_GRANULE_MASK,
                SCRATCH_COLD | SINGLE_GRANULE_MASK,
                CFG_SINGLE_NS,
                "SINGLE_WR",
            )
            await self._await_resp(
                master, VERSION_LO, RESP_OKAY, label="single_window_ready", prot=PROT_NONSECURE
            )

            await self._step_len(master, sb, ar_count, aw_count)
            await self._step_burst_type(master, sb, ar_count, aw_count)
        finally:
            ar_count.stop()
            aw_count.stop()

        await self._disable_entry(jtag, 1)
        await self._disable_entry(jtag, 0)
        await self._step_outbound_write(jtag, sb)
        await self._step_region_size_regrow(jtag, sb)
