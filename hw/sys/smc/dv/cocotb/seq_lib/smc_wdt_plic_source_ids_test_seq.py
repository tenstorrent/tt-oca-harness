# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Cluster watchdog first-stage timeouts at PLIC source IDs 329 to 332.

Sources: hw/sys/smc/doc/interrupts.adoc (PLIC Sources and Contexts, "Cluster watchdogs 0-3 ->
PLIC IDs 329-332, added by the cluster interrupt crossbar"), hw/sys/smc/regs/blocks/wdt/wdt.rdl,
hw/sys/smc/regs/blocks/plic/plic.rdl.

Each core's watchdog is armed over SEP_IN so its first-stage `wdogip0` sets. The bench probes
`tb_plic_pending_329` to `tb_plic_pending_332` read the PLIC pending bits of sources 329 to 332;
the one that rises is the armed core's, the other three keep their entry level and the raw
328-bit vector does not move. The PLIC then claims the source on context 0, and the claim word
is the software-visible ID the chapter states.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge
from cocotb.utils import get_sim_time

from .smc_addr_map import _REPO, REGION_SIZE_RESET, _field_mask, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq

WDT_MAGIC_KEY = 0x51F15E
WDT_CMP_ARM = 0x0040
WDT_CMP_CLEAR = 0x0100
WDT_CTRL_SCALE8 = 0x0008
WDT_COUNT_ARM = 0x0000_4400
WDT_CTRL_WDOGIP0_BM = _field_mask(
    _REPO / "hw" / "sys" / "smc" / "regs" / "gen" / "c" / "blocks" / "wdt.h",
    "WDT__CTRL__WDOGIP0_bm",
)
CORES = 4
WDT_FIRST_ID = 329
RAW_VECTOR_WIDTH = 328
WINDOW = 64
QUIET_RISES = 16
REGION_SIZE_256M = 0x1000_0000
REGION_SIZE = smc_addr("SMC_TOP_SMC_BASE_CONFIG_REGION_SIZE_BASE_ADDR")
PLIC = "SMC_TOP_SMC_CLUSTER_PLIC_"
CTX0 = "CORE0_MEIP"
STEPS = ("S1", "S2", "S3", "S4")
CHK_ORDER = (
    ("CHK-WDT-PLIC-ID-329-332", "S3"),
    ("CHK-TIMEOUT-PATHS", "S4"),
)


def _wdt_reg(core: int, reg: str) -> int:
    return smc_addr(f"SMC_TOP_SMC_CLUSTER_CORE{core}_WDT_{reg}_BASE_ADDR")


def _priority_addr(source: int) -> int:
    return smc_indexed_addr(PLIC + "PRIORITY_BASE_ADDR", source)


def _enable_addr(word: int) -> int:
    return smc_indexed_addr(PLIC + f"{CTX0}_ENABLE_BASE_ADDR", word)


THRESHOLD0 = smc_addr(PLIC + f"{CTX0}_THRESHOLD_BASE_ADDR")
CLAIM0 = smc_addr(PLIC + f"{CTX0}_CLAIM_COMPLETE_BASE_ADDR")


class smc_wdt_plic_source_ids_test_seq(SmcCsrSeq):
    """Arm each core's watchdog and compare the pending probe and the claim word with 329 + core."""

    def __init__(self, name: str = "smc_wdt_plic_source_ids_test_seq") -> None:
        super().__init__(name)
        self.chk_seen: set[str] = set()
        self._stamps: list[tuple[str, int]] = []
        self._chk_order: list[tuple[str, int]] = []

    def _stamp(self, step: str) -> None:
        self._stamps.append((step, int(get_sim_time("ps"))))

    def _chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self._chk_order.append((chk_id, len(self._stamps)))
        self.chk_seen.add(chk_id)

    @staticmethod
    def _bit(name: str) -> int:
        sig = getattr(cocotb.top, name)
        assert sig.value.is_resolvable, f"{name} = {sig.value} is X/Z"
        return int(sig.value)

    def _pending(self) -> tuple[int, ...]:
        return tuple(self._bit(f"tb_plic_pending_{WDT_FIRST_ID + n}") for n in range(CORES))

    async def _keyed(self, core: int, reg: str, value: int) -> None:
        await self.csr_write(f"WDT{core}_KEY", _wdt_reg(core, "KEY"), WDT_MAGIC_KEY)
        await self.csr_write(f"WDT{core}_{reg}", _wdt_reg(core, reg), value)

    async def _arm(self, core: int) -> None:
        await self._keyed(core, "CMP", WDT_CMP_ARM)
        await self._keyed(core, "CTRL", WDT_CTRL_SCALE8)
        await self._keyed(core, "COUNT", WDT_COUNT_ARM)

    async def _disarm(self, core: int) -> int:
        await self._keyed(core, "CMP", WDT_CMP_CLEAR)
        await self._keyed(core, "CTRL", WDT_CTRL_SCALE8)
        await self._keyed(core, "COUNT", 0)
        await self._keyed(core, "CTRL", 0)
        return await self.csr_read(f"WDT{core}_CTRL_AFTER_CLEAR", _wdt_reg(core, "CTRL"))

    async def _rise_window(self, core: int, before: tuple[int, ...], raw0: int) -> int:
        """Rises until the armed core's probe reads 1; the others and the raw vector hold."""
        clk = cocotb.top.clk_smc_i
        seen = None
        for n in range(1, WINDOW + 1):
            await RisingEdge(clk)
            now = self._pending()
            raw = self._bit("tb_cpu_interrupts")
            others = [m for m in range(CORES) if m != core and now[m] != before[m]]
            assert not others, (
                f"CHK-WDT-PLIC-ID-329-332: core {core} armed, pending probes of IDs "
                f"{[WDT_FIRST_ID + m for m in others]} moved from {before} to {now} at rise {n}"
            )
            assert raw == raw0, (
                f"CHK-WDT-PLIC-ID-329-332: raw vector moved to 0x{raw:x} from 0x{raw0:x} at rise "
                f"{n} of the core {core} window"
            )
            if seen is None and now[core] == 1:
                seen = n
        assert seen is not None, (
            f"CHK-WDT-PLIC-ID-329-332: tb_plic_pending_{WDT_FIRST_ID + core} stayed 0 for "
            f"{WINDOW} rises after arming core {core} (last probes {now})"
        )
        return seen

    async def body(self) -> None:
        dut = cocotb.top
        for n in range(CORES):
            assert hasattr(dut, f"tb_plic_pending_{WDT_FIRST_ID + n}"), (
                f"tb_plic_pending_{WDT_FIRST_ID + n} is not exported by tb_top"
            )

        # S1
        await self.wait_fuse_sense_done()
        width = len(dut.tb_cpu_interrupts)
        assert width == RAW_VECTOR_WIDTH, f"raw vector is {width} bits, expected {RAW_VECTOR_WIDTH}"
        entry = self._pending()
        assert entry == (0,) * CORES, f"entry pending probes 329..332 read {entry}, expected all 0"
        self._stamp("S1")

        # S2
        await self.csr_write("REGION_SIZE_256M", REGION_SIZE, REGION_SIZE_256M)
        await self.csr_read("REGION_SIZE_256M_RB", REGION_SIZE, expected=REGION_SIZE_256M)
        saved_prio = {}
        for n in range(CORES):
            saved_prio[n] = await self.csr_read(f"PRIORITY{329 + n}_SAVE", _priority_addr(329 + n))
            await self.csr_write(f"PRIORITY{329 + n}_ONE", _priority_addr(329 + n), 1)
        word = WDT_FIRST_ID // 32
        saved_enable = await self.csr_read(f"ENABLE0_{word}_SAVE", _enable_addr(word))
        saved_threshold = await self.csr_read("THRESHOLD0_SAVE", THRESHOLD0)
        await self.csr_write("THRESHOLD0_ZERO", THRESHOLD0, 0)
        idle_claim = await self.csr_read("CLAIM0_IDLE", CLAIM0)
        assert idle_claim == 0, f"CLAIM_COMPLETE read 0x{idle_claim:x} with nothing pending"
        self._stamp("S2")

        # S3
        rows = []
        for core in range(CORES):
            source = WDT_FIRST_ID + core
            before = self._pending()
            assert before[core] == 0, (
                f"CHK-WDT-PLIC-ID-329-332: tb_plic_pending_{source} reads 1 before core {core} "
                f"is armed (probes {before})"
            )
            raw0 = self._bit("tb_cpu_interrupts")
            await self._arm(core)
            rise = await self._rise_window(core, before, raw0)
            ctrl = await self._disarm(core)
            wdogip0 = (ctrl & WDT_CTRL_WDOGIP0_BM) != 0
            assert not wdogip0, (
                f"CHK-WDT-PLIC-ID-329-332: core {core} CTRL.wdogip0 still set after the clear "
                f"(CTRL 0x{ctrl:x})"
            )
            await self.csr_write(
                f"ENABLE0_{word}_SOURCE{source}", _enable_addr(word), 1 << (source % 32)
            )
            claim = await self.csr_read(f"CLAIM0_CORE{core}", CLAIM0)
            assert claim == source, (
                f"CHK-WDT-PLIC-ID-329-332: context 0 claim read {claim} after core {core} armed, "
                f"expected PLIC ID {source}"
            )
            await self.csr_write(f"COMPLETE0_CORE{core}", CLAIM0, source)
            after = self._pending()
            for q in range(1, QUIET_RISES + 1):
                await RisingEdge(dut.clk_smc_i)
                quiet = self._pending()
                assert quiet[core] == 0, (
                    f"CHK-WDT-PLIC-ID-329-332: tb_plic_pending_{source} read 1 at rise {q} after "
                    f"the completion of core {core} with wdogip0 cleared (probes {quiet})"
                )
            await self.csr_write(f"ENABLE0_{word}_NONE{core}", _enable_addr(word), 0)
            assert after[core] == 0, (
                f"CHK-WDT-PLIC-ID-329-332: tb_plic_pending_{source} still 1 after the claim of "
                f"core {core} (probes {after})"
            )
            rows.append(
                f"core {core}: probe {source} rose at rise {rise} of {WINDOW} with the other three "
                f"at {tuple(b for m, b in enumerate(before) if m != core)}, raw vector held "
                f"0x{raw0:x}, claim={claim}, wdogip0 after clear={int(wdogip0)}, "
                f"probe after claim={after[core]} and 0 for {QUIET_RISES} rises after the completion"
            )
        self._stamp("S3")
        self._chk(
            "CHK-WDT-PLIC-ID-329-332",
            f"each core's first-stage watchdog timeout set exactly PLIC source {WDT_FIRST_ID} + "
            f"core, context 0 claimed that ID, and the cleared watchdog did not pend again, "
            f"{len(rows)} cores: " + "; ".join(rows),
        )

        # S4
        for n in range(CORES):
            await self.csr_write(
                f"PRIORITY{329 + n}_RESTORE", _priority_addr(329 + n), saved_prio[n]
            )
            await self.csr_read(
                f"PRIORITY{329 + n}_RESTORE_RB", _priority_addr(329 + n), expected=saved_prio[n]
            )
        await self.csr_write(f"ENABLE0_{word}_RESTORE", _enable_addr(word), saved_enable)
        await self.csr_read(f"ENABLE0_{word}_RESTORE_RB", _enable_addr(word), expected=saved_enable)
        await self.csr_write("THRESHOLD0_RESTORE", THRESHOLD0, saved_threshold)
        await self.csr_read("THRESHOLD0_RESTORE_RB", THRESHOLD0, expected=saved_threshold)
        await self.csr_write("REGION_SIZE_RESTORE", REGION_SIZE, REGION_SIZE_RESET)
        await self.csr_read("REGION_SIZE_RESTORE_RB", REGION_SIZE, expected=REGION_SIZE_RESET)
        self._stamp("S4")
        self.assert_all_reachable(self.accesses, "WDT and PLIC")
        self._chk(
            "CHK-TIMEOUT-PATHS",
            f"fuse sense wait bound 200000 clk_smc_i rises (AssertionError on expiry); "
            f"{CORES} pending-rise windows of {WINDOW} rises each (AssertionError when the probe "
            f"never rises) and {CORES} quiet windows of {QUIET_RISES} rises; SEP_IN accesses x{self.accesses} bound={self.cfg.axi_timeout_ns} ns "
            f"allow_timeout False",
        )
        self._fence()

    def _fence(self) -> None:
        steps = tuple(s for s, _ in self._stamps)
        assert steps == STEPS, f"step order {steps}"
        times = [t for _, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing {times}"
        order = [c for c, _ in self._chk_order]
        assert order == [c for c, _ in CHK_ORDER], f"checker order {order}"
        for chk_id, n_stamps in self._chk_order:
            step = dict(CHK_ORDER)[chk_id]
            assert n_stamps == STEPS.index(step) + 1, f"{chk_id} printed before {step}"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence BRINGUP<PLIC_PROGRAMMED<FOUR_CORES_CLAIMED<RESTORED; "
            "checker lines %s; stamps %s",
            ",".join(order),
            ",".join(f"{s}={t}ps" for s, t in self._stamps),
        )
        self.chk_seen.add("CHK-NONVAC")
