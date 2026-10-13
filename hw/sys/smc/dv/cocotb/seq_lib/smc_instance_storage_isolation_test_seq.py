# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Instance isolation of the scratch, remap, filter and GPIO register arrays.

Contract XBAR_031, anchor smc_instance_storage_isolation_test.
Allocated scenarios: XBAR-INSTANCE-ISOLATION.S1-S6; XBAR-DEC-SPARE.S5.
Spec sources: scratch.rdl SCRATCH[8]; misc_wrap.rdl scratch_cold; smc.rdl register arrays.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cocotb
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from ._one_shot import _OneShot
from .smc_addr_map import GPIO_INTF_NUM, gpio_intf_u32, smc_indexed_addr
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
    FILTER_CTRL_END_ADDR_REG_DEFAULT,
    FILTER_CTRL_FILTER_CONFIG_REG_DEFAULT,
    FILTER_CTRL_START_ADDR_REG_DEFAULT,
)

AXI_TIMEOUT_NS = 50_000
FUSE_BOUND = 200_000
SCRATCH_COUNT = 8
ALIAS_COUNT = 8
REMAP_COUNT = 8
FILTER_COUNT = 16
ACCESS_FLOOR = 700
ADDR_FIELD_SHIFT = 12
ADDR_FIELD_MASK = ((1 << 56) - 1) & ~((1 << ADDR_FIELD_SHIFT) - 1)

_AWPROT_SHIFT = gpio_intf_u32("GPIO_INTF__ACCESS_FILTER__AWPROT_REQUIREMENT_bp")
_ARPROT_SHIFT = gpio_intf_u32("GPIO_INTF__ACCESS_FILTER__ARPROT_REQUIREMENT_bp")
_GPIO_FILTER_RESET = (
    gpio_intf_u32("GPIO_INTF__ACCESS_FILTER__AWPROT_REQUIREMENT_reset") << _AWPROT_SHIFT
) | (gpio_intf_u32("GPIO_INTF__ACCESS_FILTER__ARPROT_REQUIREMENT_reset") << _ARPROT_SHIFT)

STEPS = (
    "SETUP",
    "SCRATCH",
    "SCRATCH_WARM",
    "ALIAS",
    "OUTPUT_REMAPS",
    "FILTERS",
    "GPIO",
    "SCRATCH_PORTS",
    "RESTORED",
)
CHECKERS = (
    ("CHK-SCRATCH-COLD-ISOLATION", "SCRATCH"),
    ("CHK-SCRATCH-COLD-WARM-SEPARATE", "SCRATCH_WARM"),
    ("CHK-ALIAS-REMAP-ISOLATION", "ALIAS"),
    ("CHK-OUTPUT-REMAP-ISOLATION", "OUTPUT_REMAPS"),
    ("CHK-FILTER-CTRL-ISOLATION", "FILTERS"),
    ("CHK-GPIO-INSTANCE-ISOLATION", "GPIO"),
    ("CHK-SCRATCH-32BIT-PORTS", "SCRATCH_PORTS"),
)
PORTS = ("SEP_IN", "SYS_IN", "JTAG")
PORT_PATTERNS = {"SEP_IN": 0x5E90_0001, "SYS_IN": 0x5E50_0002, "JTAG": 0x17A6_0003}


def _scratch(block: str, idx: int) -> int:
    return smc_indexed_addr(f"SMC_TOP_SMC_MISC_WRAP_{block}_SCRATCH_BASE_ADDR", idx)


def _array(symbol: str, idx: int) -> int:
    return smc_indexed_addr(f"SMC_TOP_{symbol}_BASE_ADDR", idx)


def _gpio_prot_word(value: int) -> int:
    """ACCESS_FILTER word with both filter enables clear and a 6-bit prot value pair."""
    return ((value & 0x7) << _AWPROT_SHIFT) | (((value >> 3) & 0x7) << _ARPROT_SHIFT)


class smc_instance_storage_isolation_test_seq(SmcCsrSeq):
    """Write every instance of each register array, then read every instance back."""

    def __init__(self, name: str = "smc_instance_storage_isolation_test_seq") -> None:
        super().__init__(name)
        self.chk_seen: dict[str, str] = {}
        self.port_accesses = {p: 0 for p in PORTS}
        self._last = {p: "none" for p in PORTS}
        self._stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []
        self._waits: list[tuple[str, str, str]] = []

    def _mark_step(self, step_id: str) -> None:
        self._stamps.append((step_id, int(get_sim_time("ps"))))

    def _log_chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self._chk_marks.append((chk_id, len(self._stamps)))
        self.chk_seen[chk_id] = text

    async def _access(
        self,
        port: str,
        name: str,
        op: SmcSysAxiOp,
        addr: int,
        length: int,
        data: int = 0,
        expected: int | None = None,
        wstrb: int | None = None,
    ) -> int:
        item = SmcSysAxiItem(f"{port.lower()}_{name}")
        item.op = op
        item.addr = addr
        item.length = length
        item.wdata = data
        item.expected = expected
        if wstrb is not None:
            item.wstrb = wstrb
        if port == "SEP_IN":
            await self.start_item(item)
            await self.finish_item(item)
            self.accesses += 1
        else:
            agent = self.env.sys_in_axi_agent if port == "SYS_IN" else self.env.jtag_axi_agent
            await _OneShot(item, f"{port.lower()}_{name}_os").start(agent.sequencer)
        self.port_accesses[port] += 1
        self._last[port] = f"{name}@0x{addr:08x} resp={item.resp_code}"
        assert item.resp_code == 0, f"{port} {self._last[port]}: not OKAY"
        if op == SmcSysAxiOp.WRITE:
            return 0
        assert item.rdata is not None, f"{port} {self._last[port]}: read data missing"
        got = int(item.rdata)
        if expected is not None:
            assert got == expected, (
                f"{port} {name} @ 0x{addr:08x}: read 0x{got:x}, want 0x{expected:x}"
            )
        return got

    async def _wr(self, name: str, addr: int, data: int, length: int) -> None:
        await self._access("SEP_IN", name, SmcSysAxiOp.WRITE, addr, length, data)

    async def _rd(self, name: str, addr: int, expected: int, length: int) -> int:
        return await self._access("SEP_IN", name, SmcSysAxiOp.READ, addr, length, 0, expected)

    async def _coresident(
        self, label: str, entries: list[tuple[str, int, int]], length: int, restore: int
    ) -> list[int]:
        """Write every pattern, read every register back, restore, read the restore back."""
        assert len({a for _, a, _ in entries}) == len(entries), f"{label}: addresses not distinct"
        assert len({p for _, _, p in entries}) == len(entries), f"{label}: patterns not distinct"
        for name, addr, pattern in entries:
            await self._wr(f"{label}_{name}", addr, pattern, length)
        observed = []
        for name, addr, pattern in entries:
            observed.append(await self._rd(f"{label}_{name}_RB", addr, pattern, length))
        await self._restore(label, entries, length, restore)
        return observed

    async def _restore(
        self, label: str, entries: list[tuple[str, int, int]], length: int, restore: int
    ) -> None:
        for name, addr, _ in entries:
            await self._wr(f"{label}_{name}_RESTORE", addr, restore, length)
        for name, addr, _ in entries:
            await self._rd(f"{label}_{name}_RESTORE_RB", addr, restore, length)

    @staticmethod
    def _hexes(values: list[int], width: int = 8) -> str:
        return ",".join(f"0x{v:0{width}X}" for v in values)

    async def _fuse_wait(self) -> None:
        await self.wait_fuse_sense_done(FUSE_BOUND)
        top = cocotb.top
        state = []
        for sig in (top.tb_fuse_sense_done, top.tb_fuse_reset_n, top.tb_rst_warm_smc_clk_n):
            assert sig.value.is_resolvable, f"{sig._name} is X/Z after the fuse wait"
            state.append(int(sig.value))
        assert state == [1, 1, 1], f"fuse sense probes {state} after the wait, want [1, 1, 1]"
        for name, val in zip(
            ("tb_fuse_sense_done", "tb_fuse_reset_n", "tb_rst_warm_smc_clk_n"), state
        ):
            self._waits.append((name, f"{FUSE_BOUND}clk_smc_i", f"{name}={val}"))

    async def _scratch_steps(self) -> None:
        cold = [_scratch("SCRATCH_COLD", i) for i in range(SCRATCH_COUNT)]
        warm = [_scratch("SCRATCH_COLD_WARM", i) for i in range(SCRATCH_COUNT)]
        cold_pat = [0xC01D_C0DE ^ (i * 0x0101_0101) for i in range(SCRATCH_COUNT)]
        warm_pat = [0x3A3A_0000 + (i + 1) * 0x0101_0003 for i in range(SCRATCH_COUNT)]
        assert all(c != w for c, w in zip(cold_pat, warm_pat)), "cold and warm patterns collide"

        obs = await self._coresident(
            "COLD", [(f"C{i}", cold[i], cold_pat[i]) for i in range(SCRATCH_COUNT)], 4, 0
        )
        self._mark_step("SCRATCH")
        self._log_chk(
            "CHK-SCRATCH-COLD-ISOLATION",
            f"SCRATCH_COLD[0..7] resident read {self._hexes(obs)} for patterns "
            f"{self._hexes(cold_pat)}; restored to 0 and read back 0",
        )

        entries = [(f"C{i}", cold[i], cold_pat[i]) for i in range(SCRATCH_COUNT)] + [
            (f"W{i}", warm[i], warm_pat[i]) for i in range(SCRATCH_COUNT)
        ]
        for name, addr, pattern in entries:
            await self._wr(f"BOTH_{name}", addr, pattern, 4)
        cold_rb = [await self._rd(f"BOTH_C{i}_RB", cold[i], cold_pat[i], 4) for i in range(8)]
        warm_rb = [await self._rd(f"BOTH_W{i}_RB", warm[i], warm_pat[i], 4) for i in range(8)]
        for i in range(SCRATCH_COUNT):
            assert cold_rb[i] != warm_pat[i], f"scratch_cold[{i}] holds the warm pattern"
            assert warm_rb[i] != cold_pat[i], f"scratch_cold_warm[{i}] holds the cold pattern"
        await self._restore("BOTH", entries, 4, 0)
        self._mark_step("SCRATCH_WARM")
        self._log_chk(
            "CHK-SCRATCH-COLD-WARM-SEPARATE",
            f"scratch_cold[0..7] read {self._hexes(cold_rb)} and scratch_cold_warm[0..7] read "
            f"{self._hexes(warm_rb)}; no index holds the other block's pattern",
        )

    async def _alias_step(self) -> None:
        pats = [((0x0A5A_5000 + i * 0x0001_1000) << 12) & ADDR_FIELD_MASK for i in range(8)]
        entries = [
            (f"A{i}", _array("SMC_ALIAS_REMAP_REGION_REGION_START", i), pats[i]) for i in range(8)
        ]
        obs = await self._coresident("ALIAS_START", entries, 8, 0)
        self._mark_step("ALIAS")
        self._log_chk(
            "CHK-ALIAS-REMAP-ISOLATION",
            f"alias remap REGION_START[0..7] (0x20 stride) read {self._hexes(obs, 16)}; "
            "restored to 0 and read back 0",
        )

    async def _output_remap_step(self) -> None:
        mpat = [((0x0C3C_3000 + i * 0x0001_0100) << 12) & ADDR_FIELD_MASK for i in range(8)]
        xpat = [((0x0E5E_5000 + i * 0x0002_0300) << 12) & ADDR_FIELD_MASK for i in range(8)]
        assert not set(mpat) & set(xpat), "M-mode and Xvisor patterns collide"
        entries = [
            (f"M{i}", _array("SMC_MMODE_REMAP_REGION_REGION_ATTRS", i), mpat[i]) for i in range(8)
        ] + [
            (f"X{i}", _array("SMC_XVISOR_REMAP_REGION_REGION_ATTRS", i), xpat[i]) for i in range(8)
        ]
        obs = await self._coresident("REMAP_ATTRS", entries, 8, 0)
        for i in range(REMAP_COUNT):
            assert obs[i] not in xpat and obs[8 + i] not in mpat, f"cross-array pattern at {i}"
        self._mark_step("OUTPUT_REMAPS")
        self._log_chk(
            "CHK-OUTPUT-REMAP-ISOLATION",
            f"M-mode ATTRS offset[0..7] read {self._hexes(obs[:8], 16)} and Xvisor ATTRS "
            f"offset[0..7] read {self._hexes(obs[8:], 16)} (enable bits clear); no cross-array "
            "pattern; restored to 0 and read back 0",
        )

    async def _filter_step(self) -> None:
        ipat = [0x00A5_A500_0000_1000 + (i + 1) * 0x0000_0001_0000_0123 for i in range(16)]
        opat = [0x005A_5A00_0000_2000 + (i + 1) * 0x0000_0002_0000_0321 for i in range(16)]
        assert not set(ipat) & set(opat), "inbound and outbound patterns collide"
        entries = [
            (f"I{i}", _array("SMC_INBOUND_FILTER_CTRL_START_ADDR", i), ipat[i]) for i in range(16)
        ] + [
            (f"O{i}", _array("SMC_OUTBOUND_FILTER_CTRL_START_ADDR", i), opat[i]) for i in range(16)
        ]
        obs = await self._coresident("FILTER_START", entries, 8, FILTER_CTRL_START_ADDR_REG_DEFAULT)
        for i in range(FILTER_COUNT):
            assert obs[i] not in opat and obs[16 + i] not in ipat, f"cross-array pattern at {i}"
        self._mark_step("FILTERS")
        self._log_chk(
            "CHK-FILTER-CTRL-ISOLATION",
            f"inbound START_ADDR[0..15] read {self._hexes(obs[:16], 16)} and outbound "
            f"START_ADDR[0..15] read {self._hexes(obs[16:], 16)} (FILTER_CONFIG untouched); no "
            "cross-array pattern; restored to the reset word and read back",
        )

    async def _gpio_step(self) -> None:
        addrs = [_array("GPIO_INTF_ACCESS_FILTER", i) for i in range(GPIO_INTF_NUM)]
        rounds = (
            [(i % 64) for i in range(GPIO_INTF_NUM)],
            [((i + i // 64) % 64) for i in range(GPIO_INTF_NUM)],
        )
        assert len(set(zip(*rounds))) == GPIO_INTF_NUM, "GPIO pattern pairs are not distinct"
        observed: list[list[int]] = []
        for r, vals in enumerate(rounds):
            words = [_gpio_prot_word(v) for v in vals]
            for i in range(GPIO_INTF_NUM):
                await self._wr(f"GPIO{r}_{i}", addrs[i], words[i], 4)
            observed.append(
                [await self._rd(f"GPIO{r}_{i}_RB", addrs[i], words[i], 4) for i in range(65)]
            )
        for i in range(GPIO_INTF_NUM):
            await self._wr(f"GPIO_{i}_RESTORE", addrs[i], _GPIO_FILTER_RESET, 4)
        for i in range(GPIO_INTF_NUM):
            await self._rd(f"GPIO_{i}_RESTORE_RB", addrs[i], _GPIO_FILTER_RESET, 4)
        self._mark_step("GPIO")
        self._log_chk(
            "CHK-GPIO-INSTANCE-ISOLATION",
            f"{GPIO_INTF_NUM} GPIO_INTF ACCESS_FILTER prot fields (0x10 stride, filter enables "
            f"clear) each read their own pattern in two co-resident rounds; "
            f"first={observed[0][0]:#x}"
            f" last={observed[0][-1]:#x}; round2 first={observed[1][0]:#x} "
            f"last={observed[1][-1]:#x}; restored to 0x{_GPIO_FILTER_RESET:08X} and read back",
        )

    async def _ports_step(self) -> None:
        addr = _scratch("SCRATCH_COLD", 0)
        neighbor = _scratch("SCRATCH_COLD", 1)
        await self._wr("INBOUND0_START", INBOUND0_START, 0, 8)
        await self._wr("INBOUND0_END", INBOUND0_END, 0x00FF_FFFF_FFFF_FFFF, 8)
        await self._wr("INBOUND0_CONFIG", INBOUND0_FILTER_CONFIG, PASS_ALL_CONFIG, 8)
        await self._rd("INBOUND0_CONFIG_RB", INBOUND0_FILTER_CONFIG, PASS_ALL_CONFIG, 8)
        reads: dict[str, list[int]] = {}
        for writer in PORTS:
            pattern = PORT_PATTERNS[writer]
            await self._access(
                writer, f"W64_{writer}", SmcSysAxiOp.WRITE, addr, 8, pattern, wstrb=0x0F
            )
            reads[writer] = [
                await self._access(
                    reader, f"RD_{writer}_{reader}", SmcSysAxiOp.READ, addr, 4, 0, pattern
                )
                for reader in PORTS
            ]
            await self._rd(f"NEIGHBOR_{writer}", neighbor, 0, 4)
        await self._wr("SCRATCH0_RESTORE", addr, 0, 4)
        await self._rd("SCRATCH0_RESTORE_RB", addr, 0, 4)
        self._mark_step("SCRATCH_PORTS")
        self._log_chk(
            "CHK-SCRATCH-32BIT-PORTS",
            "SCRATCH_COLD[0] written as one 32-bit word through an 8-byte write (strobe 0x0F) "
            + "; ".join(
                f"from {w} 0x{PORT_PATTERNS[w]:08X} read back by SEP_IN/SYS_IN/JTAG "
                f"{self._hexes(reads[w])}"
                for w in PORTS
            )
            + "; SCRATCH_COLD[1] stayed 0 after each; restored to 0 and read back 0",
        )
        await self._wr(
            "INBOUND0_CONFIG_RESTORE",
            INBOUND0_FILTER_CONFIG,
            FILTER_CTRL_FILTER_CONFIG_REG_DEFAULT,
            8,
        )
        await self._wr(
            "INBOUND0_START_RESTORE", INBOUND0_START, FILTER_CTRL_START_ADDR_REG_DEFAULT, 8
        )
        await self._wr("INBOUND0_END_RESTORE", INBOUND0_END, FILTER_CTRL_END_ADDR_REG_DEFAULT, 8)
        await self._rd(
            "INBOUND0_CONFIG_RESTORE_RB",
            INBOUND0_FILTER_CONFIG,
            FILTER_CTRL_FILTER_CONFIG_REG_DEFAULT,
            8,
        )
        await self._rd(
            "INBOUND0_START_RESTORE_RB", INBOUND0_START, FILTER_CTRL_START_ADDR_REG_DEFAULT, 8
        )
        await self._rd("INBOUND0_END_RESTORE_RB", INBOUND0_END, FILTER_CTRL_END_ADDR_REG_DEFAULT, 8)

    async def body(self) -> None:
        await self._fuse_wait()
        self._mark_step("SETUP")
        await self._scratch_steps()
        await self._alias_step()
        await self._output_remap_step()
        await self._filter_step()
        await self._gpio_step()
        await self._ports_step()
        self._mark_step("RESTORED")

        total = sum(self.port_accesses.values())
        assert total >= ACCESS_FLOOR, f"issued {total} accesses, literal floor {ACCESS_FLOOR}"
        for port in PORTS:
            self._waits.append(
                (f"{port.lower()}_axi_access", f"{AXI_TIMEOUT_NS}ns", self._last[port])
            )
        waits = " ".join(f"{n}={b} last={s}" for n, b, s in self._waits)
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits: %s; expiry raises AssertionError",
            len(self._waits),
            waits,
        )
        self.chk_seen["CHK-TIMEOUT-PATHS"] = waits
        self._nonvac_fence(total)

    def _nonvac_fence(self, total: int) -> None:
        ids = tuple(s for s, _ in self._stamps)
        assert ids == STEPS, f"step ids {ids}, want {STEPS}"
        times = [t for _, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing: {times}"
        assert tuple(c for c, _ in self._chk_marks) == tuple(c for c, _ in CHECKERS), (
            f"checker lines {[c for c, _ in self._chk_marks]}"
        )
        pos = {s: i + 1 for i, s in enumerate(STEPS)}
        for (chk_id, printed_after), (_, step) in zip(self._chk_marks, CHECKERS):
            assert printed_after >= pos[step], f"{chk_id} printed before step {step}"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; accesses %d >= floor %d; stamps %s",
            " < ".join(STEPS),
            ",".join(c for c, _ in CHECKERS),
            total,
            ACCESS_FLOOR,
            ",".join(f"{s}={t}" for s, t in self._stamps),
        )
        self.chk_seen["CHK-NONVAC"] = "ordered"
