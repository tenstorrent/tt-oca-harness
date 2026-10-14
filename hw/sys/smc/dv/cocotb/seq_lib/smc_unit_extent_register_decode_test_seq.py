# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Base and last register decode of the mailbox, eFuse, timer, CLA, DMA and zeroer apertures.

Spec sources: smc.rdl unit placements and past-extent, memmap.adoc Address Space Organization,
fabric.adoc Fabric Topology.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cocotb
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from ._one_shot import _OneShot
from .smc_addr_map import (
    _REPO,
    GLOBAL_BASE_RESET,
    LOCAL_BASE_RESET,
    SPM_MEMORY_BASE,
    SPM_MEMORY_SIZE,
    reg_reset_word,
    smc_addr,
    smc_indexed_addr,
)
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_efuse_vip_utils import efuse_preload_word_at
from .smc_output_fabric_vip_utils import (
    INBOUND0_END,
    INBOUND0_FILTER_CONFIG,
    INBOUND0_START,
    PASS_ALL_CONFIG,
)

_SMC_REG_PY = Path(__file__).resolve().parents[3] / "regs" / "gen" / "py"
if str(_SMC_REG_PY) not in sys.path:
    sys.path.insert(0, str(_SMC_REG_PY))

from smc_reg import (  # noqa: E402
    AXIL_MAILBOX_CTRL_REG_DEFAULT,
    AXIL_MAILBOX_WRITE_DATA_REG_DEFAULT,
    CHIP_CONFIG_LC_STATE_REG_DEFAULT,
    DMA_CTRL_NUM_REPETITIONS_HI_REG_DEFAULT,
    EFUSE_INTERFACE_CTRL_EFUSE_PROGRAM_REQ_TIMEOUT_REG_DEFAULT,
    EFUSE_INTERFACE_CTRL_EFUSE_READ_REQ_TIMEOUT_REG_DEFAULT,
    FILTER_CTRL_END_ADDR_REG_DEFAULT,
    FILTER_CTRL_FILTER_CONFIG_REG_DEFAULT,
    FILTER_CTRL_START_ADDR_REG_DEFAULT,
    NDM_RESET_NDMRESET_CLUSTER_COUNT_REG_DEFAULT,
    SCRATCH_SCRATCH_REG_DEFAULT,
    SYSTEM_TIMER_OCTS_CTRL_REG_DEFAULT,
    SYSTEM_TIMER_OCTS_TIMER_GPIO_ENABLE_REG_DEFAULT,
    SYSTEM_TIMER_OCTS_TIMER_START_REG_DEFAULT,
    ZEROER_CTRL_CTRL_STATUS_REG_DEFAULT,
)

FUSE_WAIT_BOUND_SMC_CYCLES = 200_000
AXI_TIMEOUT_NS = 50_000
PASS_ALL_END = 0x00FF_FFFF_FFFF_FFFF
WORD = 8
_MASK32 = 0xFFFF_FFFF
_MASK64 = 0xFFFF_FFFF_FFFF_FFFF

BASES = (("LOCAL", LOCAL_BASE_RESET), ("GLOBAL", GLOBAL_BASE_RESET))
PORTS = ("SEP_IN", "SYS_IN", "JTAG")

_CLA_H = _REPO / "hw" / "ip" / "dfd" / "regs" / "gen" / "c" / "smc_cla.h"
CLA_TRDSTRAMIMPL_RESET = reg_reset_word(_CLA_H, "DFD_DST_SINK", "TRDSTRAMIMPL")

MAILBOX_OUT0_FIRST = smc_addr("SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_WRITE_DATA_BASE_ADDR")
EFUSE_MAP_FIRST = smc_addr("SMC_TOP_SMC_EFUSE_MAP_BASE_ADDR")
EFUSE_CTRL_FIRST = smc_addr("SMC_TOP_EFUSE_INTERFACE_CTRL_BASE_ADDR")
EFUSE_READ_REQ_TIMEOUT = smc_addr("SMC_TOP_EFUSE_INTERFACE_CTRL_EFUSE_READ_REQ_TIMEOUT_BASE_ADDR")
EFUSE_PROGRAM_REQ_TIMEOUT = smc_addr(
    "SMC_TOP_EFUSE_INTERFACE_CTRL_EFUSE_PROGRAM_REQ_TIMEOUT_BASE_ADDR"
)
TIMER_FIRST = smc_addr("SMC_TOP_SMC_SYSTEM_TIMER_OCTS_BASE_ADDR")
TIMER_CTRL = smc_addr("SMC_TOP_SMC_SYSTEM_TIMER_OCTS_CTRL_BASE_ADDR")
TIMER_LAST = smc_addr("SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_GPIO_ENABLE_BASE_ADDR")
CLA_TRDSTRAMIMPL = smc_addr("SMC_TOP_SMC_CLA_DST_SINK_TRDSTRAMIMPL_BASE_ADDR")
MAILBOX_IN31_LAST = smc_addr("SMC_TOP_SMC_MAILBOX_INBOUND_MAILBOX_31_CTRL_BASE_ADDR")
ROM_FIRST = smc_addr("SMC_TOP_SPM_ROM_MEMORY_BASE_ADDR")
ROM_LAST = ROM_FIRST + smc_addr("SMC_TOP_SPM_ROM_MEMORY_SIZE") - WORD
SPM_LAST = SPM_MEMORY_BASE + SPM_MEMORY_SIZE - WORD
SCRATCH_COLD_7 = smc_indexed_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_SCRATCH_BASE_ADDR", 7)
SCRATCH_COLD_WARM_7 = smc_indexed_addr(
    "SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_WARM_SCRATCH_BASE_ADDR", 7
)
LC_STATE = smc_addr("SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_LC_STATE_BASE_ADDR")
CLUSTER_COUNT = smc_addr("SMC_TOP_SMC_MISC_WRAP_NDM_RESET_NDMRESET_CLUSTER_COUNT_BASE_ADDR")
DMA_LAST = smc_addr("SMC_TOP_DMA_CTRL_NUM_REPETITIONS_HI_BASE_ADDR")
DMA_DST_ADDRESS_LO = smc_addr("SMC_TOP_DMA_CTRL_DST_ADDRESS_LO_BASE_ADDR")
ZEROER_LAST = smc_addr("SMC_TOP_ZEROER_CTRL_CTRL_STATUS_BASE_ADDR")
ZEROER_DEST_ADDR = smc_addr("SMC_TOP_ZEROER_CTRL_DEST_ADDR_BASE_ADDR")

SPM_PATTERN_SEP = {SPM_MEMORY_BASE: 0xA5A5_5A5A_1122_3344, SPM_LAST: 0x5A5A_A5A5_8877_6655}
SPM_PATTERN_JTAG = {SPM_MEMORY_BASE: 0xC3C3_3C3C_0F0F_F0F0, SPM_LAST: 0x3C3C_C3C3_F0F0_0F0F}
SCRATCH_PATTERN = 0x5AC3_A53C
DMA_PATTERN = 0xDA7A_0001
ZEROER_PATTERN = 0x2E20_0002

_STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7")
_CHECKERS = (
    "CHK-MAILBOX-BASE-PORTS",
    "CHK-EFUSE-BASE-PORTS",
    "CHK-TIMER-BASE-PORTS",
    "CHK-CLA-BASE-PORTS",
    "CHK-ROM-WORDS-PORTS",
    "CHK-SPM-WORDS-BASES",
    "CHK-SPARE-LAST-REGS",
    "CHK-LAST-REG-MAILBOX-EFUSE-TIMER",
    "CHK-LAST-REG-DMA-ZEROER",
)
_CHECKER_STEPS = ("S2", "S2", "S2", "S2", "S3", "S4", "S5", "S6", "S7")

# Last registers sit at the end of the declared extent of their unit.
assert EFUSE_PROGRAM_REQ_TIMEOUT + 4 == EFUSE_CTRL_FIRST + smc_addr(
    "SMC_TOP_EFUSE_INTERFACE_CTRL_SIZE"
)
assert TIMER_LAST + 4 == TIMER_FIRST + smc_addr("SMC_TOP_SMC_SYSTEM_TIMER_OCTS_SIZE")
assert MAILBOX_IN31_LAST + 8 == smc_addr(
    "SMC_TOP_SMC_MAILBOX_INBOUND_MAILBOX_31_BASE_ADDR"
) + smc_addr("SMC_TOP_SMC_MAILBOX_INBOUND_MAILBOX_31_SIZE")
assert DMA_LAST + 4 == smc_addr("SMC_TOP_DMA_CTRL_BASE_ADDR") + smc_addr("SMC_TOP_DMA_CTRL_SIZE")
assert ZEROER_LAST + 8 == smc_addr("SMC_TOP_ZEROER_CTRL_BASE_ADDR") + smc_addr(
    "SMC_TOP_ZEROER_CTRL_SIZE"
)


class smc_unit_extent_register_decode_test_seq(SmcCsrSeq):
    """Read base and last registers and memory words over SEP_IN, SYS_IN and JTAG."""

    def __init__(self, name: str = "smc_unit_extent_register_decode_test_seq") -> None:
        super().__init__(name)
        self._stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []
        self.fuse_state = "not waited"

    def _mark_step(self, step_id: str) -> None:
        self._stamps.append((step_id, int(get_sim_time("ps"))))

    def _log_chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self._chk_marks.append((chk_id, int(get_sim_time("ps"))))

    async def _access(
        self,
        port: str,
        label: str,
        write: bool,
        addr: int,
        *,
        length: int = 4,
        wdata: int = 0,
        expected: int | None = None,
    ) -> SmcSysAxiItem:
        item = SmcSysAxiItem(f"{'wr' if write else 'rd'}_{port.lower()}_{label}")
        item.op = SmcSysAxiOp.WRITE if write else SmcSysAxiOp.READ
        item.addr = addr
        item.length = length
        if write:
            item.wdata = wdata
        else:
            item.expected = expected
        if port == "SEP_IN":
            await self.start_item(item)
            await self.finish_item(item)
        else:
            agent = self.env.sys_in_axi_agent if port == "SYS_IN" else self.env.jtag_axi_agent
            await _OneShot(item, f"{item.get_name()}_os").start(agent.sequencer)
        self.accesses += 1
        assert item.resp_code == 0, f"{port} {label} @ 0x{addr:08x}: resp {item.resp_code}"
        return item

    async def _read(
        self,
        port: str,
        label: str,
        addr: int,
        length: int = 4,
        expected: int | None = None,
    ) -> int:
        item = await self._access(port, label, False, addr, length=length, expected=expected)
        got = item.rdata & (_MASK64 if length == WORD else _MASK32)
        if expected is not None:
            assert got == expected, (
                f"{port} {label} @ 0x{addr:08x}: read 0x{got:x}, want 0x{expected:x}"
            )
        return got

    async def _read_ports_bases(
        self, label: str, addr: int, expected: int | None, length: int = 4
    ) -> list[tuple[str, str, int]]:
        """Read ``addr`` (a local-base address) from every port at both bases."""
        got = []
        for bname, base in BASES:
            for port in PORTS:
                value = await self._read(
                    port,
                    f"{label}_{bname}",
                    base + (addr - LOCAL_BASE_RESET),
                    length,
                    expected,
                )
                got.append((port, bname, value))
        values = {v for _, _, v in got}
        assert len(values) == 1, f"{label} @ 0x{addr:08x}: ports/bases disagree " + ",".join(
            f"{p}.{b}=0x{v:x}" for p, b, v in got
        )
        return got

    async def _base_reg(self, label: str, addr: int, expected: int | None) -> str:
        got = await self._read_ports_bases(label, addr, expected)
        value = got[0][2]
        rule = f"RDL reset 0x{expected:08X}" if expected is not None else "observe-only"
        return f"{label}@0x{addr:08X}=0x{value:08X} ({rule}) on {len(got)} port-base reads"

    async def _word_check(self, label: str, addr: int, pattern: int, port: str, base: int) -> None:
        await self._read(port, label, base + (addr - LOCAL_BASE_RESET), WORD, pattern)

    async def body(self) -> None:
        await self.wait_fuse_sense_done(FUSE_WAIT_BOUND_SMC_CYCLES)
        dut = cocotb.top
        states = []
        for name in ("tb_fuse_sense_done", "tb_fuse_reset_n", "tb_rst_warm_smc_clk_n"):
            sig = getattr(dut, name)
            assert sig.value.is_resolvable, f"{name} is X/Z after the wait"
            states.append(f"{name}={int(sig.value)}")
        self.fuse_state = ",".join(states)

        # S1: inbound entry 0 pass-all over SEP_IN.
        await self.csr_write("INBOUND0_CONFIG_PASS_ALL", INBOUND0_FILTER_CONFIG, PASS_ALL_CONFIG, 8)
        await self.csr_write("INBOUND0_START_PASS_ALL", INBOUND0_START, 0, length=8)
        await self.csr_write("INBOUND0_END_PASS_ALL", INBOUND0_END, PASS_ALL_END, length=8)
        await self.csr_read(
            "INBOUND0_CONFIG_PASS_ALL_RB",
            INBOUND0_FILTER_CONFIG,
            expected=PASS_ALL_CONFIG,
            length=8,
        )
        self._mark_step("S1")

        # S2: base registers from three ports at both bases.
        mailbox = await self._base_reg("OUT0_WRITE_DATA", MAILBOX_OUT0_FIRST, None)
        efuse_map = await self._base_reg(
            "EFUSE_MAP_W0", EFUSE_MAP_FIRST, efuse_preload_word_at(EFUSE_MAP_FIRST)
        )
        efuse_status = await self._base_reg("EFUSE_STATUS", EFUSE_CTRL_FIRST, None)
        efuse_timeout = await self._base_reg(
            "EFUSE_READ_REQ_TIMEOUT",
            EFUSE_READ_REQ_TIMEOUT,
            EFUSE_INTERFACE_CTRL_EFUSE_READ_REQ_TIMEOUT_REG_DEFAULT,
        )
        timer_start = await self._base_reg(
            "OCTS_TIMER_START", TIMER_FIRST, SYSTEM_TIMER_OCTS_TIMER_START_REG_DEFAULT
        )
        timer_ctrl = await self._base_reg(
            "OCTS_CTRL", TIMER_CTRL, SYSTEM_TIMER_OCTS_CTRL_REG_DEFAULT
        )
        cla = await self._base_reg("TRDSTRAMIMPL", CLA_TRDSTRAMIMPL, CLA_TRDSTRAMIMPL_RESET)
        self._mark_step("S2")
        self._log_chk(
            "CHK-MAILBOX-BASE-PORTS",
            f"{mailbox} (write-only register, readback word is not an RDL reset, "
            f"RDL default 0x{AXIL_MAILBOX_WRITE_DATA_REG_DEFAULT & _MASK32:X}; OKAY and equality "
            f"across ports only)",
        )
        self._log_chk(
            "CHK-EFUSE-BASE-PORTS",
            f"{efuse_map}; {efuse_status} (sense status is hardware driven, "
            f"equality across ports only); {efuse_timeout}",
        )
        self._log_chk("CHK-TIMER-BASE-PORTS", f"{timer_start}; {timer_ctrl}")
        self._log_chk("CHK-CLA-BASE-PORTS", f"{cla} through the 32-bit APB path")

        # S3: first and last ROM words from three ports at both bases.
        rom_parts = []
        rom_values = []
        for label, addr in (("ROM_FIRST", ROM_FIRST), ("ROM_LAST", ROM_LAST)):
            got = await self._read_ports_bases(label, addr, None, WORD)
            rom_values.append(got[0][2])
            rom_parts.append(f"{label}@0x{addr:08X}=0x{got[0][2]:016X}")
        spm_patterns = set(SPM_PATTERN_SEP.values()) | set(SPM_PATTERN_JTAG.values())
        assert not spm_patterns & set(rom_values), f"ROM word equals an SPM pattern {rom_values}"
        self._mark_step("S3")
        self._log_chk(
            "CHK-ROM-WORDS-PORTS",
            f"{'; '.join(rom_parts)} identical on {len(PORTS)} ports x {len(BASES)} bases, all "
            f"OKAY, differ from the SPM patterns (no spec value for the word)",
        )

        # S4: SPM words written through one base and port, read through the other.
        spm_words = (SPM_MEMORY_BASE, SPM_LAST)
        for addr in spm_words:
            await self._access(
                "SEP_IN", "SPM_W_LOCAL", True, addr, length=WORD, wdata=SPM_PATTERN_SEP[addr]
            )
        for addr in spm_words:
            await self._word_check(
                "SPM_SEP_RB", addr, SPM_PATTERN_SEP[addr], "SEP_IN", LOCAL_BASE_RESET
            )
        for addr in spm_words:
            await self._word_check(
                "SPM_SYS_RB", addr, SPM_PATTERN_SEP[addr], "SYS_IN", GLOBAL_BASE_RESET
            )
        for addr in spm_words:
            await self._access(
                "JTAG",
                "SPM_W_GLOBAL",
                True,
                GLOBAL_BASE_RESET + (addr - LOCAL_BASE_RESET),
                length=WORD,
                wdata=SPM_PATTERN_JTAG[addr],
            )
        for addr in spm_words:
            await self._word_check(
                "SPM_JTAG_RB", addr, SPM_PATTERN_JTAG[addr], "JTAG", GLOBAL_BASE_RESET
            )
        for addr in spm_words:
            await self._word_check(
                "SPM_SEP_RB2", addr, SPM_PATTERN_JTAG[addr], "SEP_IN", LOCAL_BASE_RESET
            )
        for addr in spm_words:
            await self._access("SEP_IN", "SPM_RESTORE", True, addr, length=WORD, wdata=0)
        for addr in spm_words:
            await self._word_check("SPM_RESTORE_RB", addr, 0, "SEP_IN", LOCAL_BASE_RESET)
        self._mark_step("S4")
        self._log_chk(
            "CHK-SPM-WORDS-BASES",
            f"SPM first 0x{SPM_MEMORY_BASE:08X} and last 0x{SPM_LAST:08X} words: SEP_IN write "
            f"through LOCAL read back through LOCAL (SEP_IN) and GLOBAL (SYS_IN) as "
            f"0x{SPM_PATTERN_SEP[SPM_MEMORY_BASE]:016X}/0x{SPM_PATTERN_SEP[SPM_LAST]:016X}; "
            f"JTAG write through GLOBAL read back through GLOBAL (JTAG) and LOCAL (SEP_IN) as "
            f"0x{SPM_PATTERN_JTAG[SPM_MEMORY_BASE]:016X}/0x{SPM_PATTERN_JTAG[SPM_LAST]:016X}; "
            f"both words restored to 0 and read back 0",
        )

        # S5: spare sub-block last registers over SEP_IN.
        for name, addr in (("COLD", SCRATCH_COLD_7), ("COLD_WARM", SCRATCH_COLD_WARM_7)):
            await self.csr_read(
                f"SCRATCH_{name}_7_RESET", addr, expected=SCRATCH_SCRATCH_REG_DEFAULT
            )
            await self.csr_write_readback(f"SCRATCH_{name}_7", addr, SCRATCH_PATTERN)
            await self.csr_restore(f"SCRATCH_{name}_7", addr, SCRATCH_SCRATCH_REG_DEFAULT)
        lc_state = await self.csr_read("LC_STATE", LC_STATE)
        cluster_count = await self.csr_read("NDMRESET_CLUSTER_COUNT", CLUSTER_COUNT)
        self._mark_step("S5")
        self._log_chk(
            "CHK-SPARE-LAST-REGS",
            f"SCRATCH_COLD[7]@0x{SCRATCH_COLD_7:08X} and SCRATCH_COLD_WARM[7]@"
            f"0x{SCRATCH_COLD_WARM_7:08X} read reset 0x{SCRATCH_SCRATCH_REG_DEFAULT:X} and "
            f"round-trip 0x{SCRATCH_PATTERN:08X}; LC_STATE@0x{LC_STATE:08X}=0x{lc_state:08X} "
            f"(RDL reset 0x{CHIP_CONFIG_LC_STATE_REG_DEFAULT:X}) and NDMRESET_CLUSTER_COUNT@"
            f"0x{CLUSTER_COUNT:08X}=0x{cluster_count:08X} (RDL reset "
            f"0x{NDM_RESET_NDMRESET_CLUSTER_COUNT_REG_DEFAULT:X}) hardware driven, observe-only "
            f"(owner value pending)",
        )

        # S6: last registers of mailbox, eFuse interface control and system timer.
        mbox_last = await self.csr_read("MBOX_IN31_CTRL", MAILBOX_IN31_LAST)
        efuse_last = await self.csr_read(
            "EFUSE_PROGRAM_REQ_TIMEOUT",
            EFUSE_PROGRAM_REQ_TIMEOUT,
            expected=EFUSE_INTERFACE_CTRL_EFUSE_PROGRAM_REQ_TIMEOUT_REG_DEFAULT,
        )
        timer_last = await self.csr_read(
            "OCTS_TIMER_GPIO_ENABLE",
            TIMER_LAST,
            expected=SYSTEM_TIMER_OCTS_TIMER_GPIO_ENABLE_REG_DEFAULT,
        )
        self._mark_step("S6")
        self._log_chk(
            "CHK-LAST-REG-MAILBOX-EFUSE-TIMER",
            f"INBOUND_MAILBOX_31 CTRL@0x{MAILBOX_IN31_LAST:08X}=0x{mbox_last:08X} (write-only, "
            f"RDL default 0x{AXIL_MAILBOX_CTRL_REG_DEFAULT & _MASK32:X}, observe-only); "
            f"eFuse PROGRAM_REQ_TIMEOUT@0x{EFUSE_PROGRAM_REQ_TIMEOUT:08X}="
            f"0x{efuse_last:08X}; OCTS "
            f"TIMER_GPIO_ENABLE@0x{TIMER_LAST:08X}=0x{timer_last:08X}; eFuse and timer OKAY "
            f"at their RDL reset, mailbox OKAY",
        )

        # S7: DMA and zeroer last registers with distinct patterns in their first registers.
        await self.csr_write_readback("DMA_DST_ADDRESS_LO", DMA_DST_ADDRESS_LO, DMA_PATTERN)
        await self.csr_write_readback("ZEROER_DEST_ADDR", ZEROER_DEST_ADDR, ZEROER_PATTERN)
        dma_last = await self.csr_read(
            "DMA_NUM_REPETITIONS_HI", DMA_LAST, expected=DMA_CTRL_NUM_REPETITIONS_HI_REG_DEFAULT
        )
        dma_pat = await self.csr_read("DMA_DST_ADDRESS_LO_KEPT", DMA_DST_ADDRESS_LO, DMA_PATTERN)
        zer_last = await self.csr_read(
            "ZEROER_CTRL_STATUS", ZEROER_LAST, expected=ZEROER_CTRL_CTRL_STATUS_REG_DEFAULT
        )
        zer_pat = await self.csr_read("ZEROER_DEST_ADDR_KEPT", ZEROER_DEST_ADDR, ZEROER_PATTERN)
        await self.csr_restore("DMA_DST_ADDRESS_LO", DMA_DST_ADDRESS_LO, 0)
        await self.csr_restore("ZEROER_DEST_ADDR", ZEROER_DEST_ADDR, 0)
        self._mark_step("S7")
        self._log_chk(
            "CHK-LAST-REG-DMA-ZEROER",
            f"DMA NUM_REPETITIONS_HI@0x{DMA_LAST:08X}=0x{dma_last:08X} with DST_ADDRESS_LO "
            f"holding 0x{dma_pat:08X}; zeroer CTRL_STATUS@0x{ZEROER_LAST:08X}=0x{zer_last:08X} "
            f"with DEST_ADDR holding 0x{zer_pat:08X}; both patterns kept, no collapse",
        )

        # Restore the inbound entry to its reset.
        await self.csr_write(
            "INBOUND0_CONFIG_RESTORE",
            INBOUND0_FILTER_CONFIG,
            FILTER_CTRL_FILTER_CONFIG_REG_DEFAULT,
            8,
        )
        await self.csr_write(
            "INBOUND0_START_RESTORE", INBOUND0_START, FILTER_CTRL_START_ADDR_REG_DEFAULT, length=8
        )
        await self.csr_write(
            "INBOUND0_END_RESTORE", INBOUND0_END, FILTER_CTRL_END_ADDR_REG_DEFAULT, length=8
        )
        await self.csr_read(
            "INBOUND0_CONFIG_RESTORE_RB",
            INBOUND0_FILTER_CONFIG,
            expected=FILTER_CTRL_FILTER_CONFIG_REG_DEFAULT,
            length=8,
        )

    def log_timeout_paths(self) -> None:
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: wait_fuse_sense_done sub-waits tb_fuse_sense_done, "
            "tb_fuse_reset_n, tb_rst_warm_smc_clk_n each bounded %d clk_smc_i rises, last "
            "observed %s; %d AXI accesses on SEP_IN, SYS_IN and JTAG each bounded by the driver "
            "timeout %d ns (allow_timeout False), all answered; no other wait",
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
        for (chk_id, when), step in zip(self._chk_marks, _CHECKER_STEPS):
            assert when >= stamp_of[step], f"{chk_id} printed before its step {step} stamp"
        assert self.accesses >= floor, f"{self.accesses} accesses, floor {floor}"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence SETUP<BASE_REGS<ROM_WORDS<SPM_WORDS<SPARE_LAST<"
            "MAILBOX_EFUSE_TIMER_LAST<DMA_ZEROER_LAST; checker lines %s; accesses %d >= floor "
            "%d; stamps %s",
            ",".join(chk_ids),
            self.accesses,
            floor,
            ",".join(f"{s}={t}" for s, t in self._stamps),
        )
