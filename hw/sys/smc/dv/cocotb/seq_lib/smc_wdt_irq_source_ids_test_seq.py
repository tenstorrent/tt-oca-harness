# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC raw interrupt vector width, SEP watchdog indication on bit 282, core-2 WDT PLIC pending.

Sources: hw/sys/smc/doc/interrupts.adoc (Raw Vector and PLIC Numbering),
hw/sys/smc/doc/clk_rst.adoc (Reset).
Registers: hw/sys/smc/regs/blocks/wdt/wdt.rdl; the SEP watchdog pin is driven on tb_sep_wdt_reset_n.

The SEP watchdog reset pin is driven low and high while bit 282 of the raw vector,
tb_sep_wdt_irq_sync and tb_plic_pending_331 are sampled; after the warm reset releases the core-2
watchdog is armed over SEP_IN so wdogip0 sets and tb_plic_pending_331 is sampled beside every bit
of tb_cpu_interrupts. Latency, level-or-latch and the PLIC pending latch of the ID 283 source are
measured and printed, not asserted.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge
from cocotb.utils import get_sim_time

from .smc_addr_map import smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

WDT_MAGIC_KEY = 0x51F15E
WDT_CORE = 2
WDT_CMP_ARM = 0x0040
WDT_CMP_CLEAR = 0x0100
WDT_CTRL_SCALE8 = 0x0008
WDT_COUNT_ARM = 0x0000_4400
WDT_CTRL_WDOGIP0_BM = 0x1000_0000
WDT_CTRL_WDOGIP0_BP = 28

RAW_VECTOR_WIDTH = 328
SEP_WDT_BIT = 282
WINDOW = 64
WARM_RELEASE_BOUND = 200_000

STEPS = ("S1", "S2", "S3", "S4", "S5")


class smc_wdt_irq_source_ids_test_seq(SmcCsrSeq):
    """Core-2 WDT pending and SEP WDT reset indication observed on distinct probes."""

    def __init__(self, name: str = "smc_wdt_irq_source_ids_test_seq") -> None:
        super().__init__(name)
        self.fence_done = False
        self._stamps: list[tuple[str, int]] = []
        self._chk_after: list[tuple[str, str, int]] = []
        self._waits: list[str] = []

    def _reg(self, reg: str) -> int:
        return smc_addr(f"SMC_TOP_SMC_CLUSTER_CORE{WDT_CORE}_WDT_{reg}_BASE_ADDR")

    def _stamp(self, step: str) -> None:
        self._stamps.append((step, int(get_sim_time("ps"))))

    def _chk(self, chk_id: str, step: str, text: str, *args) -> None:
        self._chk_after.append((chk_id, step, len(self._stamps)))
        cocotb.log.info(f"{chk_id}: {text}", *args)

    @staticmethod
    def _bit(sig, label: str) -> int:
        assert sig.value.is_resolvable, f"{label} = {sig.value} is X/Z"
        return int(sig.value)

    def _sample(self) -> tuple[int, int, int, int]:
        """(raw vector, raw bit 282, sep_wdt_irq_sync, plic pending 331) at this instant."""
        dut = cocotb.top
        raw = self._bit(dut.tb_cpu_interrupts, "tb_cpu_interrupts")
        sync = self._bit(dut.tb_sep_wdt_irq_sync, "tb_sep_wdt_irq_sync")
        plic = self._bit(dut.tb_plic_pending_331, "tb_plic_pending_331")
        return raw, (raw >> SEP_WDT_BIT) & 1, sync, plic

    async def _keyed(self, label: str, reg: str, value: int) -> None:
        await self.csr_write(f"{label}_KEY", self._reg("KEY"), WDT_MAGIC_KEY)
        await self.csr_write(label, self._reg(reg), value)

    async def _window(self) -> list[tuple[int, int, int, int]]:
        clk = cocotb.top.clk_smc_i
        out = []
        for _ in range(WINDOW):
            await RisingEdge(clk)
            out.append(self._sample())
        return out

    @staticmethod
    def _first(samples, idx: int, want: int) -> int | None:
        for i, s in enumerate(samples):
            if s[idx] == want:
                return i + 1
        return None

    async def body(self) -> None:
        dut = cocotb.top
        for name in (
            "tb_sep_wdt_reset_n",
            "tb_cpu_interrupts",
            "tb_sep_wdt_irq_sync",
            "tb_plic_pending_331",
        ):
            assert hasattr(dut, name), f"{name} is not exported by tb_top"

        # S1
        await self.wait_fuse_sense_done()
        pin = self._bit(dut.tb_sep_wdt_reset_n, "tb_sep_wdt_reset_n")
        assert pin == 1, "SEP WDT reset not high"
        raw0, bit0, sync0, plic0 = self._sample()
        assert (bit0, sync0, plic0) == (0, 0, 0), (
            f"entry state bit282={bit0} irq_sync={sync0} plic331={plic0}, expected all 0"
        )
        width = len(dut.tb_cpu_interrupts)
        assert width == RAW_VECTOR_WIDTH, f"raw vector is {width} bits, expected {RAW_VECTOR_WIDTH}"
        self._stamp("S1")

        # S2
        s2 = await self._window()
        s2_bad = [i + 1 for i, s in enumerate(s2) if s[1] != 0 or s[2] != 0]
        assert not s2_bad, f"bit282 or irq_sync read 1 with the pin high at rises {s2_bad}"
        s2_plic = [i + 1 for i, s in enumerate(s2) if s[3] != 0]
        assert not s2_plic, f"tb_plic_pending_331 read 1 with the pin high at rises {s2_plic}"
        self._stamp("S2")

        # S3
        dut.tb_sep_wdt_reset_n.value = 0
        s3 = await self._window()
        self._waits.append(f"sep_wdt_assert_window={WINDOW} last=bit282:{s3[-1][1]}")
        rise_bit = self._first(s3, 1, 1)
        rise_sync = self._first(s3, 2, 1)
        assert rise_bit is not None and rise_sync is not None, (
            f"after the fall of tb_sep_wdt_reset_n bit282 first-1 rise={rise_bit}, "
            f"irq_sync first-1 rise={rise_sync} within {WINDOW}"
        )
        s3_plic = [i + 1 for i, s in enumerate(s3) if s[3] != 0]
        s3_plic_count = len(s3_plic)
        cocotb.log.info(
            "tb_plic_pending_331 read 1 at %d of %d rises during the SEP indication (measured "
            "only, the warm reset holds the cluster PLIC)",
            s3_plic_count,
            WINDOW,
        )
        self._stamp("S3")

        # S4
        dut.tb_sep_wdt_reset_n.value = 1
        s4 = await self._window()
        diff = [i + 1 for i, s in enumerate(s2 + s3 + s4) if s[1] != s[2]]
        assert not diff, f"bit282 differs from irq_sync at samples {diff}"
        ret_bit = self._first(s4, 1, 0)
        ret_sync = self._first(s4, 2, 0)
        for i in range(WARM_RELEASE_BOUND):
            if self._bit(dut.tb_rst_warm_smc_clk_n, "tb_rst_warm_smc_clk_n") == 1:
                break
            await RisingEdge(dut.clk_smc_i)
        else:
            raise AssertionError(f"warm reset not released within {WARM_RELEASE_BOUND} rises")
        self._waits.append(f"warm_release={WARM_RELEASE_BOUND} last=rst_warm_n:1")
        await RisingEdge(dut.clk_smc_i)
        self._stamp("S4")
        self._chk(
            "CHK-SEP-WDT-IRQ-LEVEL",
            "S4",
            "pin high: bit282 and irq_sync read 0 at %d of %d rises; after the fall both read 1 "
            "(bit282 first at rise %d, irq_sync first at rise %d of %d) and were equal at every "
            "one of %d samples; after the release bit282 returned to 0 at rise %s and irq_sync at "
            "rise %s (latency and level or latch are not specified, ID 283 pending latch "
            "not exported)",
            WINDOW,
            WINDOW,
            rise_bit,
            rise_sync,
            WINDOW,
            3 * WINDOW,
            ret_bit,
            ret_sync,
        )

        # S5
        await self._keyed("WDT2_CMP_ARM", "CMP", WDT_CMP_ARM)
        await self._keyed("WDT2_CTRL_ARM", "CTRL", WDT_CTRL_SCALE8)
        await RisingEdge(dut.clk_smc_i)
        base = self._sample()
        assert base[3] == 0, f"tb_plic_pending_331 reads {base[3]} just before the COUNT write"
        await self._keyed("WDT2_COUNT_ARM", "COUNT", WDT_COUNT_ARM)
        arm = await self._window()
        self._waits.append(f"plic331_set_window={WINDOW} last=plic331:{arm[-1][3]}")
        plic_rise = self._first(arm, 3, 1)
        assert plic_rise is not None, (
            f"tb_plic_pending_331 never read 1 in {WINDOW} rises after the arming (no positive "
            f"control); last sample plic={arm[-1][3]}"
        )
        for i, s in enumerate(arm):
            assert s[0] == raw0, (
                f"raw vector changed at rise {i + 1} of the core-2 WDT window: "
                f"0x{s[0]:x} != 0x{raw0:x}"
            )
        await self._keyed("WDT2_CMP_CLEAR", "CMP", WDT_CMP_CLEAR)
        await self._keyed("WDT2_CTRL_CLEAR", "CTRL", WDT_CTRL_SCALE8)
        await self._keyed("WDT2_COUNT_DISARM", "COUNT", 0)
        await self._keyed("WDT2_CTRL_DISARM", "CTRL", 0)
        ctrl = await self.csr_read("WDT2_CTRL_AFTER_CLEAR", self._reg("CTRL"))
        wdogip0 = (ctrl & WDT_CTRL_WDOGIP0_BM) >> WDT_CTRL_WDOGIP0_BP
        clr = await self._window()
        plic_after_clear = clr[-1][3]
        plic_clr_rise = self._first(clr, 3, 0)
        self._stamp("S5")
        self._chk(
            "CHK-SEP-WDT-IRQ-DISTINCT",
            "S5",
            "tb_cpu_interrupts is %d bits wide; during the SEP indication bit282 read 1 from "
            "rise %d and tb_plic_pending_331 read 1 at %d of %d rises (measured only, the warm "
            "reset holds the cluster PLIC); tb_plic_pending_331 read %d "
            "immediately before the core %d arming; with wdogip0 set "
            "tb_plic_pending_331 read 1 at rise %d while the raw vector stayed 0x%x over %d "
            "rises; after the clear core-2 CTRL.wdogip0 read %d and plic331 read %d at rise %d "
            "(first 0 at rise %s, level or latch is not specified)",
            width,
            rise_bit,
            s3_plic_count,
            WINDOW,
            base[3],
            WDT_CORE,
            plic_rise,
            raw0,
            WINDOW,
            wdogip0,
            plic_after_clear,
            WINDOW,
            plic_clr_rise,
        )
        self._fence()

    def _fence(self) -> None:
        ids = [s for s, _ in self._stamps]
        assert ids == list(STEPS), f"step ids {ids}, expected {list(STEPS)}"
        times = [t for _, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing: {times}"
        chk_ids = [c for c, _, _ in self._chk_after]
        assert chk_ids == ["CHK-SEP-WDT-IRQ-LEVEL", "CHK-SEP-WDT-IRQ-DISTINCT"], (
            f"checker lines {chk_ids} out of order"
        )
        order = [STEPS.index(step) for _, step, _ in self._chk_after]
        assert order == sorted(order), f"checker steps {order} out of order"
        for chk_id, step, n in self._chk_after:
            assert n >= STEPS.index(step) + 1, f"{chk_id} printed before {step} was stamped"
        self.fence_done = True
        cocotb.log.info(
            "CHK-NONVAC: ordered fence S1<S2<S3<S4<S5 strictly increasing, each line after its "
            "own compare; checker lines %s; stamps %s ps; bounded waits %s",
            ", ".join(chk_ids),
            ", ".join(f"{s}={t}" for s, t in self._stamps),
            "; ".join(self._waits),
        )
