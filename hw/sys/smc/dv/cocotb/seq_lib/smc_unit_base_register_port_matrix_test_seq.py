# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Base-register reset readback of the unit apertures from three ports at two bases.

Spec sources: smc.rdl unit and array placements, smc_base_config.rdl, dfx_ctrl_status.rdl,
memmap.adoc Address Space Organization, fabric.adoc Alias Remap Registers.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cocotb
from cocotb.triggers import ReadOnly, RisingEdge
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from ._one_shot import _OneShot
from .smc_addr_map import (
    DFX_STATUS_IDLE,
    GLOBAL_BASE_RESET,
    LOCAL_BASE_RESET,
    smc_addr,
    smc_indexed_addr,
)
from .smc_csr_seq_utils import SmcCsrSeq
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
    CHIP_CONFIG_VERSION_LO_REG_DEFAULT,
    CPU_CTRL_RESET_VECTOR_REG_DEFAULT,
    DFX_CTRL_STATUS_DEBUG_BUS_MUX_REG_DEFAULT,
    DFX_CTRL_STATUS_DEBUG_CTRL_REG_DEFAULT,
    DFX_CTRL_STATUS_STATUS_REG_DEFAULT,
    DMA_CTRL_DST_ADDRESS_LO_REG_DEFAULT,
    FILTER_CTRL_END_ADDR_REG_DEFAULT,
    FILTER_CTRL_FILTER_CONFIG_REG_DEFAULT,
    FILTER_CTRL_START_ADDR_REG_DEFAULT,
    NDM_RESET_NDMRESET_REQUEST_REG_DEFAULT,
    REMAP_REGION_REGION_ATTRS_REG_DEFAULT,
    REMAP_REGION_REGION_START_REG_DEFAULT,
    RESET_UNIT_SS_WARM_RESET_N_REG_DEFAULT,
    SCRATCH_SCRATCH_REG_DEFAULT,
    SMC_BASE_CONFIG_GLOBAL_BASE_REG_DEFAULT,
    SMC_BASE_CONFIG_HANG_DET_CTRL_REG_DEFAULT,
    SMC_BASE_CONFIG_HANG_DET_TIMEOUT_THRESHOLD_REG_DEFAULT,
    SMC_BASE_CONFIG_LOCAL_BASE_REG_DEFAULT,
    SMC_BASE_CONFIG_REGION_SIZE_REG_DEFAULT,
    WDT_CTRL_REG_DEFAULT,
    ZEROER_CTRL_DEST_ADDR_REG_DEFAULT,
)

FUSE_WAIT_BOUND_SMC_CYCLES = 200_000
AXI_TIMEOUT_NS = 50_000
PASS_ALL_END = 0x00FF_FFFF_FFFF_FFFF
WORD = 8
_MASK = {4: 0xFFFF_FFFF, 8: 0xFFFF_FFFF_FFFF_FFFF}
_RESP_OKAY = 0

BASES = (("LOCAL", LOCAL_BASE_RESET), ("GLOBAL", GLOBAL_BASE_RESET))
PORTS = ("SEP_IN", "SYS_IN", "JTAG")
_NO_SEP_PORTS = ("SYS_IN", "JTAG")

# Reset words stated by smc_base_config.rdl and chip_config.rdl.
VERSION_LO_RESET_WORD = 0x0001_00A0
GLOBAL_BASE_RESET_WORD = 0x4000_0000
LOCAL_BASE_RESET_WORD = 0xC000_0000
REGION_SIZE_RESET_WORD = 0x0100_0000
THRESHOLD_RESET_WORD = 0x1000
assert CHIP_CONFIG_VERSION_LO_REG_DEFAULT == VERSION_LO_RESET_WORD
assert (GLOBAL_BASE_RESET, LOCAL_BASE_RESET) == (GLOBAL_BASE_RESET_WORD, LOCAL_BASE_RESET_WORD)
assert SMC_BASE_CONFIG_GLOBAL_BASE_REG_DEFAULT == GLOBAL_BASE_RESET_WORD
assert SMC_BASE_CONFIG_LOCAL_BASE_REG_DEFAULT == LOCAL_BASE_RESET_WORD
assert SMC_BASE_CONFIG_REGION_SIZE_REG_DEFAULT == REGION_SIZE_RESET_WORD
assert SMC_BASE_CONFIG_HANG_DET_TIMEOUT_THRESHOLD_REG_DEFAULT == THRESHOLD_RESET_WORD

WDT_CTRLS = tuple(
    (f"CORE{n}_WDT_CTRL", smc_addr(f"SMC_TOP_SMC_CLUSTER_CORE{n}_WDT_CTRL_BASE_ADDR"))
    for n in range(4)
)
SS_WARM_RESET_N = smc_addr("SMC_TOP_SMC_RESET_UNIT_SS_WARM_RESET_N_BASE_ADDR")
SCRATCH_COLD_0 = smc_indexed_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_SCRATCH_BASE_ADDR", 0)
SCRATCH_COLD_WARM_0 = smc_indexed_addr(
    "SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_WARM_SCRATCH_BASE_ADDR", 0
)
VERSION_LO = smc_addr("SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_VERSION_LO_BASE_ADDR")
NDMRESET_REQUEST = smc_addr("SMC_TOP_SMC_MISC_WRAP_NDM_RESET_NDMRESET_REQUEST_BASE_ADDR")
GLOBAL_BASE = smc_addr("SMC_TOP_SMC_BASE_CONFIG_GLOBAL_BASE_BASE_ADDR")
LOCAL_BASE = smc_addr("SMC_TOP_SMC_BASE_CONFIG_LOCAL_BASE_BASE_ADDR")
REGION_SIZE = smc_addr("SMC_TOP_SMC_BASE_CONFIG_REGION_SIZE_BASE_ADDR")
HANG_DET_CTRLS = (
    ("SYS_AXI_CTRL", smc_addr("SMC_TOP_SMC_BASE_CONFIG_HANG_DET_SYS_AXI_CTRL_BASE_ADDR"), 0x20),
    ("SEP_AXI_CTRL", smc_addr("SMC_TOP_SMC_BASE_CONFIG_HANG_DET_SEP_AXI_CTRL_BASE_ADDR"), 0x30),
    (
        "DATA_ACCEL_CTRL",
        smc_addr("SMC_TOP_SMC_BASE_CONFIG_HANG_DET_DATA_ACCEL_CTRL_BASE_ADDR"),
        0x40,
    ),
)
HANG_DET_THRESHOLDS = (
    (
        "SYS_AXI_THRESHOLD",
        smc_addr("SMC_TOP_SMC_BASE_CONFIG_HANG_DET_SYS_AXI_TIMEOUT_THRESHOLD_BASE_ADDR"),
        0x28,
    ),
    (
        "SEP_AXI_THRESHOLD",
        smc_addr("SMC_TOP_SMC_BASE_CONFIG_HANG_DET_SEP_AXI_TIMEOUT_THRESHOLD_BASE_ADDR"),
        0x38,
    ),
    (
        "DATA_ACCEL_THRESHOLD",
        smc_addr("SMC_TOP_SMC_BASE_CONFIG_HANG_DET_DATA_ACCEL_TIMEOUT_THRESHOLD_BASE_ADDR"),
        0x48,
    ),
)
DFX_STATUS = smc_addr("SMC_TOP_DFX_CTRL_STATUS_SMU_BASE_ADDR")
DFX_DEBUG_CTRL = smc_addr("SMC_TOP_DFX_CTRL_DEBUG_CTRL_BASE_ADDR")
DFX_DEBUG_BUS_MUX = smc_addr("SMC_TOP_DFX_CTRL_DEBUG_BUS_MUX_BASE_ADDR")
DMA_DST_ADDRESS_LO = smc_addr("SMC_TOP_DMA_CTRL_DST_ADDRESS_LO_BASE_ADDR")
ZEROER_DEST_ADDR = smc_addr("SMC_TOP_ZEROER_CTRL_DEST_ADDR_BASE_ADDR")
RESET_VECTOR_0 = smc_indexed_addr("SMC_TOP_SMC_CPU_CTRL_RESET_VECTOR_BASE_ADDR", 0)

_ALIAS_START = "SMC_TOP_SMC_ALIAS_REMAP_REGION_REGION_START_BASE_ADDR"
_MMODE_ATTRS = "SMC_TOP_SMC_MMODE_REMAP_REGION_REGION_ATTRS_BASE_ADDR"
_XVISOR_ATTRS = "SMC_TOP_SMC_XVISOR_REMAP_REGION_REGION_ATTRS_BASE_ADDR"
_INBOUND_CONFIG = "SMC_TOP_SMC_INBOUND_FILTER_CTRL_FILTER_CONFIG_BASE_ADDR"
_OUTBOUND_CONFIG = "SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_FILTER_CONFIG_BASE_ADDR"
# (label, symbol, reset word, last index, spec offset of the last instance from the base)
ARRAYS = (
    ("ALIAS_REGION_START", _ALIAS_START, REMAP_REGION_REGION_START_REG_DEFAULT, 7, 0x1_20E0),
    ("MMODE_REGION_ATTRS", _MMODE_ATTRS, REMAP_REGION_REGION_ATTRS_REG_DEFAULT, 7, 0x1_3038),
    ("XVISOR_REGION_ATTRS", _XVISOR_ATTRS, REMAP_REGION_REGION_ATTRS_REG_DEFAULT, 7, 0x1_4038),
    ("INBOUND_FILTER_CONFIG", _INBOUND_CONFIG, FILTER_CTRL_FILTER_CONFIG_REG_DEFAULT, 15, 0x1_51E0),
    (
        "OUTBOUND_FILTER_CONFIG",
        _OUTBOUND_CONFIG,
        FILTER_CTRL_FILTER_CONFIG_REG_DEFAULT,
        15,
        0x1_61E0,
    ),
)
_ARRAY_FIRST_OFFSETS = (0x1_2000, 0x1_3000, 0x1_4000, 0x1_5000, 0x1_6000)
assert FILTER_CTRL_FILTER_CONFIG_REG_DEFAULT == 0x3000

DMA_PATTERN = 0xDA7A_0028
ZEROER_PATTERN = 0x2E20_0028

_STEPS = tuple(f"S{n}" for n in range(1, 13))
_FENCE_TERMS = (
    "FABRIC_PRE_SETUP",
    "SETUP",
    "WDT",
    "RESET_UNIT",
    "SPARE",
    "BASE_CONFIG",
    "HANG_DET",
    "DFX",
    "FABRIC_BASES",
    "FABRIC_LAST",
    "DMA_ZEROER",
    "CPU_CTRL",
)
_CHECKERS = (
    "CHK-WDT-BASE-PORTS",
    "CHK-RESET-UNIT-BASE-PORTS",
    "CHK-SPARE-FIRST-REGS-PORTS",
    "CHK-BASE-CONFIG-RESETS-PORTS",
    "CHK-HANG-DET-RESETS",
    "CHK-DFX-REGS-PORTS",
    "CHK-FABRIC-ARRAY-BASES-PORTS",
    "CHK-FABRIC-ARRAY-LAST-INSTANCE",
    "CHK-DMA-ZEROER-BASE-PORTS",
    "CHK-CPU-CTRL-FIRST-REG-PORTS",
)
_CHECKER_STEPS = ("S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10", "S11", "S12")


class smc_unit_base_register_port_matrix_test_seq(SmcCsrSeq):
    """Read the base register of each unit aperture from SEP_IN, SYS_IN and JTAG."""

    def __init__(self, name: str = "smc_unit_base_register_port_matrix_test_seq") -> None:
        super().__init__(name)
        self._stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []
        self.fuse_state = "not waited"
        self.hit_state = "not run"
        self._hit_stop = False
        self._hit_samples = 0
        self._hit_high = 0

    def _mark_step(self, step_id: str) -> None:
        self._stamps.append((step_id, int(get_sim_time("ps"))))

    def _log_chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self._chk_marks.append((chk_id, int(get_sim_time("ps"))))

    async def _access(
        self, port: str, label: str, write: bool, addr: int, length: int, wdata: int = 0
    ) -> SmcSysAxiItem:
        item = SmcSysAxiItem(f"{'wr' if write else 'rd'}_{port.lower()}_{label}")
        item.op = SmcSysAxiOp.WRITE if write else SmcSysAxiOp.READ
        item.addr = addr
        item.length = length
        if write:
            item.wdata = wdata
        if port == "SEP_IN":
            await self.start_item(item)
            await self.finish_item(item)
        else:
            agent = self.env.sys_in_axi_agent if port == "SYS_IN" else self.env.jtag_axi_agent
            await _OneShot(item, f"{item.get_name()}_os").start(agent.sequencer)
        self.accesses += 1
        assert item.resp_code == _RESP_OKAY, (
            f"{port} {label} @ 0x{addr:08x}: resp {item.resp_code}, want OKAY "
            f"(rdata 0x{item.rdata:x})"
        )
        return item

    async def _read(
        self, port: str, label: str, addr: int, length: int, expected: int | None
    ) -> int:
        item = await self._access(port, label, False, addr, length)
        got = item.rdata & _MASK[length]
        if expected is not None:
            assert got == expected, (
                f"{port} {label} @ 0x{addr:08x}: read 0x{got:x}, want 0x{expected:x}"
            )
        return got

    async def _matrix(
        self,
        label: str,
        local_addr: int,
        length: int,
        expected: int | None,
        ports: tuple[str, ...] = PORTS,
    ) -> list[tuple[str, str, int]]:
        """Read a LOCAL_BASE-relative register from each port at both bases."""
        got = []
        for bname, base in BASES:
            for port in ports:
                addr = base + (local_addr - LOCAL_BASE_RESET)
                got.append(
                    (
                        port,
                        bname,
                        await self._read(port, f"{label}_{bname}", addr, length, expected),
                    )
                )
        return got

    @staticmethod
    def _values(got: list[tuple[str, str, int]]) -> str:
        return ",".join(f"{p}.{b[0]}=0x{v:X}" for p, b, v in got)

    async def _reg_line(self, label: str, addr: int, length: int, expected: int | None) -> str:
        got = await self._matrix(label, addr, length, expected)
        rule = f"RDL reset 0x{expected:X}" if expected is not None else "observe-only"
        return f"{label}@0x{addr:08X} {rule} [{self._values(got)}]"

    async def _watch_inbound_hit(self) -> None:
        dut = cocotb.top
        while not self._hit_stop:
            await RisingEdge(dut.clk_smc_i)
            await ReadOnly()
            hit = dut.tb_inb_read_hit.value
            assert hit.is_resolvable, f"tb_inb_read_hit is X/Z ({hit})"
            self._hit_samples += 1
            self._hit_high += int(hit) & 1

    async def body(self) -> None:
        await self.wait_fuse_sense_done(FUSE_WAIT_BOUND_SMC_CYCLES)
        dut = cocotb.top
        states = []
        for name in ("tb_fuse_sense_done", "tb_fuse_reset_n", "tb_rst_warm_smc_clk_n"):
            sig = getattr(dut, name)
            assert sig.value.is_resolvable, f"{name} is X/Z after the wait"
            states.append(f"{name}={int(sig.value)}")
        self.fuse_state = ",".join(states)

        # S1: array base registers over SEP_IN and JTAG before anything is programmed.
        first_addrs = []
        for (label, symbol, reset, _last, _off), offset in zip(ARRAYS, _ARRAY_FIRST_OFFSETS):
            addr = smc_indexed_addr(symbol, 0)
            assert addr - LOCAL_BASE_RESET == offset, f"{label} base 0x{addr:x} off the spec"
            first_addrs.append((label, addr, reset))
        pre = []
        for label, addr, reset in first_addrs:
            got = await self._matrix(f"PRE_{label}", addr, WORD, reset, ("SEP_IN", "JTAG"))
            pre.append(f"{label}@0x{addr:08X}=0x{reset:X} [{self._values(got)}]")
        self._mark_step("S1")

        # S2: inbound entry 0 pass-all over SEP_IN.
        await self.csr_write("INBOUND0_START_PASS_ALL", INBOUND0_START, 0, length=WORD)
        await self.csr_write("INBOUND0_END_PASS_ALL", INBOUND0_END, PASS_ALL_END, length=WORD)
        await self.csr_write(
            "INBOUND0_CONFIG_PASS_ALL", INBOUND0_FILTER_CONFIG, PASS_ALL_CONFIG, length=WORD
        )
        self._mark_step("S2")

        # S3: watchdog CTRL registers.
        wdt = [
            await self._reg_line(label, addr, 4, WDT_CTRL_REG_DEFAULT) for label, addr in WDT_CTRLS
        ]
        self._mark_step("S3")
        self._log_chk("CHK-WDT-BASE-PORTS", "; ".join(wdt) + " all OKAY, 24 reads")

        # S4: reset unit SS_WARM_RESET_N at its generated address.
        line = await self._reg_line(
            "SS_WARM_RESET_N", SS_WARM_RESET_N, 4, RESET_UNIT_SS_WARM_RESET_N_REG_DEFAULT
        )
        self._mark_step("S4")
        self._log_chk(
            "CHK-RESET-UNIT-BASE-PORTS",
            f"{line} (generated address offset 0x{SS_WARM_RESET_N - LOCAL_BASE_RESET:X} from "
            f"the base; the readback is not stated in a document)",
        )

        # S5: first register of each spare sub-block.
        spare = [
            await self._reg_line("SCRATCH_COLD_0", SCRATCH_COLD_0, 4, SCRATCH_SCRATCH_REG_DEFAULT),
            await self._reg_line(
                "SCRATCH_COLD_WARM_0", SCRATCH_COLD_WARM_0, 4, SCRATCH_SCRATCH_REG_DEFAULT
            ),
            await self._reg_line("VERSION_LO", VERSION_LO, 4, VERSION_LO_RESET_WORD),
            await self._reg_line(
                "NDMRESET_REQUEST", NDMRESET_REQUEST, 4, NDM_RESET_NDMRESET_REQUEST_REG_DEFAULT
            ),
        ]
        self._mark_step("S5")
        self._log_chk(
            "CHK-SPARE-FIRST-REGS-PORTS",
            "; ".join(spare) + " all OKAY; VERSION_LO is the non-zero compare, the 0x0 compares "
            "cannot fail on X under Verilator zero-init",
        )

        # S6: base configuration registers.
        base_cfg = [
            await self._reg_line("GLOBAL_BASE", GLOBAL_BASE, WORD, GLOBAL_BASE_RESET_WORD),
            await self._reg_line("LOCAL_BASE", LOCAL_BASE, WORD, LOCAL_BASE_RESET_WORD),
            await self._reg_line("REGION_SIZE", REGION_SIZE, WORD, REGION_SIZE_RESET_WORD),
        ]
        self._mark_step("S6")
        self._log_chk("CHK-BASE-CONFIG-RESETS-PORTS", "; ".join(base_cfg) + " all OKAY")

        # S7: hang detector registers over SEP_IN at LOCAL_BASE.
        hang = []
        for label, addr, offset in HANG_DET_CTRLS + HANG_DET_THRESHOLDS:
            assert addr - LOCAL_BASE_RESET == 0x1_0000 + offset, f"{label} offset off the spec"
            want = (
                THRESHOLD_RESET_WORD
                if label.endswith("THRESHOLD")
                else SMC_BASE_CONFIG_HANG_DET_CTRL_REG_DEFAULT
            )
            got = await self._read("SEP_IN", f"{label}_LOCAL", addr, 4, want)
            hang.append(f"{label}@0x{addr:08X}=0x{got:X}")
        self._mark_step("S7")
        self._log_chk(
            "CHK-HANG-DET-RESETS",
            f"{'; '.join(hang)}; controls read 0x{SMC_BASE_CONFIG_HANG_DET_CTRL_REG_DEFAULT:X}, "
            f"thresholds 0x{THRESHOLD_RESET_WORD:X}, SEP_IN at LOCAL_BASE, all OKAY",
        )

        # S8: DFX registers; STATUS is observe-only.
        status = await self._matrix("DFX_STATUS", DFX_STATUS, WORD, None)
        ctrl = await self._reg_line(
            "DEBUG_CTRL", DFX_DEBUG_CTRL, 4, DFX_CTRL_STATUS_DEBUG_CTRL_REG_DEFAULT
        )
        mux = await self._reg_line(
            "DEBUG_BUS_MUX", DFX_DEBUG_BUS_MUX, WORD, DFX_CTRL_STATUS_DEBUG_BUS_MUX_REG_DEFAULT
        )
        self._mark_step("S8")
        status_words = {v for _, _, v in status}
        self._log_chk(
            "CHK-DFX-REGS-PORTS",
            f"STATUS@0x{DFX_STATUS:08X} observe-only (not specified, measured) "
            f"[{self._values(status)}] vs RDL reset 0x{DFX_CTRL_STATUS_STATUS_REG_DEFAULT:X} match="
            f"{int(status_words == {DFX_CTRL_STATUS_STATUS_REG_DEFAULT})} (tie-off word "
            f"0x{DFX_STATUS_IDLE:X}); {ctrl}; {mux}; all OKAY",
        )

        # S9: array base registers over SYS_IN; inbound entry 0 returns the pass-all word.
        self._hit_stop = False
        watcher = cocotb.start_soon(self._watch_inbound_hit())
        bases = []
        for label, addr, reset in first_addrs:
            want = PASS_ALL_CONFIG if label == "INBOUND_FILTER_CONFIG" else reset
            got = await self._matrix(f"SYS_{label}", addr, WORD, want, ("SYS_IN",))
            bases.append(f"{label}@0x{addr:08X}=0x{want:X} [{self._values(got)}]")
        self._hit_stop = True
        assert self._hit_high > 0, (
            f"tb_inb_read_hit[0] never high in {self._hit_samples} clk_smc_i samples of S9"
        )
        self.hit_state = f"{self._hit_high} high of {self._hit_samples} samples"
        self._mark_step("S9")
        self._log_chk(
            "CHK-FABRIC-ARRAY-BASES-PORTS",
            f"pre-setup SEP_IN and JTAG at both bases: {'; '.join(pre)}; SYS_IN at both bases "
            f"after setup: {'; '.join(bases)}; inbound entry 0 returns the pass-all word "
            f"0x{PASS_ALL_CONFIG:X} with tb_inb_read_hit[0] high for {self._hit_high} of "
            f"{self._hit_samples} samples",
        )
        del watcher

        # S10: last instance of each array at the generated stride.
        last = []
        for label, symbol, reset, idx, offset in ARRAYS:
            addr = smc_indexed_addr(symbol, idx)
            assert addr - LOCAL_BASE_RESET == offset, f"{label}[{idx}] 0x{addr:x} off stride"
            got = await self._matrix(f"LAST_{label}", addr, WORD, reset)
            last.append(f"{label}[{idx}]@0x{addr:08X}=0x{reset:X} [{self._values(got)}]")
        self._mark_step("S10")
        self._log_chk("CHK-FABRIC-ARRAY-LAST-INSTANCE", "; ".join(last) + " all OKAY")

        # S11: DMA and zeroer base registers, then co-resident patterns written over SEP_IN.
        dma = await self._reg_line(
            "DMA_DST_ADDRESS_LO", DMA_DST_ADDRESS_LO, 4, DMA_CTRL_DST_ADDRESS_LO_REG_DEFAULT
        )
        zer = await self._reg_line(
            "ZEROER_DEST_ADDR", ZEROER_DEST_ADDR, 4, ZEROER_CTRL_DEST_ADDR_REG_DEFAULT
        )
        assert DMA_PATTERN != ZEROER_PATTERN, "co-resident patterns not distinct"
        await self._access("SEP_IN", "DMA_PATTERN", True, DMA_DST_ADDRESS_LO, 4, DMA_PATTERN)
        await self._access("SEP_IN", "ZEROER_PATTERN", True, ZEROER_DEST_ADDR, 4, ZEROER_PATTERN)
        seen = []
        for port, base in (("SYS_IN", GLOBAL_BASE_RESET), ("JTAG", LOCAL_BASE_RESET)):
            for label, addr, pattern in (
                ("DMA_DST_ADDRESS_LO", DMA_DST_ADDRESS_LO, DMA_PATTERN),
                ("ZEROER_DEST_ADDR", ZEROER_DEST_ADDR, ZEROER_PATTERN),
            ):
                got = await self._read(
                    port, f"{label}_PATTERN", base + (addr - LOCAL_BASE_RESET), 4, pattern
                )
                seen.append(f"{port}.{label}=0x{got:X}")
        await self._access("SEP_IN", "DMA_RESTORE", True, DMA_DST_ADDRESS_LO, 4, 0)
        await self._access("SEP_IN", "ZEROER_RESTORE", True, ZEROER_DEST_ADDR, 4, 0)
        await self._read("SEP_IN", "DMA_RESTORE_RB", DMA_DST_ADDRESS_LO, 4, 0)
        await self._read("SEP_IN", "ZEROER_RESTORE_RB", ZEROER_DEST_ADDR, 4, 0)
        self._mark_step("S11")
        self._log_chk(
            "CHK-DMA-ZEROER-BASE-PORTS",
            f"{dma}; {zer}; co-resident patterns DMA 0x{DMA_PATTERN:X} and zeroer "
            f"0x{ZEROER_PATTERN:X} written over SEP_IN read back [{','.join(seen)}], then "
            f"restored to 0 and read back 0; the zero resets alone cannot fail on X under "
            f"Verilator zero-init",
        )

        # S12: CPU control RESET_VECTOR_0, SEP_IN reachability precheck first.
        pre_cpu = await self._read(
            "SEP_IN",
            "RESET_VECTOR_0_PRECHECK",
            RESET_VECTOR_0,
            WORD,
            CPU_CTRL_RESET_VECTOR_REG_DEFAULT,
        )
        cpu = await self._matrix(
            "RESET_VECTOR_0", RESET_VECTOR_0, WORD, CPU_CTRL_RESET_VECTOR_REG_DEFAULT, _NO_SEP_PORTS
        )
        self._mark_step("S12")
        self._log_chk(
            "CHK-CPU-CTRL-FIRST-REG-PORTS",
            f"RESET_VECTOR_0@0x{RESET_VECTOR_0:08X} RDL reset "
            f"0x{CPU_CTRL_RESET_VECTOR_REG_DEFAULT:X} (not specified, measured): "
            f"SEP_IN.L=0x{pre_cpu:X} [{self._values(cpu)}] all OKAY",
        )

        # Restore the inbound entry 0 reset word.
        await self.csr_write(
            "INBOUND0_CONFIG_RESTORE",
            INBOUND0_FILTER_CONFIG,
            FILTER_CTRL_FILTER_CONFIG_REG_DEFAULT,
            length=WORD,
        )
        await self.csr_write(
            "INBOUND0_START_RESTORE", INBOUND0_START, FILTER_CTRL_START_ADDR_REG_DEFAULT, WORD
        )
        await self.csr_write(
            "INBOUND0_END_RESTORE", INBOUND0_END, FILTER_CTRL_END_ADDR_REG_DEFAULT, length=WORD
        )
        await self.csr_read(
            "INBOUND0_CONFIG_RESTORE_RB",
            INBOUND0_FILTER_CONFIG,
            expected=FILTER_CTRL_FILTER_CONFIG_REG_DEFAULT,
            length=WORD,
        )

    def log_timeout_paths(self) -> None:
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: wait_fuse_sense_done sub-waits tb_fuse_sense_done, "
            "tb_fuse_reset_n, tb_rst_warm_smc_clk_n each bounded %d clk_smc_i rises, last "
            "observed %s; %d AXI accesses on SEP_IN, SYS_IN and JTAG each bounded by the driver "
            "timeout %d ns (allow_timeout False), all answered; tb_inb_read_hit watcher over "
            "the S9 reads ends on a stop flag after the last SYS_IN read, last observed %s; "
            "no other wait",
            FUSE_WAIT_BOUND_SMC_CYCLES,
            self.fuse_state,
            self.accesses,
            AXI_TIMEOUT_NS,
            self.hit_state,
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
            "CHK-NONVAC: ordered fence %s; checker lines %s; accesses %d >= floor %d; stamps %s",
            "<".join(_FENCE_TERMS),
            ",".join(chk_ids),
            self.accesses,
            floor,
            ",".join(f"{s}={t}" for s, t in self._stamps),
        )
