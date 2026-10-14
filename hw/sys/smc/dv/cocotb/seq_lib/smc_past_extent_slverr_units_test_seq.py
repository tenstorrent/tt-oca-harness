# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Past-extent and last-aperture-word response of the SLVERR-declared units over SEP_IN.

Spec sources: smc.rdl ocah_past_extent_resp placements, misc_wrap.rdl ocah_gap_resp,
memmap.adoc Address Space Organization.
"""

from __future__ import annotations

import cocotb
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

_STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9")
_CHECKERS = (
    "CHK-PAST-EXTENT-RESET-UNIT",
    "CHK-PAST-EXTENT-EFUSE",
    "CHK-PAST-EXTENT-TIMER",
    "CHK-PAST-EXTENT-BASE-CONFIG",
    "CHK-PAST-EXTENT-FABRIC-CTRL",
    "CHK-PAST-EXTENT-SPARE",
    "CHK-PAST-EXTENT-PERIPH",
    "CHK-PAST-EXTENT-CLA",
)

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


class smc_past_extent_slverr_units_test_seq(SmcCsrSeq):
    """Probe the past-extent and last-word addresses of each SLVERR-declared unit on SEP_IN."""

    def __init__(self, name: str = "smc_past_extent_slverr_units_test_seq") -> None:
        super().__init__(name)
        self._stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []
        self.fuse_state = "not waited"

    def _mark_step(self, step_id: str) -> None:
        self._stamps.append((step_id, int(get_sim_time("ps"))))

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
            f"extent 0x{generated_decoded_extent(unit):X}{live_txt}"
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

    async def _observe_aperture_end(self, unit: str, tag: str) -> str:
        """UART and I3C declare no past-extent response: print the answers, assert nothing."""
        first, last = generated_window(unit)
        top = self._top_addr(unit)
        self.env.axi_monitor.expected_decerr_addrs.add(top)
        rresp, rdata = await self._observe_read(f"{tag}_TOP", top)
        bresp = await self._write_past(f"{tag}_TOP", top)
        rname = _RESP_NAMES.get(rresp, rresp)
        bname = _RESP_NAMES.get(bresp, bresp)
        cocotb.log.info(
            "island=%s addr=0x%08x bresp_declared=undeclared bresp_observed=%s", unit, top, bname
        )
        return (
            f"{unit} aperture 0x{LOCAL_BASE_RESET + first:08X}..0x{LOCAL_BASE_RESET + last:08X} "
            f"(generated_window, no past-extent response declared, owner value pending); "
            f"TOP@0x{top:08x} rresp={rname} rdata=0x{rdata:08X} bresp={bname}"
        )

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
            "CHK-TIMEOUT-PATHS: wait_fuse_sense_done sub-waits tb_fuse_sense_done, "
            "tb_fuse_reset_n, tb_rst_warm_smc_clk_n each bounded %d clk_smc_i rises, last "
            "observed %s; %d AXI accesses each bounded by the driver timeout %d ns "
            "(allow_timeout False), all answered; no other wait",
            FUSE_WAIT_BOUND_SMC_CYCLES,
            self.fuse_state,
            self.accesses,
            AXI_TIMEOUT_NS,
        )

    def nonvac_fence(self, floor: int) -> None:
        ids = tuple(s for s, _ in self._stamps)
        assert ids == _STEPS, f"step ids {ids}, want {_STEPS}"
        times = [t for _, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"step stamps not increasing: {times}"
        chk_ids = tuple(c for c, _ in self._chk_marks)
        assert chk_ids == _CHECKERS, f"checker lines {chk_ids}, want {_CHECKERS}"
        stamp_of = dict(self._stamps)
        for (chk_id, when), step in zip(self._chk_marks, _STEPS[1:]):
            assert when >= stamp_of[step], f"{chk_id} printed before its step {step} stamp"
        assert self.accesses >= floor, f"{self.accesses} accesses, floor {floor}"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence SETUP<RESET_UNIT<EFUSE<TIMER<BASE_CONFIG<FABRIC_CTRL<SPARE"
            "<PERIPH<CLA; checker lines %s; accesses %d >= floor %d; stamps %s",
            ",".join(chk_ids),
            self.accesses,
            floor,
            ",".join(f"{s}={t}" for s, t in self._stamps),
        )
