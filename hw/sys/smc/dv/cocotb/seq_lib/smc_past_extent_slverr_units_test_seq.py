# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
# DV-TESTCASE-CONTRACT: SMC_COV_R4_003 ANCHOR: smc_past_extent_slverr_units_test
# DV-TESTCASE-CONTRACT-REVISION: 2 RECORD-SHA256: 6be46fedcec884c50cdbb8daa6cb4ee084f440621197d483c8c35006e003758b
# DV-TESTCASE-CONTRACT-SOURCE: hw/sys/smc/dv/ai/dv_vplan_gen/SMC_COV_R4_VPLAN_DETAIL.md @ artifact_revision 3 ENV: cocotb
"""Past-extent, last-aperture-word and unimplemented-offset responses of SMC unit windows.

Every access goes over SEP_IN. Spec sources: smc.rdl ocah_past_extent_resp placements,
misc_wrap.rdl ocah_gap_resp, memmap.adoc Address Space Organization and AXI-Lite External
Window, memory_map.adoc component rows, uart_log_engine_wrap.adoc, uart_16550_main.adoc,
log_engine.adoc, smc_cla.adoc, zeroer_ctrl.adoc, efuse_interface_ctrl.adoc and
telemetry_receiver.adoc.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import with_timeout
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import (
    AVS_CG_EN,
    CLOCK_GATE_CONTROL,
    I3C_CG_EN,
    LOCAL_BASE_RESET,
    TELEMETRY_CG_EN,
    UART_CG_EN,
    ZEROER_CTRL_DEST_ADDR,
    ZEROER_CTRL_STATUS,
    generated_decoded_extent,
    generated_past_extent_resp,
    generated_window,
    smc_addr,
    smc_indexed_addr,
)
from .smc_csr_seq_utils import SmcCsrSeq

AXI_RESP_OKAY = 0
AXI_RESP_SLVERR = 2
AXI_RESP_DECERR = 3
PAST_EXTENT_RDATA = 0xBADCAB1E
WRITE_PATTERN = 0xA5A55A5A
FUSE_WAIT_BOUND_SMC_CYCLES = 200_000
AXI_TIMEOUT_NS = 50_000
_RESP_NAMES = {0: "OKAY", 1: "EXOKAY", 2: "SLVERR", 3: "DECERR"}

_STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9")
_TERMS = (
    "SETUP",
    "EXISTING",
    "CLA",
    "DMA-ZEROER",
    "UART-LOGENG",
    "EFUSE",
    "I3C",
    "TELEMETRY-AVS",
    "EXTERNAL",
)
# The past-extent legs inside S2, each stamped as E.<leg>; the last one closes S2.
_EXISTING_LEGS = (
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
# (checker, stamp after which it prints)
_CHECKERS = (
    ("CHK-PAST-EXTENT-RESET-UNIT", "E.RESET_UNIT"),
    ("CHK-PAST-EXTENT-EFUSE", "E.EFUSE"),
    ("CHK-PAST-EXTENT-TIMER", "E.TIMER"),
    ("CHK-PAST-EXTENT-BASE-CONFIG", "E.BASE_CONFIG"),
    ("CHK-PAST-EXTENT-FABRIC-CTRL", "E.FABRIC_CTRL"),
    ("CHK-PAST-EXTENT-SPARE", "E.SPARE"),
    ("CHK-PAST-EXTENT-PERIPH", "E.PERIPH"),
    ("CHK-PAST-EXTENT-CLA", "E.CLA"),
    ("CHK-PAST-EXTENT-UARTWRAP", "E.UARTWRAP"),
    ("CHK-PAST-EXTENT-UARTWRAP-LIVE", "E.UARTWRAP"),
    ("CHK-ERR-CLA", "S3"),
    ("CHK-ERR-DMA", "S4"),
    ("CHK-ERR-ZEROER", "S4"),
    ("CHK-ERR-UART", "S5"),
    ("CHK-ERR-LOGENG", "S5"),
    ("CHK-ERR-EFUSE", "S6"),
    ("CHK-ERR-I3C", "S7"),
    ("CHK-ERR-TELEMETRY", "S8"),
    ("CHK-ERR-AVS", "S8"),
    ("CHK-ERR-EXTERNAL", "S9"),
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
        "smc_alias_remap_wrap",
        "ALIAS",
        smc_indexed_addr(
            "SMC_TOP_SMC_ALIAS_REMAP_WRAP_ALIAS_REMAP_REGION_REGION_START_BASE_ADDR", 0
        ),
    ),
    (
        "smc_mmode_remap_wrap",
        "MMODE",
        smc_indexed_addr("SMC_TOP_SMC_MMODE_REMAP_WRAP_OUTPUT_REMAP_REGION_BASE_ADDR", 0),
    ),
    (
        "smc_xvisor_remap_wrap",
        "XVISOR",
        smc_indexed_addr("SMC_TOP_SMC_XVISOR_REMAP_WRAP_OUTPUT_REMAP_REGION_BASE_ADDR", 0),
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
        "gpio_intf_wrap",
        "GPIO",
        smc_indexed_addr("SMC_TOP_GPIO_INTF_WRAP_GPIO_INTF_DATA_CTRL_ENABLE_BASE_ADDR", 0),
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

# Unimplemented-offset probes. Offsets are from LOCAL_BASE unless named as window or bank
# offsets. memmap.adoc: the UART, I3C, AVSBus and telemetry windows answer SLVERR with
# 0xBADCAB1E while their CLOCK_GATE_CONTROL enable is set.
GATED_PAIR = (AXI_RESP_SLVERR, 0xBADCAB1E)
_GATE_BITS = (
    ("UART", UART_CG_EN),
    ("I3C", I3C_CG_EN),
    ("TELEMETRY", TELEMETRY_CG_EN),
    ("AVS", AVS_CG_EN),
)
# smc_cla.adoc: dst_sink gap 0x44-0xFF4, funnel gap 0x100C-0x1FF4, dst gap 0x31A4-0x3FF4.
CLA_GAP_OFFSETS = (0x0800, 0x1800, 0x3800)
CLA_TRDSTRAMIMPL_OFF = 0x4
CLA_TRDSTRAMIMPL_RESET = 0x0100_3901
DMA_PAST_OFF = 0x3_8180
DMA_CTRL0_OFF = 0x3_8000
ZEROER_PAST_OFF = 0x3_8280
ZEROER_DEST_ADDR_OFF = 0x3_8200
ZEROER_CTRL_STATUS_OFF = 0x3_8210
ZEROER_STATUS_BIT = 32
# Wrapper 0: UART window offsets, then (log-engine bank offset, wrapper offset).
UART_PROBE_OFFSETS = (0x1C0, 0x3F0)
UART_SCR_OFF = 0x11C
UART_SCR_VALUE = 0x5A
LOGENG_PROBE_OFFSETS = ((0x20, 0x220), (0xC0, 0x2C0))
LOG_WRITE_ADDR_OFF = 0x210
LOG_WRITE_ADDR_VALUE = 0x1357_9BDF
EFUSE_CTRL_PAST_OFF = 0x8800
EFUSE_CTRL_STATUS_OFF = 0x8000
EFUSE_SHADOW_PAST_OFF = 0x7800
EFUSE_SHADOW_FIRST_OFF = 0x7000
# I3C window offset and the unimplemented offset inside it.
I3C_WINDOW_OFF = 0x3_A000
I3C_HOLE_OFF = 0x3F0
TELEMETRY_HOLE_OFF = 0x9040
TELEMETRY_PAST_OFF = 0x9800
TELEMETRY_CTRL_OFF = 0x9000
AVS_PAST_OFF = 0x4800
AVS_FIRST_OFF = 0x4000
EXTERNAL_UNCLAIMED_OFF = 0x40_6000
EXTERNAL_PAST_OFF = 0x40_6548
# Probes whose documented answer is an error, or one of a pair that includes DECERR.
_ERROR_PROBE_OFFSETS = (
    DMA_PAST_OFF,
    ZEROER_PAST_OFF,
    *(0x6000 + off for off in UART_PROBE_OFFSETS),
    *(0x6000 + off for _, off in LOGENG_PROBE_OFFSETS),
    EFUSE_CTRL_PAST_OFF,
    EFUSE_SHADOW_PAST_OFF,
    TELEMETRY_PAST_OFF,
    AVS_PAST_OFF,
    EXTERNAL_UNCLAIMED_OFF,
    EXTERNAL_PAST_OFF,
)


class smc_past_extent_slverr_units_test_seq(SmcCsrSeq):
    """Probe the past-extent and last-word addresses of each SLVERR-declared unit on SEP_IN."""

    def __init__(self, name: str = "smc_past_extent_slverr_units_test_seq") -> None:
        super().__init__(name)
        self._stamps: list[tuple[str, int, int]] = []
        self._leg_stamps: list[tuple[str, int, int]] = []
        self.gated: dict[str, bool] = {}
        self.clock_gate_control: int | None = None
        self._chk_marks: list[tuple[str, int]] = []
        self.fuse_state = "not waited"
        self.unconverted_reads = 0

    @property
    def total_accesses(self) -> int:
        return self.accesses + self.unconverted_reads

    def _mark_step(self, step_id: str) -> None:
        self._stamps.append((step_id, int(get_sim_time("ps")), self.total_accesses))

    def _mark_leg(self, leg: str) -> None:
        self._leg_stamps.append((f"E.{leg}", int(get_sim_time("ps")), self.total_accesses))

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

    async def _observe_read(self, label: str, addr: int, length: int = 4) -> tuple[int, int]:
        item = SmcSysAxiItem(f"rd_{label}")
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = length
        item.allow_error = True
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        assert item.resp_code is not None, f"{label} @ 0x{addr:08x}: no rresp recorded"
        return item.resp_code, item.rdata & ((1 << (8 * length)) - 1)

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

    async def _write_past(self, label: str, addr: int, data: int = WRITE_PATTERN) -> int:
        item = SmcSysAxiItem(f"wr_{label}")
        item.op = SmcSysAxiOp.WRITE
        item.addr = addr
        item.length = 4
        item.wdata = data
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
        cgc = await self.csr_read("CLOCK_GATE_CONTROL_SETUP", CLOCK_GATE_CONTROL)
        self.clock_gate_control = cgc & 0xFFFF_FFFF
        self.gated = {win: bool(cgc & bit) for win, bit in _GATE_BITS}
        self.env.axi_monitor.expected_decerr_addrs.update(
            LOCAL_BASE_RESET + off for off in _ERROR_PROBE_OFFSETS
        )
        cocotb.log.info(
            "SETUP: CLOCK_GATE_CONTROL=0x%08x gated=%s; %d error probes registered",
            self.clock_gate_control,
            self.gated,
            len(_ERROR_PROBE_OFFSETS),
        )
        self._mark_step("S1")

        await self._existing_legs()
        self._mark_step("S2")

        self._log_chk("CHK-ERR-CLA", await self._err_cla())
        self._mark_step("S3")
        dma, zeroer = await self._err_dma_zeroer()
        self._mark_step("S4")
        self._log_chk("CHK-ERR-DMA", dma)
        self._log_chk("CHK-ERR-ZEROER", zeroer)
        uart, logeng = await self._err_uart_logeng()
        self._mark_step("S5")
        self._log_chk("CHK-ERR-UART", uart)
        self._log_chk("CHK-ERR-LOGENG", logeng)
        efuse = await self._err_efuse()
        self._mark_step("S6")
        self._log_chk("CHK-ERR-EFUSE", efuse)
        i3c = await self._err_i3c()
        self._mark_step("S7")
        self._log_chk("CHK-ERR-I3C", i3c)
        telemetry, avs = await self._err_telemetry_avs()
        self._mark_step("S8")
        self._log_chk("CHK-ERR-TELEMETRY", telemetry)
        self._log_chk("CHK-ERR-AVS", avs)
        external = await self._err_external()
        self._mark_step("S9")
        self._log_chk("CHK-ERR-EXTERNAL", external)

    async def _existing_legs(self) -> None:
        text = await self._probe_unit(*_RESET_UNIT)
        self._mark_leg("RESET_UNIT")
        self._log_chk("CHK-PAST-EXTENT-RESET-UNIT", text)

        text = " || ".join([await self._probe_unit(*u) for u in _EFUSE_UNITS])
        self._mark_leg("EFUSE")
        self._log_chk("CHK-PAST-EXTENT-EFUSE", text)

        text = await self._probe_unit(*_TIMER_UNIT)
        self._mark_leg("TIMER")
        self._log_chk("CHK-PAST-EXTENT-TIMER", text)

        unit, tag, live = _BASE_CONFIG_UNIT
        past = self._past_addr(unit)
        points = [
            ("PAST", past),
            ("NEXT8", (past + 7) & ~0x7),
            ("TOP", self._top_addr(unit)),
        ]
        head, parts = await self._probe_addrs(unit, tag, live, points)
        self._mark_leg("BASE_CONFIG")
        self._log_chk("CHK-PAST-EXTENT-BASE-CONFIG", f"{head}; {'; '.join(parts)}")

        text = " || ".join([await self._probe_unit(*u) for u in _FABRIC_UNITS])
        self._mark_leg("FABRIC_CTRL")
        self._log_chk("CHK-PAST-EXTENT-FABRIC-CTRL", text)

        points = [(where, LOCAL_BASE_RESET + off) for where, off in _SPARE_OFFSETS]
        head, parts = await self._probe_addrs("smc_misc_wrap", "SPARE", _SPARE_LIVE, points)
        self._mark_leg("SPARE")
        self._log_chk("CHK-PAST-EXTENT-SPARE", f"{head}; {'; '.join(parts)}")

        texts = [await self._probe_unit(*u) for u in _PERIPH_UNITS]
        texts.extend([await self._observe_aperture_end(*u) for u in _APERTURE_ONLY_UNITS])
        self._mark_leg("PERIPH")
        self._log_chk("CHK-PAST-EXTENT-PERIPH", " || ".join(texts))

        await self._probe_cla()
        self._mark_leg("CLA")

        hole_gap, live = await self._probe_uart_wrappers()
        self._mark_leg("UARTWRAP")
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

    @staticmethod
    def _pair(pair: tuple[int, int]) -> str:
        return f"({_RESP_NAMES.get(pair[0], pair[0])},0x{pair[1]:08X})"

    def _in_window(self, unit: str, off: int) -> int:
        """LOCAL_BASE + ``off``, which must lie inside ``unit``'s generated aperture."""
        first, last = generated_window(unit)
        assert first <= off <= last, (
            f"{unit}: offset 0x{off:x} outside its aperture 0x{first:x}..0x{last:x}"
        )
        return LOCAL_BASE_RESET + off

    def _past_extent(self, unit: str, off: int) -> int:
        """LOCAL_BASE + ``off``, which must lie in ``unit``'s aperture past its decoded extent."""
        addr = self._in_window(unit, off)
        first, _ = generated_window(unit)
        extent = generated_decoded_extent(unit)
        assert off >= first + extent, f"{unit}: offset 0x{off:x} inside the 0x{extent:x} extent"
        assert generated_past_extent_resp(unit) == ("DECERR", "DECERR"), (
            f"{unit}: generated past-extent response {generated_past_extent_resp(unit)}"
        )
        return addr

    def _want(self, win: str | None, pair: tuple[int, int]) -> tuple[int, int]:
        return GATED_PAIR if win is not None and self.gated[win] else pair

    async def _rd_exact(
        self, win: str | None, label: str, addr: int, want: tuple[int, int], length: int = 4
    ) -> int:
        got = await self._observe_read(label, addr, length)
        want = self._want(win, want)
        assert got == want, (
            f"{label} @ 0x{addr:08x}: read {self._pair(got)}, want {self._pair(want)}"
        )
        return got[1]

    async def _rd_code(self, win: str | None, label: str, addr: int, length: int = 4) -> int:
        """Read whose response code is OKAY (gate clear) and whose data is only recorded."""
        got = await self._observe_read(label, addr, length)
        if win is not None and self.gated[win]:
            assert got == GATED_PAIR, f"{label} @ 0x{addr:08x}: read {self._pair(got)} while gated"
        else:
            assert got[0] == AXI_RESP_OKAY, f"{label} @ 0x{addr:08x}: read {self._pair(got)}"
        return got[1]

    async def _wr_exact(
        self, win: str | None, label: str, addr: int, want: int, data: int = WRITE_PATTERN
    ) -> int:
        got = await self._write_past(label, addr, data)
        if win is not None and self.gated[win]:
            want = AXI_RESP_SLVERR
        assert got == want, (
            f"{label} @ 0x{addr:08x}: bresp {_RESP_NAMES.get(got, got)}, "
            f"want {_RESP_NAMES.get(want, want)}"
        )
        return got

    async def _err_cla(self) -> str:
        first, _ = generated_window(_CLA_UNIT)
        rd = wr = rerd = 0
        for off in CLA_GAP_OFFSETS:
            addr = self._in_window(_CLA_UNIT, first + off)
            await self._rd_exact(None, f"CLA_GAP_{off:X}", addr, (AXI_RESP_OKAY, 0))
            rd += 1
            await self._wr_exact(None, f"CLA_GAP_{off:X}", addr, AXI_RESP_OKAY)
            wr += 1
            await self._rd_exact(None, f"CLA_GAP_{off:X}_RERD", addr, (AXI_RESP_OKAY, 0))
            rerd += 1
        impl = await self._rd_exact(
            None,
            "CLA_TRDSTRAMIMPL",
            self._in_window(_CLA_UNIT, first + CLA_TRDSTRAMIMPL_OFF),
            (AXI_RESP_OKAY, CLA_TRDSTRAMIMPL_RESET),
        )
        n = len(CLA_GAP_OFFSETS)
        return (
            f"gaps 0x800/0x1800/0x3800 rd OKAY 0x0 {rd}/{n}, wr OKAY {wr}/{n}, "
            f"re-rd 0x0 {rerd}/{n}; Trdstramimpl=0x{impl:08X} OKAY"
        )

    async def _err_dma_zeroer(self) -> tuple[str, str]:
        past = self._past_extent("dma_ctrl", DMA_PAST_OFF)
        rd = await self._read_past("DMA_PAST", past)
        await self._wr_exact(None, "DMA_PAST", past, AXI_RESP_DECERR)
        ctrl0 = await self._rd_code(None, "DMA_CTRL0", self._in_window("dma_ctrl", DMA_CTRL0_OFF))
        dma = f"past rd DECERR 0x{rd:08X}, wr DECERR; +0x0 rd OKAY data=0x{ctrl0:08X}"

        status_addr = self._in_window("zeroer_ctrl", ZEROER_CTRL_STATUS_OFF)
        dest_addr = self._in_window("zeroer_ctrl", ZEROER_DEST_ADDR_OFF)
        assert status_addr == ZEROER_CTRL_STATUS, f"CTRL_STATUS 0x{ZEROER_CTRL_STATUS:x}"
        assert dest_addr == ZEROER_CTRL_DEST_ADDR, f"DEST_ADDR 0x{ZEROER_CTRL_DEST_ADDR:x}"
        pre = await self._rd_code(None, "ZEROER_CTRL_STATUS_PRE", status_addr, length=8)
        status_pre = (pre >> ZEROER_STATUS_BIT) & 1
        assert status_pre == 0, f"zeroer STATUS={status_pre} before the probe (0x{pre:016x})"
        past = self._past_extent("zeroer_ctrl", ZEROER_PAST_OFF)
        rd = await self._read_past("ZEROER_PAST", past)
        await self._wr_exact(None, "ZEROER_PAST", past, AXI_RESP_DECERR)
        post = await self._rd_code(None, "ZEROER_CTRL_STATUS_POST", status_addr, length=8)
        status_post = (post >> ZEROER_STATUS_BIT) & 1
        assert status_post == 0, f"zeroer STATUS={status_post} after the probe (0x{post:016x})"
        dest = await self._rd_exact(
            None, "ZEROER_DEST_ADDR", dest_addr, (AXI_RESP_OKAY, 0), length=8
        )
        zeroer = (
            f"past rd DECERR 0x{rd:08X}, wr DECERR; STATUS {status_pre}->{status_post}; "
            f"DEST_ADDR=0x{dest:X} OKAY"
        )
        return dma, zeroer

    async def _pair_probe(self, win: str, label: str, addr: int) -> tuple[str, str]:
        """Read and write one UART-window offset; returns (read pair, write code)."""
        got = await self._observe_read(label, addr)
        if self.gated[win]:
            allowed_rd = {GATED_PAIR: "gated"}
            allowed_wr = {AXI_RESP_SLVERR}
        else:
            allowed_rd = {UARTWRAP_HOLE_PAIR: "hole", UARTWRAP_GAP_PAIR: "gap"}
            allowed_wr = {AXI_RESP_OKAY, AXI_RESP_DECERR}
        assert got in allowed_rd, (
            f"{label} @ 0x{addr:08x}: read {self._pair(got)} is none of "
            f"{', '.join(self._pair(p) for p in allowed_rd)}"
        )
        bresp = await self._write_past(label, addr)
        assert bresp in allowed_wr, (
            f"{label} @ 0x{addr:08x}: bresp {_RESP_NAMES.get(bresp, bresp)}, want one of "
            f"{', '.join(_RESP_NAMES[c] for c in sorted(allowed_wr))}"
        )
        return self._pair(got), _RESP_NAMES.get(bresp, str(bresp))

    async def _err_uart_logeng(self) -> tuple[str, str]:
        base = smc_indexed_addr(f"{_UARTWRAP}_BASE_ADDR", 0)
        assert base == self._in_window("smc_uart_wrap", 0x6000), f"wrapper 0 at 0x{base:08x}"
        parts = []
        for off in UART_PROBE_OFFSETS:
            pair, code = await self._pair_probe("UART", f"UART_{off:X}", base + off)
            parts.append(f"+0x{off:X} rd {pair} wr {code}")
        scr = smc_indexed_addr(f"{_UARTWRAP}_UART_SCR_BASE_ADDR", 0)
        assert scr == base + UART_SCR_OFF, f"SCR at 0x{scr:08x}"
        await self._wr_exact("UART", "UART_SCR", scr, AXI_RESP_OKAY, UART_SCR_VALUE)
        got = await self._rd_exact("UART", "UART_SCR_RB", scr, (AXI_RESP_OKAY, UART_SCR_VALUE))
        uart = f"{', '.join(parts)} (LINKED-ISSUE SF-015); SCR=0x{got:X} OKAY"

        parts = []
        for bank_off, off in LOGENG_PROBE_OFFSETS:
            pair, code = await self._pair_probe("UART", f"LOGENG_{bank_off:X}", base + off)
            parts.append(f"0x{bank_off:X} rd {pair} wr {code}")
        lwa = smc_indexed_addr(f"{_UARTWRAP}_LOG_ENGINE_LOG_WRITE_ADDR_BASE_ADDR", 0)
        assert lwa == base + LOG_WRITE_ADDR_OFF, f"LOG_WRITE_ADDR at 0x{lwa:08x}"
        await self._wr_exact("UART", "LOG_WRITE_ADDR", lwa, AXI_RESP_OKAY, LOG_WRITE_ADDR_VALUE)
        got = await self._rd_exact(
            "UART", "LOG_WRITE_ADDR_RB", lwa, (AXI_RESP_OKAY, LOG_WRITE_ADDR_VALUE)
        )
        await self._wr_exact("UART", "LOG_WRITE_ADDR_RESTORE", lwa, AXI_RESP_OKAY, 0)
        restored = await self._rd_exact(
            "UART", "LOG_WRITE_ADDR_RESTORE_RB", lwa, (AXI_RESP_OKAY, 0)
        )
        logeng = (
            f"bank {', '.join(parts)} (LINKED-ISSUE SF-015); LOG_WRITE_ADDR=0x{got:08X} OKAY "
            f"(restored 0x{restored:X})"
        )
        return uart, logeng

    async def _err_efuse(self) -> str:
        past = self._past_extent("efuse_interface_ctrl", EFUSE_CTRL_PAST_OFF)
        rd_ctrl = await self._read_past("EFUSE_CTRL_PAST", past)
        await self._wr_exact(None, "EFUSE_CTRL_PAST", past, AXI_RESP_DECERR)
        status_addr = self._in_window("efuse_interface_ctrl", EFUSE_CTRL_STATUS_OFF)
        assert status_addr == smc_addr(
            "SMC_TOP_EFUSE_INTERFACE_CTRL_EFUSE_INTERFACE_CTRL_STATUS_BASE_ADDR"
        ), f"EFUSE_INTERFACE_CTRL_STATUS at 0x{status_addr:08x}"
        status = await self._rd_code(None, "EFUSE_INTERFACE_CTRL_STATUS", status_addr)
        past = self._past_extent("smc_efuse_map", EFUSE_SHADOW_PAST_OFF)
        rd_shadow = await self._read_past("EFUSE_SHADOW_PAST", past)
        await self._wr_exact(None, "EFUSE_SHADOW_PAST", past, AXI_RESP_DECERR)
        first = await self._rd_code(
            None, "EFUSE_SHADOW_FIRST", self._in_window("smc_efuse_map", EFUSE_SHADOW_FIRST_OFF)
        )
        cocotb.log.info(
            "EFUSE: EFUSE_INTERFACE_CTRL_STATUS=0x%08x shadow +0x0=0x%08x (data recorded, SF-018)",
            status,
            first,
        )
        return (
            f"ctrl past rd DECERR 0x{rd_ctrl:08X} wr DECERR, STATUS OKAY; shadow past rd DECERR "
            f"0x{rd_shadow:08X} wr DECERR, +0x0 OKAY"
        )

    async def _err_i3c(self) -> str:
        first, _ = generated_window("oca_i3c_wrap")
        assert first == I3C_WINDOW_OFF, f"I3C window at +0x{first:x}"
        hole = self._in_window("oca_i3c_wrap", first + I3C_HOLE_OFF)
        rd = await self._rd_exact("I3C", "I3C_HOLE", hole, (AXI_RESP_OKAY, 0))
        await self._wr_exact("I3C", "I3C_HOLE", hole, AXI_RESP_OKAY)
        rerd = await self._rd_exact("I3C", "I3C_HOLE_RERD", hole, (AXI_RESP_OKAY, 0))
        if self.gated["I3C"]:
            return f"gated: +0x3F0 rd/wr/re-rd SLVERR 0x{rd:08X}/0x{rerd:08X} (SF-019)"
        return (
            f"+0x3F0 rd OKAY 0x{rd:X}, wr OKAY, re-rd OKAY 0x{rerd:X} "
            "(DAT/DCT not accessed, SF-029)"
        )

    async def _err_telemetry_avs(self) -> tuple[str, str]:
        unit = "smc_telemetry_receiver_wrap"
        hole = self._in_window(unit, TELEMETRY_HOLE_OFF)
        assert generated_window(unit)[0] == TELEMETRY_CTRL_OFF, "receiver 0 not at window base"
        await self._rd_exact("TELEMETRY", "TELEM_HOLE", hole, (AXI_RESP_OKAY, 0))
        await self._wr_exact("TELEMETRY", "TELEM_HOLE", hole, AXI_RESP_OKAY)
        past = self._past_extent(unit, TELEMETRY_PAST_OFF)
        await self._rd_exact("TELEMETRY", "TELEM_PAST", past, (AXI_RESP_DECERR, PAST_EXTENT_RDATA))
        await self._wr_exact("TELEMETRY", "TELEM_PAST", past, AXI_RESP_DECERR)
        ctrl = self._in_window(unit, TELEMETRY_CTRL_OFF)
        assert ctrl == smc_indexed_addr(
            "SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_TELEMETRY_RECEIVER_CTRL_BASE_ADDR", 0
        ), f"telemetry CTRL at 0x{ctrl:08x}"
        ctrl_val = await self._rd_code("TELEMETRY", "TELEM_CTRL", ctrl)
        telemetry = "hole rd OKAY 0x0 wr OKAY; past rd DECERR 0xBADCAB1E wr DECERR; CTRL OKAY"
        if self.gated["TELEMETRY"]:
            telemetry = "gated: every access SLVERR 0xBADCAB1E (SF-019)"

        unit = "smc_avsbus_controller"
        past = self._past_extent(unit, AVS_PAST_OFF)
        await self._rd_exact("AVS", "AVS_PAST", past, (AXI_RESP_DECERR, PAST_EXTENT_RDATA))
        await self._wr_exact("AVS", "AVS_PAST", past, AXI_RESP_DECERR)
        first = await self._rd_code("AVS", "AVS_FIRST", self._in_window(unit, AVS_FIRST_OFF))
        avs = f"past rd DECERR 0xBADCAB1E wr DECERR; +0x0 rd OKAY data=0x{first:08X}"
        if self.gated["AVS"]:
            avs = f"gated: every access SLVERR 0xBADCAB1E (SF-019); +0x0 data=0x{first:08X}"
        cocotb.log.info("TELEMETRY: CTRL=0x%08x (data recorded)", ctrl_val)
        return telemetry, avs

    async def _err_external(self) -> str:
        unit = "smc_external"
        _, last = generated_window(unit)
        assert last + 1 == EXTERNAL_PAST_OFF, f"external window ends at +0x{last:x}"
        past = LOCAL_BASE_RESET + EXTERNAL_PAST_OFF
        rd = await self._read_past("EXTERNAL_PAST", past)
        await self._wr_exact(None, "EXTERNAL_PAST", past, AXI_RESP_DECERR)
        addr = self._in_window(unit, EXTERNAL_UNCLAIMED_OFF)
        rresp, rdata = await self._observe_read("EXTERNAL_UNCLAIMED", addr)
        bresp = await self._write_past("EXTERNAL_UNCLAIMED", addr)
        return (
            f"past-window rd DECERR 0x{rd:08X} wr DECERR; +0x6000 rd "
            f"{_RESP_NAMES.get(rresp, rresp)} 0x{rdata:08X} wr {_RESP_NAMES.get(bresp, bresp)} "
            f"(LINKED-ISSUE SF-016)"
        )

    def log_timeout_paths(self) -> None:
        mon = self.env.axi_monitor
        r_codes = ",".join(
            f"{_RESP_NAMES.get(code, 'X')}={n}" for code, n in mon.resp_tally.items() if n
        )
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits, bound/last-state per wait, 0 expired; "
            "wait_fuse_sense_done sub-waits tb_fuse_sense_done, tb_fuse_reset_n, "
            "tb_rst_warm_smc_clk_n bound %d clk_smc_i rises each, last state %s; %d driver "
            "AXI accesses bound %d ns each by the driver timeout (allow_timeout False, expiry "
            "raises in the driver), %d unconverted reads bound %d ns each by with_timeout "
            "(expiry raises), last state every access answered: monitor R beats %d (%s), "
            "B responses %d; no other wait",
            FUSE_WAITS + self.total_accesses,
            FUSE_WAIT_BOUND_SMC_CYCLES,
            self.fuse_state,
            self.accesses,
            AXI_TIMEOUT_NS,
            self.unconverted_reads,
            AXI_TIMEOUT_NS,
            mon.r_beats,
            r_codes,
            mon.b_resps,
        )

    def nonvac_fence(self, floor: int) -> None:
        ids = tuple(s for s, _, _ in self._stamps)
        assert ids == _STEPS, f"step ids {ids}, want {_STEPS}"
        times = [t for _, t, _ in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"step stamps not increasing: {times}"
        leg_ids = tuple(s for s, _, _ in self._leg_stamps)
        want_legs = tuple(f"E.{leg}" for leg in _EXISTING_LEGS)
        assert leg_ids == want_legs, f"existing leg stamps {leg_ids}, want {want_legs}"
        legs = [self._stamps[0], *self._leg_stamps]
        leg_times = [t for _, t, _ in legs]
        assert all(b > a for a, b in zip(leg_times, leg_times[1:])), (
            f"existing leg stamps not increasing after S1: {leg_times}"
        )
        assert self._leg_stamps[-1][1:] == self._stamps[1][1:], "S2 does not close the legs"
        leg_counts = [b - a for (_, _, a), (_, _, b) in zip(legs, legs[1:])]
        assert all(c > 0 for c in leg_counts), (
            f"zero-count existing leg: {dict(zip(_EXISTING_LEGS, leg_counts))}"
        )
        chk_ids = tuple(c for c, _ in self._chk_marks)
        want = tuple(c for c, _ in _CHECKERS)
        assert chk_ids == want, f"checker lines {chk_ids}, want {want}"
        stamp_of = {s: t for s, t, _ in [*self._stamps, *self._leg_stamps]}
        for (chk_id, when), (_, step) in zip(self._chk_marks, _CHECKERS):
            assert when >= stamp_of[step], f"{chk_id} printed before its stamp {step}"
        counts = [FUSE_WAITS + self._stamps[0][2]]
        counts.extend(b - a for (_, _, a), (_, _, b) in zip(self._stamps, self._stamps[1:]))
        assert all(c > 0 for c in counts), f"zero-count fence term: {dict(zip(_TERMS, counts))}"
        assert self.total_accesses >= floor, f"{self.total_accesses} accesses, floor {floor}"
        terms = ",".join(
            f"{term}[{step} t={t}ps n={c}]"
            for term, (step, t, _), c in zip(_TERMS, self._stamps, counts)
        )
        leg_terms = ",".join(
            f"{leg}[t={t}ps n={c}]"
            for leg, (_, t, _), c in zip(_EXISTING_LEGS, self._leg_stamps, leg_counts)
        )
        cocotb.log.info(
            "CHK-NONVAC: %s; terms %s; EXISTING legs %s; accesses %d >= %d (%d driver + %d "
            "unconverted); checker lines %s",
            " < ".join(_TERMS),
            terms,
            leg_terms,
            self.total_accesses,
            floor,
            self.accesses,
            self.unconverted_reads,
            ",".join(chk_ids),
        )
