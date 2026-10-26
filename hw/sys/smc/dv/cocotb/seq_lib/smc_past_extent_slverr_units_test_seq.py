# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Past-extent and last-aperture-word response of the SLVERR-declared units over SEP_IN.

Spec sources: smc.rdl ocah_past_extent_resp placements, misc_wrap.rdl ocah_gap_resp,
memmap.adoc Address Space Organization, memory_map.adoc UART window row,
uart_log_engine_wrap.adoc, uart_16550 and log_engine memmap.adoc.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import with_timeout
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import (
    CLOCK_GATE_CONTROL,
    LOCAL_BASE_RESET,
    generated_decoded_extent,
    generated_past_extent_resp,
    generated_window,
    smc_addr,
    smc_indexed_addr,
)
from .smc_csr_seq_utils import SmcCsrSeq

AXI_RESP_OKAY = 0
AXI_RESP_DECERR = 3
PAST_EXTENT_RDATA = 0xBADCAB1E
WRITE_PATTERN = 0xA5A55A5A
FUSE_WAIT_BOUND_SMC_CYCLES = 200_000
AXI_TIMEOUT_NS = 50_000
_RESP_NAMES = {0: "OKAY", 1: "EXOKAY", 2: "SLVERR", 3: "DECERR"}

_STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10")
_TERMS = (
    "SETUP",
    "RESET_UNIT",
    "EFUSE",
    "TIMER",
    "BASE_CONFIG",
    "FABRIC_CTRL",
    "SPARE",
    "PERIPH",
    "CLA",
    "UARTWRAP",
)
# (checker, step after whose stamp it prints)
_CHECKERS = (
    ("CHK-PAST-EXTENT-RESET-UNIT", "S2"),
    ("CHK-PAST-EXTENT-EFUSE", "S3"),
    ("CHK-PAST-EXTENT-TIMER", "S4"),
    ("CHK-PAST-EXTENT-BASE-CONFIG", "S5"),
    ("CHK-PAST-EXTENT-FABRIC-CTRL", "S6"),
    ("CHK-PAST-EXTENT-SPARE", "S7"),
    ("CHK-PAST-EXTENT-PERIPH", "S8"),
    ("CHK-PAST-EXTENT-CLA", "S9"),
    ("CHK-PAST-EXTENT-UARTWRAP", "S10"),
    ("CHK-PAST-EXTENT-UARTWRAP-LIVE", "S10"),
)
FUSE_WAITS = 3

# (unit, tag, live register read before and after each write)
_RESET_UNIT = ("smc_reset_unit", "RST", smc_addr("SMC_TOP_SMC_RESET_UNIT_SS_CONFIG_BASE_ADDR"))
_EFUSE_UNITS = (
    ("smc_efuse_map", "EFMAP", smc_addr("SMC_TOP_SMC_EFUSE_MAP_SMC_CONFIG_BASE_ADDR")),
    (
        "efuse_interface_ctrl",
        "EFCTL",
        smc_addr("SMC_TOP_EFUSE_INTERFACE_CTRL_EFUSE_READ_CTRL_BASE_ADDR"),
    ),
)
_TIMER_UNIT = (
    "smc_system_timer_octs",
    "OCTS",
    smc_addr("SMC_TOP_SMC_SYSTEM_TIMER_OCTS_CTRL_BASE_ADDR"),
)
_BASE_CONFIG_UNIT = ("smc_base_config", "BCFG", CLOCK_GATE_CONTROL)
_FABRIC_UNITS = (
    (
        "smc_alias_remap",
        "ALIAS",
        smc_indexed_addr("SMC_TOP_SMC_ALIAS_REMAP_REGION_REGION_START_BASE_ADDR", 0),
    ),
    ("smc_mmode_remap", "MMODE", smc_indexed_addr("SMC_TOP_SMC_MMODE_REMAP_REGION_BASE_ADDR", 0)),
    (
        "smc_xvisor_remap",
        "XVISOR",
        smc_indexed_addr("SMC_TOP_SMC_XVISOR_REMAP_REGION_BASE_ADDR", 0),
    ),
    (
        "smc_inbound_filter_ctrl",
        "INFILT",
        smc_indexed_addr("SMC_TOP_SMC_INBOUND_FILTER_CTRL_BASE_ADDR", 0),
    ),
    (
        "smc_outbound_filter_ctrl",
        "OUTFILT",
        smc_indexed_addr("SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_BASE_ADDR", 0),
    ),
)
_SPARE_LIVE = smc_indexed_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_SCRATCH_BASE_ADDR", 0)
# Offsets from LOCAL_BASE: first and last word of each gap, past ndm_reset, last aperture word.
_SPARE_OFFSETS = (
    ("GAP1_FIRST", 0x2820),
    ("GAP1_LAST", 0x287C),
    ("GAP2_FIRST", 0x28A0),
    ("GAP2_LAST", 0x28FC),
    ("GAP3_FIRST", 0x2910),
    ("GAP3_LAST", 0x29FC),
    ("PAST_NDM_RESET", 0x2A0C),
    ("TOP", 0x2FF8),
)
_PERIPH_UNITS = (
    (
        "gpio_intf",
        "GPIO",
        smc_indexed_addr("SMC_TOP_GPIO_INTF_DATA_CTRL_ENABLE_BASE_ADDR", 0),
    ),
    ("smc_avsbus_controller", "AVS", smc_addr("SMC_TOP_SMC_AVSBUS_CONTROLLER_AVS_CFG_0_BASE_ADDR")),
    (
        "smc_i2c_wrap",
        "I2C",
        smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_INTR_ENABLE_BASE_ADDR", 0),
    ),
    (
        "smc_telemetry_receiver_wrap",
        "TELEM",
        smc_indexed_addr(
            "SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_TELEMETRY_RECEIVER_INTR_ENABLE_BASE_ADDR", 0
        ),
    ),
)
_APERTURE_ONLY_UNITS = (("smc_uart_wrap", "UART"), ("oca_i3c_wrap", "I3C"))
_CLA_UNIT = "smc_cla"

# UART/log-engine wrappers: uart_log_engine_wrap.adoc places the UART at wrapper +0x100 and
# instance N at N * 0x400; the UART 16550 decodes 64 bytes; LOG_REGION_SIZE is log-engine bank
# offset 0x04 with the bank at +0x200; LOG_CTRL[15] at bank +0x7C is the last log-engine register.
_UARTWRAP = "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP"
UARTWRAP_COUNT = 4
UARTWRAP_STRIDE = 0x400
UARTWRAP_LOG_REGION_SIZE_OFF = 0x204
UARTWRAP_PAST_UART_OFF = 0x140
UARTWRAP_PAST_LOG_ENGINE_OFF = 0x280
UARTWRAP_LIVE_BASE = 0x0000_1000
UARTWRAP_HOLE_PAIR = (AXI_RESP_OKAY, 0x0000_0000)
UARTWRAP_GAP_PAIR = (AXI_RESP_DECERR, PAST_EXTENT_RDATA)


class smc_past_extent_slverr_units_test_seq(SmcCsrSeq):
    """Probe the past-extent and last-word addresses of each SLVERR-declared unit on SEP_IN."""

    def __init__(self, name: str = "smc_past_extent_slverr_units_test_seq") -> None:
        super().__init__(name)
        self._stamps: list[tuple[str, int, int]] = []
        self._chk_marks: list[tuple[str, int]] = []
        self.fuse_state = "not waited"
        self.unconverted_reads = 0

    @property
    def total_accesses(self) -> int:
        return self.accesses + self.unconverted_reads

    def _mark_step(self, step_id: str) -> None:
        self._stamps.append((step_id, int(get_sim_time("ps")), self.total_accesses))

    def _log_chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self._chk_marks.append((chk_id, int(get_sim_time("ps"))))

    async def _read_past(self, label: str, addr: int) -> int:
        item = SmcSysAxiItem(f"rd_{label}")
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = 4
        item.allow_error = True
        item.expect_error = True
        item.expected_resp = AXI_RESP_DECERR
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        assert item.resp_code == AXI_RESP_DECERR, (
            f"{label} @ 0x{addr:08x}: rresp {item.resp_code}, want DECERR (rdata 0x{item.rdata:x})"
        )
        got = item.rdata & 0xFFFF_FFFF
        assert got == PAST_EXTENT_RDATA, (
            f"{label} @ 0x{addr:08x}: rdata 0x{got:08x}, want 0x{PAST_EXTENT_RDATA:08x}"
        )
        return got

    async def _observe_read(self, label: str, addr: int) -> tuple[int, int]:
        item = SmcSysAxiItem(f"rd_{label}")
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = 4
        item.allow_error = True
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        assert item.resp_code is not None, f"{label} @ 0x{addr:08x}: no rresp recorded"
        return item.resp_code, item.rdata & 0xFFFF_FFFF

    async def _read_unconverted(self, label: str, addr: int) -> tuple[int, bool, str]:
        """One 4-byte read on SEP_IN whose R beat is taken before any data conversion.

        The AR beat goes out on the SEP_IN manager's own AR channel under a fresh ARID, and
        the R beat is taken from that ID's response context before the manager processes
        it, so RDATA stays a logic vector. Returns (RRESP, RDATA resolvable, RDATA bits).
        """
        rif = self.env.sys_axi_agent.driver._vip.backend.read_if
        timeout_ns = self.env.cfg.axi_timeout_ns
        assert timeout_ns == AXI_TIMEOUT_NS, f"driver timeout {timeout_ns} ns"
        defaults = SmcSysAxiItem(f"rd_{label}")
        arid = rif.cur_id
        rif.cur_id = (rif.cur_id + 1) % rif.id_count
        ar = rif.ar_channel._transaction_obj()
        ar.arid = arid
        ar.araddr = addr
        ar.arlen = 0
        ar.arsize = 2
        ar.arburst = defaults.burst
        ar.arlock = defaults.axi_lock
        ar.arcache = defaults.axi_cache
        ar.arprot = defaults.prot
        ar.arqos = defaults.axi_qos
        ar.arregion = defaults.axi_region
        ar.aruser = defaults.axi_user
        manager = rif.tag_context_manager
        context = manager._get_context(arid)
        rif.in_flight_operations += 1
        rif._idle.clear()
        rif.active_id[arid] += 1
        await rif.ar_channel.send(ar)
        r = await with_timeout(context.get_resp(), timeout_ns, "ns")
        rif.active_id[arid] -= 1
        manager._set_idle(context)
        rif.in_flight_operations -= 1
        if rif.in_flight_operations == 0:
            rif._idle.set()
        self.unconverted_reads += 1
        assert r.rid.is_resolvable and int(r.rid) == arid, (
            f"{label} @ 0x{addr:08x}: rid {r.rid}, want 0x{arid:x}"
        )
        assert r.rlast.is_resolvable and int(r.rlast) == 1, (
            f"{label} @ 0x{addr:08x}: rlast {r.rlast}"
        )
        assert r.rresp.is_resolvable, f"{label} @ 0x{addr:08x}: rresp {r.rresp} is X/Z"
        rresp = int(r.rresp)
        bits = str(r.rdata)
        cocotb.log.info(
            "unconverted read %s @ 0x%08x arid=0x%x rresp=%s rdata_resolvable=%s rdata_bits=%s",
            label,
            addr,
            arid,
            _RESP_NAMES.get(rresp, rresp),
            r.rdata.is_resolvable,
            bits,
        )
        return rresp, r.rdata.is_resolvable, bits

    async def _write_past(self, label: str, addr: int) -> int:
        item = SmcSysAxiItem(f"wr_{label}")
        item.op = SmcSysAxiOp.WRITE
        item.addr = addr
        item.length = 4
        item.wdata = WRITE_PATTERN
        item.allow_error = True
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        assert item.resp_code is not None, f"{label} @ 0x{addr:08x}: no bresp recorded"
        return item.resp_code

    def _declared(self, unit: str) -> str:
        rresp_name, bresp_name = generated_past_extent_resp(unit)
        assert rresp_name == "DECERR", f"{unit}: RDL past-extent rresp {rresp_name}"
        return bresp_name

    def _past_addr(self, unit: str) -> int:
        first, _ = generated_window(unit)
        extent = generated_decoded_extent(unit)
        assert extent % 4 == 0, f"{unit}: decoded extent 0x{extent:x} not on a 4-byte boundary"
        return LOCAL_BASE_RESET + first + extent

    def _top_addr(self, unit: str) -> int:
        _, last = generated_window(unit)
        return (LOCAL_BASE_RESET + last) & ~0x7

    async def _probe_addrs(
        self, unit: str, tag: str, live_addr: int | None, points: list[tuple[str, int]]
    ) -> tuple[str, list[str]]:
        """Read and write each (where, address) point of ``unit``.

        The read must answer DECERR with 0xBADCAB1E; the write answer is printed and
        compared with the declared bresp only as a printed flag. ``live_addr`` is read
        before the points and after each write.
        """
        declared = self._declared(unit)
        self.env.axi_monitor.expected_decerr_addrs.update(addr for _, addr in points)
        before = None
        if live_addr is not None:
            before = await self.csr_read(f"{tag}_LIVE_PRE", live_addr)
        parts = []
        for where, addr in points:
            rdata = await self._read_past(f"{tag}_{where}", addr)
            bresp = await self._write_past(f"{tag}_{where}", addr)
            if live_addr is not None:
                after = await self.csr_read(f"{tag}_LIVE_POST_{where}", live_addr)
                assert after == before, (
                    f"{unit} live 0x{live_addr:08x}: 0x{after:x} after write to "
                    f"0x{addr:08x}, was 0x{before:x}"
                )
            observed = _RESP_NAMES.get(bresp, bresp)
            cocotb.log.info(
                "island=%s addr=0x%08x bresp_declared=%s bresp_observed=%s",
                unit,
                addr,
                declared,
                observed,
            )
            parts.append(
                f"{where}@0x{addr:08x} rresp=DECERR rdata=0x{rdata:08X} "
                f"bresp_declared={declared} bresp_observed={observed}"
            )
        first, last = generated_window(unit)
        live_txt = f"; live 0x{live_addr:08X}=0x{before:X} unchanged" if live_addr else ""
        head = (
            f"{unit} aperture 0x{LOCAL_BASE_RESET + first:08X}..0x{LOCAL_BASE_RESET + last:08X} "
            f"extent 0x{generated_decoded_extent(unit):X}{live_txt}; bresp measured, "
            f"LINKED-ISSUE SF-001"
        )
        return head, parts

    async def _probe_unit(self, unit: str, tag: str, live_addr: int) -> str:
        points = [("PAST", self._past_addr(unit)), ("TOP", self._top_addr(unit))]
        head, parts = await self._probe_addrs(unit, tag, live_addr, points)
        return f"{head}; {'; '.join(parts)}"

    async def body(self) -> None:
        await self.wait_fuse_sense_done(FUSE_WAIT_BOUND_SMC_CYCLES)
        dut = cocotb.top
        states = []
        for name in ("tb_fuse_sense_done", "tb_fuse_reset_n", "tb_rst_warm_smc_clk_n"):
            sig = getattr(dut, name)
            assert sig.value.is_resolvable, f"{name} is X/Z after the wait"
            states.append(f"{name}={int(sig.value)}")
        self.fuse_state = ",".join(states)
        self._mark_step("S1")

        text = await self._probe_unit(*_RESET_UNIT)
        self._mark_step("S2")
        self._log_chk("CHK-PAST-EXTENT-RESET-UNIT", text)

        text = " || ".join([await self._probe_unit(*u) for u in _EFUSE_UNITS])
        self._mark_step("S3")
        self._log_chk("CHK-PAST-EXTENT-EFUSE", text)

        text = await self._probe_unit(*_TIMER_UNIT)
        self._mark_step("S4")
        self._log_chk("CHK-PAST-EXTENT-TIMER", text)

        unit, tag, live = _BASE_CONFIG_UNIT
        past = self._past_addr(unit)
        points = [
            ("PAST", past),
            ("NEXT8", (past + 7) & ~0x7),
            ("TOP", self._top_addr(unit)),
        ]
        head, parts = await self._probe_addrs(unit, tag, live, points)
        self._mark_step("S5")
        self._log_chk("CHK-PAST-EXTENT-BASE-CONFIG", f"{head}; {'; '.join(parts)}")

        text = " || ".join([await self._probe_unit(*u) for u in _FABRIC_UNITS])
        self._mark_step("S6")
        self._log_chk("CHK-PAST-EXTENT-FABRIC-CTRL", text)

        points = [(where, LOCAL_BASE_RESET + off) for where, off in _SPARE_OFFSETS]
        head, parts = await self._probe_addrs("smc_misc_wrap", "SPARE", _SPARE_LIVE, points)
        self._mark_step("S7")
        self._log_chk("CHK-PAST-EXTENT-SPARE", f"{head}; {'; '.join(parts)}")

        texts = [await self._probe_unit(*u) for u in _PERIPH_UNITS]
        texts.extend([await self._observe_aperture_end(*u) for u in _APERTURE_ONLY_UNITS])
        self._mark_step("S8")
        self._log_chk("CHK-PAST-EXTENT-PERIPH", " || ".join(texts))

        await self._probe_cla()
        self._mark_step("S9")

        hole_gap, live = await self._probe_uart_wrappers()
        self._mark_step("S10")
        self._log_chk("CHK-PAST-EXTENT-UARTWRAP", hole_gap)
        self._log_chk("CHK-PAST-EXTENT-UARTWRAP-LIVE", live)

    async def _observe_aperture_end(self, unit: str, tag: str) -> str:
        """UART and I3C declare no past-extent response: record the codes, compare nothing.

        The read data is never converted; the monitor's R-beat count corroborates that the
        read answered exactly once.
        """
        first, last = generated_window(unit)
        top = self._top_addr(unit)
        self.env.axi_monitor.expected_decerr_addrs.add(top)
        beats_before = self.env.axi_monitor.r_beats
        rresp, resolvable, bits = await self._read_unconverted(f"{tag}_TOP", top)
        bresp = await self._write_past(f"{tag}_TOP", top)
        beats = self.env.axi_monitor.r_beats - beats_before
        assert beats == 1, f"{tag}_TOP @ 0x{top:08x}: monitor saw {beats} R beats, want 1"
        rname = _RESP_NAMES.get(rresp, rresp)
        bname = _RESP_NAMES.get(bresp, bresp)
        cocotb.log.info(
            "island=%s addr=0x%08x bresp_declared=undeclared bresp_observed=%s", unit, top, bname
        )
        return (
            f"{tag}_TOP {unit} aperture 0x{LOCAL_BASE_RESET + first:08X}.."
            f"0x{LOCAL_BASE_RESET + last:08X} @0x{top:08x} rresp={rname} bresp={bname} "
            f"(data not converted; rdata_resolvable={resolvable} rdata_bits={bits}; "
            f"monitor R beats={beats}; measured, LINKED-ISSUE SF-003, SF-004)"
        )

    def _uart_wrapper_points(self, n: int) -> tuple[int, int, list[tuple[str, int, int]]]:
        """(wrapper base, LOG_REGION_SIZE address, [(where, offset, address)]) of wrapper ``n``."""
        base = smc_indexed_addr(f"{_UARTWRAP}_BASE_ADDR", n)
        assert base == LOCAL_BASE_RESET + 0x6000 + n * UARTWRAP_STRIDE, (
            f"wrapper {n}: generated base 0x{base:08x}"
        )
        lrs = smc_indexed_addr(f"{_UARTWRAP}_LOG_ENGINE_LOG_REGION_SIZE_BASE_ADDR", n)
        assert lrs == base + UARTWRAP_LOG_REGION_SIZE_OFF, (
            f"wrapper {n}: generated LOG_REGION_SIZE 0x{lrs:08x}"
        )
        ctrl = smc_indexed_addr(f"{_UARTWRAP}_UART_LOG_ENGINE_CTRL_BASE_ADDR", n)
        gap = ctrl + smc_addr(f"{_UARTWRAP}_UART_LOG_ENGINE_CTRL_SIZE") - base
        assert gap % 4 == 0 and gap < smc_indexed_addr(f"{_UARTWRAP}_UART_BASE_ADDR", n) - base, (
            f"wrapper {n}: generated map leaves no gap before the UART (first free +0x{gap:x})"
        )
        offsets = (
            ("PAST_UART", UARTWRAP_PAST_UART_OFF),
            ("PAST_LOG_ENGINE", UARTWRAP_PAST_LOG_ENGINE_OFF),
            ("GAP", gap),
        )
        return base, lrs, [(where, off, base + off) for where, off in offsets]

    async def _probe_uart_wrappers(self) -> tuple[str, str]:
        count = smc_addr(f"{_UARTWRAP}_NUM")
        assert count == UARTWRAP_COUNT, f"generated map has {count} UART wrappers, want 4"
        wrappers = [self._uart_wrapper_points(n) for n in range(UARTWRAP_COUNT)]
        for _, _, points in wrappers:
            self.env.axi_monitor.expected_decerr_addrs.update(a for _, _, a in points)

        written = []
        for n, (_, lrs, _) in enumerate(wrappers):
            value = UARTWRAP_LIVE_BASE + n
            await self.csr_write(f"UARTWRAP{n}_LRS", lrs, value)
            got = await self.csr_read(f"UARTWRAP{n}_LRS_RB", lrs, expected=value)
            assert got == value, f"wrapper {n} LOG_REGION_SIZE 0x{got:x}, wrote 0x{value:x}"
            written.append(value)

        parts = []
        allowed = {UARTWRAP_HOLE_PAIR: "hole", UARTWRAP_GAP_PAIR: "gap"}
        for n, (_, _, points) in enumerate(wrappers):
            for where, off, addr in points:
                rresp, rdata = await self._observe_read(f"UARTWRAP{n}_{where}", addr)
                pair = allowed.get((rresp, rdata))
                assert pair is not None, (
                    f"wrapper {n} +0x{off:x} @ 0x{addr:08x}: rresp "
                    f"{_RESP_NAMES.get(rresp, rresp)} rdata 0x{rdata:08x} is neither "
                    f"(OKAY, 0x0) nor (DECERR, 0xBADCAB1E)"
                )
                bresp = await self._write_past(f"UARTWRAP{n}_{where}", addr)
                parts.append(
                    f"wrapper {n} offset 0x{off:03X} {where}@0x{addr:08x} "
                    f"rresp={_RESP_NAMES[rresp]} rdata=0x{rdata:08X} pair={pair} "
                    f"bresp={_RESP_NAMES.get(bresp, bresp)}"
                )

        after = []
        for n, (_, lrs, _) in enumerate(wrappers):
            got = await self.csr_read(f"UARTWRAP{n}_LRS_POST", lrs, expected=written[n])
            assert got == written[n], (
                f"wrapper {n} LOG_REGION_SIZE 0x{got:x} after the hole/gap writes, "
                f"wrote 0x{written[n]:x}"
            )
            after.append(got)

        hole_gap = (
            f"{len(parts)} reads each one of (OKAY, 0x00000000) / (DECERR, 0xBADCAB1E), "
            f"{len(parts)} writes; documented bresp hole=OKAY gap=SLVERR, pair and bresp per "
            f"offset measured, LINKED-ISSUE SF-003; " + "; ".join(parts)
        )
        live = (
            "wrapper0..3 LOG_REGION_SIZE written="
            + ",".join(f"0x{v:X}" for v in written)
            + " readback="
            + ",".join(f"0x{v:X}" for v in written)
            + " after="
            + ",".join(f"0x{v:X}" for v in after)
            + " rresp=OKAY"
        )
        return hole_gap, live

    async def _probe_cla(self) -> None:
        first, last = generated_window(_CLA_UNIT)
        top = self._top_addr(_CLA_UNIT)
        past = LOCAL_BASE_RESET + last + 1
        self.env.axi_monitor.expected_decerr_addrs.add(past)
        rdata_top = await self.csr_read("CLA_TOP", top)
        rdata_past = await self._read_past("CLA_PAST", past)
        bresp = await self._write_past("CLA_PAST", past)
        bname = _RESP_NAMES.get(bresp, bresp)
        self._log_chk(
            "CHK-PAST-EXTENT-CLA",
            f"{_CLA_UNIT} window 0x{LOCAL_BASE_RESET + first:08X}.."
            f"0x{LOCAL_BASE_RESET + last:08X}; "
            f"last word @0x{top:08x} rresp=OKAY rdata=0x{rdata_top & 0xFFFFFFFF:08X}; "
            f"past @0x{past:08x} rresp=DECERR rdata=0x{rdata_past:08X} bresp_observed={bname}",
        )

    def log_timeout_paths(self) -> None:
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits, 0 expired; wait_fuse_sense_done sub-waits "
            "tb_fuse_sense_done, tb_fuse_reset_n, tb_rst_warm_smc_clk_n each bounded %d "
            "clk_smc_i rises, last observed %s; %d driver AXI accesses each bounded by the "
            "driver timeout %d ns (allow_timeout False) and %d unconverted reads each bounded "
            "by with_timeout %d ns, all answered; no other wait",
            FUSE_WAITS + self.total_accesses,
            FUSE_WAIT_BOUND_SMC_CYCLES,
            self.fuse_state,
            self.accesses,
            AXI_TIMEOUT_NS,
            self.unconverted_reads,
            AXI_TIMEOUT_NS,
        )

    def nonvac_fence(self, floor: int) -> None:
        ids = tuple(s for s, _, _ in self._stamps)
        assert ids == _STEPS, f"step ids {ids}, want {_STEPS}"
        times = [t for _, t, _ in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"step stamps not increasing: {times}"
        chk_ids = tuple(c for c, _ in self._chk_marks)
        want = tuple(c for c, _ in _CHECKERS)
        assert chk_ids == want, f"checker lines {chk_ids}, want {want}"
        stamp_of = {s: t for s, t, _ in self._stamps}
        for (chk_id, when), (_, step) in zip(self._chk_marks, _CHECKERS):
            assert when >= stamp_of[step], f"{chk_id} printed before its step {step} stamp"
        counts = [FUSE_WAITS]
        counts.extend(b - a for (_, _, a), (_, _, b) in zip(self._stamps, self._stamps[1:]))
        assert all(c > 0 for c in counts), f"zero-count fence term: {dict(zip(_TERMS, counts))}"
        assert self.total_accesses >= floor, f"{self.total_accesses} accesses, floor {floor}"
        terms = ",".join(
            f"{term}[{step} t={t}ps n={c}]"
            for term, (step, t, _), c in zip(_TERMS, self._stamps, counts)
        )
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s, accesses %d >= %d (%d driver + %d unconverted); "
            "checker lines %s; terms %s",
            "<".join(_TERMS),
            self.total_accesses,
            floor,
            self.accesses,
            self.unconverted_reads,
            ",".join(chk_ids),
            terms,
        )
