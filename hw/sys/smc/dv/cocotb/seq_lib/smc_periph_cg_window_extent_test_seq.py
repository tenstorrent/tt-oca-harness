# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Gated peripheral window extent, isolation, write delivery and the AVSBus clock pad.

Sources: hw/sys/smc/regs/smc.rdl, hw/sys/smc/doc/memmap.adoc, hw/sys/smc/doc/clk_rst.adoc.

With one peripheral enable of CLOCK_GATE_CONTROL set, the window of that peripheral answers
SLVERR with 0xBADCAB1E at a registered and at an unbacked address, while the other windows and
CLOCK_GATE_CONTROL answer OKAY with their clear-state values. The last 4-byte address of each
window, the effect of a refused write and the rises of the AVSBus clock pad are printed.
"""

from __future__ import annotations

import cocotb
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import (
    AVS_CG_EN,
    CLOCK_GATE_CONTROL,
    I2C_CG_EN,
    I3C_CG_EN,
    LOCAL_BASE_RESET,
    TELEMETRY_CG_EN,
    UART_CG_EN,
    generated_window,
    smc_addr,
    smc_indexed_addr,
)
from .smc_cg_obs_utils import count_gated_rising, sample_bit
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_i3c_to_fabric_test_seq import HCI_VERSION_OFFSET

AXI_RESP_SLVERR = 2
GATED_RDATA = SmcCsrSeq.ERR_SLAVE_SIGNATURE
AVS_CLK_PROBE = "tb_avs_clk_from_dut"
AVS_COUNT_CYCLES = 256
ALL_PERIPH_CG_EN = AVS_CG_EN | I2C_CG_EN | UART_CG_EN | TELEMETRY_CG_EN | I3C_CG_EN
RESP_NAMES = {0: "OKAY", 1: "EXOKAY", 2: "SLVERR", 3: "DECERR"}

# (name, enable, memory-map unit, probe register, probe address, unbacked offset inside the
#  decoded extent, writable register, writable address)
PERIPHERALS: tuple[tuple[str, int, str, str, int, int, str, int], ...] = (
    (
        "AVSBUS",
        AVS_CG_EN,
        "smc_avsbus_controller",
        "AVS_CFG_0",
        smc_addr("SMC_TOP_SMC_AVSBUS_CONTROLLER_AVS_CFG_0_BASE_ADDR"),
        0x10,
        "AVS_CFG_0",
        smc_addr("SMC_TOP_SMC_AVSBUS_CONTROLLER_AVS_CFG_0_BASE_ADDR"),
    ),
    (
        "I2C",
        I2C_CG_EN,
        "smc_i2c_wrap",
        "I2C_CTRL_0",
        smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR", 0),
        0x100,
        "I2C_CTRL_0",
        smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR", 0),
    ),
    (
        "UART",
        UART_CG_EN,
        "smc_uart_wrap",
        "UART0_LOG_ENGINE_CTRL",
        smc_indexed_addr(
            "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_CTRL_BASE_ADDR", 0
        ),
        0x300,
        "UART0_LOG_ENGINE_CTRL",
        smc_indexed_addr(
            "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_CTRL_BASE_ADDR", 0
        ),
    ),
    (
        "TELEMETRY",
        TELEMETRY_CG_EN,
        "smc_telemetry_receiver_wrap",
        "TELEMETRY0_CTRL",
        smc_indexed_addr(
            "SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_TELEMETRY_RECEIVER_CTRL_BASE_ADDR", 0
        ),
        0x40,
        "TELEMETRY0_CTRL",
        smc_indexed_addr(
            "SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_TELEMETRY_RECEIVER_CTRL_BASE_ADDR", 0
        ),
    ),
    (
        "I3C",
        I3C_CG_EN,
        "oca_i3c_wrap",
        "I3C0_HCI_VERSION",
        smc_indexed_addr("SMC_TOP_OCA_I3C_WRAP_I3C_CSR_BASE_ADDR", 0) + HCI_VERSION_OFFSET,
        0x70,
        "I3C0_DEV_CTX_BASE_LO",
        smc_indexed_addr("SMC_TOP_OCA_I3C_WRAP_I3C_CSR_I3CBASE_DEV_CTX_BASE_LO_BASE_ADDR", 0),
    ),
)
NAMES = [p[0] for p in PERIPHERALS]
STEP_IDS = ("S1", "S2", "S3", "S4", "S5", "S6")
CHK_STEP = {
    "CHK-WINDOW-EXTENT": "S2",
    "CHK-WINDOW-ISOLATION": "S3",
    "CHK-WINDOW-WRITE-DELIVERY-PRINT": "S4",
    "CHK-AVS-CLOCK-PRINT": "S5",
}


class smc_periph_cg_window_extent_test_seq(SmcCsrSeq):
    """Set each peripheral enable alone and probe its window, the others and the AVSBus pad."""

    def __init__(self, name: str = "smc_periph_cg_window_extent_test_seq") -> None:
        super().__init__(name)
        self.steps: list[tuple[str, int]] = []
        self.chk_lines: list[tuple[str, str, int]] = []

    def _stamp(self, step: str) -> None:
        self.steps.append((step, int(get_sim_time("ps"))))

    def _chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self.chk_lines.append((chk_id, self.steps[-1][0], int(get_sim_time("ps"))))

    async def _read_any_resp(self, name: str, addr: int) -> tuple[int, int]:
        item = SmcSysAxiItem(f"rd_{name}")
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = 4
        item.allow_error = True
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        assert item.resp_code is not None, f"{name} @ 0x{addr:08x}: no response code"
        return item.resp_code, item.rdata & 0xFFFF_FFFF

    async def _read_ungated(self, name: str, addr: int, expected: int | None = None) -> int:
        return await self.csr_read(name, addr, expected=expected)

    async def _set_alone(self, tag: str, base: int, cg_en: int) -> int:
        value = base | cg_en
        await self.csr_write(f"CLOCK_GATE_CONTROL_{tag}_ON", CLOCK_GATE_CONTROL, value)
        await self.csr_read(f"CLOCK_GATE_CONTROL_{tag}_ON", CLOCK_GATE_CONTROL, expected=value)
        return value

    async def _clear(self, tag: str, base: int) -> None:
        await self.csr_write(f"CLOCK_GATE_CONTROL_{tag}_OFF", CLOCK_GATE_CONTROL, base)
        await self.csr_read(f"CLOCK_GATE_CONTROL_{tag}_OFF", CLOCK_GATE_CONTROL, expected=base)

    async def body(self) -> None:
        dut = cocotb.top
        assert hasattr(dut, AVS_CLK_PROBE), f"{AVS_CLK_PROBE} is not exported by tb_top"

        # S1: save, clear the five enables, record the clear-state probe words.
        original = await self.csr_read("CLOCK_GATE_CONTROL_SAVE", CLOCK_GATE_CONTROL)
        base = original & ~ALL_PERIPH_CG_EN
        await self._clear("ALL", base)
        clear_words = {}
        for name, _en, _unit, reg, addr, _unb, _wreg, _waddr in PERIPHERALS:
            clear_words[name] = await self._read_ungated(f"{name}_{reg}_CLEAR", addr)
        self._stamp("S1")

        # S2: registered, unbacked and window-end reads with the enable set alone.
        extent_lines = []
        for name, en, unit, reg, addr, unbacked_off, _wreg, _waddr in PERIPHERALS:
            first, last = generated_window(unit)
            win_base = LOCAL_BASE_RESET + first
            win_end = LOCAL_BASE_RESET + last - 3
            unbacked = win_base + unbacked_off
            assert win_base <= addr <= win_end and unbacked <= win_end, f"{name}: window bounds"
            gated = await self._set_alone(f"{name}_EXTENT", base, en)
            await self.csr_read_err_signature(f"{name}_{reg}_REG", addr, resp=AXI_RESP_SLVERR)
            await self.csr_read_err_signature(f"{name}_UNBACKED", unbacked, resp=AXI_RESP_SLVERR)
            end_resp, end_data = await self._read_any_resp(f"{name}_WINDOW_END", win_end)
            await self._clear(f"{name}_EXTENT", base)
            extent_lines.append(
                f"{name} window 0x{win_base:08x}..0x{win_end + 3:08x} "
                f"CLOCK_GATE_CONTROL=0x{gated:x}: "
                f"registered {reg} @ 0x{addr:08x} and unbacked @ 0x{unbacked:08x} answered "
                f"SLVERR with 0x{GATED_RDATA:08X}; window-end @ 0x{win_end:08x} answered "
                f"{RESP_NAMES.get(end_resp, end_resp)} data 0x{end_data:08x} "
                f"(extent owner value pending)"
            )
        self._stamp("S2")
        for line in extent_lines:
            self._chk("CHK-WINDOW-EXTENT", line)

        # S3: the other windows and CLOCK_GATE_CONTROL stay reachable with clear-state values.
        isolation_lines = []
        for name, en, _unit, _reg, _addr, _unb, _wreg, _waddr in PERIPHERALS:
            gated = await self._set_alone(f"{name}_ISOLATION", base, en)
            others = []
            for oname, _oen, _ounit, oreg, oaddr, _ounb, _owreg, _owaddr in PERIPHERALS:
                if oname == name:
                    continue
                await self._read_ungated(
                    f"{oname}_{oreg}_WHILE_{name}", oaddr, expected=clear_words[oname]
                )
                others.append(f"{oname}.{oreg}=0x{clear_words[oname]:08x}")
            await self._clear(f"{name}_ISOLATION", base)
            isolation_lines.append(
                f"{name} enable set alone, CLOCK_GATE_CONTROL read back 0x{gated:x}: "
                f"other windows OKAY with clear-state values {' '.join(others)}"
            )
        self._stamp("S3")
        for line in isolation_lines:
            self._chk("CHK-WINDOW-ISOLATION", line)

        # S4: a write to a gated window is refused; print the word before and after.
        delivery_lines = []
        for name, en, _unit, _reg, _addr, _unb, wreg, waddr in PERIPHERALS:
            before = await self._read_ungated(f"{name}_{wreg}_BEFORE", waddr)
            pattern = (~before) & 0xFFFF_FFFF
            gated = await self._set_alone(f"{name}_DELIVERY", base, en)
            resp = await self.csr_write_expect_error(
                f"{name}_{wreg}_GATED", waddr, pattern, resp=AXI_RESP_SLVERR
            )
            await self._clear(f"{name}_DELIVERY", base)
            after = await self._read_ungated(f"{name}_{wreg}_AFTER", waddr)
            delivery_lines.append(
                f"{name} {wreg} @ 0x{waddr:08x}: write 0x{pattern:08x} with CLOCK_GATE_CONTROL="
                f"0x{gated:x} answered {RESP_NAMES[resp]}; word before 0x{before:08x}, after "
                f"enable cleared 0x{after:08x}, unchanged={before == after} (owner value pending)"
            )
        self._stamp("S4")
        for line in delivery_lines:
            self._chk("CHK-WINDOW-WRITE-DELIVERY-PRINT", line)

        # S5: rises of the AVSBus clock pad with avs_cg_en clear and set.
        sample_bit(dut, AVS_CLK_PROBE)
        rises_clear = await count_gated_rising(dut, AVS_CLK_PROBE, AVS_COUNT_CYCLES)
        sample_bit(dut, AVS_CLK_PROBE)
        await self._set_alone("AVS_CLOCK", base, AVS_CG_EN)
        sample_bit(dut, AVS_CLK_PROBE)
        rises_set = await count_gated_rising(dut, AVS_CLK_PROBE, AVS_COUNT_CYCLES)
        level_set = sample_bit(dut, AVS_CLK_PROBE)
        await self._clear("AVS_CLOCK", base)
        self._stamp("S5")
        self._chk(
            "CHK-AVS-CLOCK-PRINT",
            f"{AVS_CLK_PROBE} rises over {AVS_COUNT_CYCLES} clk_smc_i cycles: avs_cg_en clear "
            f"{rises_clear}, avs_cg_en set {rises_set} (level {level_set} at the end of the set "
            f"window; owner value pending)",
        )

        # S6: restore.
        await self.csr_write("CLOCK_GATE_CONTROL_RESTORE", CLOCK_GATE_CONTROL, original)
        await self.csr_read("CLOCK_GATE_CONTROL_RESTORE", CLOCK_GATE_CONTROL, expected=original)
        self._stamp("S6")

        # CHK-NONVAC: ordered fence over the step stamps and the checker lines.
        assert [s for s, _t in self.steps] == list(STEP_IDS), f"step order {self.steps}"
        times = [t for _s, t in self.steps]
        for prev, nxt in zip(times, times[1:]):
            assert nxt > prev, f"step stamps not strictly increasing: {self.steps}"
        stamp_of = dict(self.steps)
        chk_ids = [c for c, _s, _t in self.chk_lines]
        expected_ids = (
            ["CHK-WINDOW-EXTENT"] * len(PERIPHERALS)
            + ["CHK-WINDOW-ISOLATION"] * len(PERIPHERALS)
            + ["CHK-WINDOW-WRITE-DELIVERY-PRINT"] * len(PERIPHERALS)
            + ["CHK-AVS-CLOCK-PRINT"]
        )
        assert chk_ids == expected_ids, f"checker lines out of order: {chk_ids}"
        last_t = 0
        for chk_id, step, t in self.chk_lines:
            assert CHK_STEP[chk_id] == step, f"{chk_id} printed in {step}"
            assert t >= stamp_of[step] and t >= last_t, f"{chk_id} printed before {step} stamp"
            last_t = t
        cocotb.log.info(
            "CHK-NONVAC: ordered fence S1 setup, S2 extent, S3 isolation, S4 write delivery, "
            "S5 avs clock, S6 restore; checker lines CHK-WINDOW-EXTENT, CHK-WINDOW-ISOLATION, "
            "CHK-WINDOW-WRITE-DELIVERY-PRINT, CHK-AVS-CLOCK-PRINT; stamps %s ps",
            " ".join(f"{s}={t}" for s, t in self.steps),
        )
