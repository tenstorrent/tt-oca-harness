# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""sync_irq_o isolation from the raw interrupt vector and from asserted interrupt sources.

Spec sources: port_table.adoc sync_irq_o, reset_unit.rdl SYNC_REG, smu-smc.adoc interrupts.
"""

from __future__ import annotations

import os

import cocotb
from cocotb.triggers import RisingEdge
from cocotb.utils import get_sim_time

from .smc_addr_map import HANG_DET_ENABLE, HANG_DET_IRQ_EN, HANG_DET_IRQ_TEST, HANG_DET_SYS_AXI_CTRL
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_probe_positive_control import SYNC_REG, SYNC_REG_SYNC_BM

# TB ceiling in clk_smc_i rises for every pin or register wait; not a latency claim.
CEILING_RISES = 64
WINDOW_RISES = 64
FUSE_SENSE_RISES = 200_000
AXI_TIMEOUT_NS = 50_000
SOURCE_BITS = (0, 256, 286)
SOURCES_MASK = sum(1 << b for b in SOURCE_BITS)
HANG_FIRE = HANG_DET_ENABLE | HANG_DET_IRQ_EN | HANG_DET_IRQ_TEST
_STEPS = ("S1", "S2", "S3", "S4", "S5")
_CHECKERS = ("CHK-SYNCIRQ-SET-CLR", "CHK-SYNCIRQ-SOURCES-ZERO", "CHK-SYNCIRQ-POSCTRL")
_CHECK_STEP = ("S3", "S4", "S5")


class smc_sync_irq_isolation_test_seq(SmcCsrSeq):
    """Follow tb_sync_irq and the raw vector around SYNC_REG writes and asserted sources."""

    def __init__(self, name: str = "smc_sync_irq_isolation_test_seq") -> None:
        super().__init__(name)
        self.phases = 0
        self._stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []
        self._waits: dict[str, tuple[str, str]] = {}
        self._base = 0

    def _mark_step(self, step_id: str) -> None:
        self._stamps.append((step_id, int(get_sim_time("ps"))))

    def _log_chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self._chk_marks.append((chk_id, int(get_sim_time("ps"))))

    @staticmethod
    def _sample(label: str) -> tuple[int, int]:
        vec = cocotb.top.tb_cpu_interrupts
        irq = cocotb.top.tb_sync_irq
        assert vec.value.is_resolvable, f"{label}: tb_cpu_interrupts is X/Z ({vec.value})"
        assert irq.value.is_resolvable, f"{label}: tb_sync_irq is X/Z ({irq.value})"
        return int(irq.value), int(vec.value)

    def _drive_pins(self, ext0: int, mbx: int, why: str) -> None:
        cocotb.top.tb_ext_interrupt_0_i.value = ext0
        cocotb.top.tb_sep_mailbox_interrupts.value = mbx
        cocotb.log.info(
            "DRIVE tb_ext_interrupt_0_i=%d tb_sep_mailbox_interrupts=0x%02x (%s) at %d ps",
            ext0,
            mbx,
            why,
            int(get_sim_time("ps")),
        )

    async def _reach(
        self, name: str, irq_want: int, vec_want: int | None = None, vec_mask: int | None = None
    ) -> int:
        """Wait until tb_sync_irq == irq_want and the masked vector matches vec_want."""
        irq, vec = self._sample(f"{name} entry")
        self._waits[name] = (f"{CEILING_RISES} rises", f"irq={irq} vec=0x{vec:x}")
        for n in range(1, CEILING_RISES + 1):
            await RisingEdge(cocotb.top.clk_smc_i)
            irq, vec = self._sample(f"{name}[{n}]")
            self._waits[name] = (f"{CEILING_RISES} rises", f"irq={irq} vec=0x{vec:x} after {n}")
            vec_ok = vec_want is None or (vec & vec_mask) == vec_want
            if irq == irq_want and vec_ok:
                return n
        raise AssertionError(
            f"{name}: tb_sync_irq did not reach {irq_want} (vector want "
            f"{'any' if vec_want is None else hex(vec_want)}) within {CEILING_RISES} clk_smc_i "
            f"rises (last irq={irq} vec=0x{vec:x})"
        )

    async def _window(self, name: str, irq_want: int, vec_check) -> list[tuple[int, int]]:
        """Sample WINDOW_RISES consecutive rises; tb_sync_irq must equal irq_want in each."""
        out = []
        for n in range(1, WINDOW_RISES + 1):
            await RisingEdge(cocotb.top.clk_smc_i)
            irq, vec = self._sample(f"{name}[{n}]")
            self._waits[name] = (f"{WINDOW_RISES} rises", f"irq={irq} vec=0x{vec:x} at {n}")
            assert irq == irq_want, f"{name}: tb_sync_irq={irq} at rise {n}, want {irq_want}"
            vec_check(name, n, vec)
            out.append((irq, vec))
        return out

    def _log_legs(self, chk: str, set_text: str, observed: str, cleared: str, checked: str):
        cocotb.log.info("LIFECYCLE %s set: %s", chk, set_text)
        cocotb.log.info("LIFECYCLE %s observed: %s", chk, observed)
        cocotb.log.info("LIFECYCLE %s cleared: %s", chk, cleared)
        cocotb.log.info("LIFECYCLE %s checked_cleared: %s", chk, checked)

    def _equals_base(self, name: str, n: int, vec: int) -> None:
        assert vec == self._base, (
            f"{name}: vector 0x{vec:x} != baseline 0x{self._base:x} at rise {n}"
        )

    async def _write_read_sync(self, label: str, value: int) -> int:
        await self.csr_write(f"SYNC_REG_{label}", SYNC_REG, value)
        got = await self.csr_read(f"SYNC_REG_{label}", SYNC_REG, expected=value)
        assert got == value, f"SYNC_REG readback 0x{got:x} after write 0x{value:x}"
        return got

    async def body(self) -> None:
        dut = cocotb.top
        await self.wait_fuse_sense_done()
        assert hasattr(dut, "tb_ext_interrupt_0_i"), "tb_ext_interrupt_0_i missing"
        assert hasattr(dut, "tb_sep_mailbox_interrupts"), "tb_sep_mailbox_interrupts missing"
        assert len(dut.tb_cpu_interrupts) >= 328, (
            f"tb_cpu_interrupts width {len(dut.tb_cpu_interrupts)}, want >= 328"
        )
        cocotb.log.info("SEED RANDOM_SEED=%s", os.environ.get("RANDOM_SEED", "1"))
        self._drive_pins(0, 0, "idle before baseline")
        await RisingEdge(dut.clk_smc_i)
        irq0, self._base = self._sample("baseline")
        assert irq0 == 0, f"tb_sync_irq={irq0} at baseline, want 0"
        cocotb.log.info("BASELINE vector=0x%x tb_sync_irq=%d", self._base, irq0)
        self._mark_step("S1")
        self.phases += 1

        set_rd = await self._write_read_sync("SET", SYNC_REG_SYNC_BM)
        up = await self._reach("sync set", 1, self._base, ~0)
        set_win = await self._window("sync set window", 1, self._equals_base)
        self._mark_step("S2")
        self.phases += 1

        clr_rd = await self._write_read_sync("CLR", 0)
        down = await self._reach("sync clear", 0, self._base, ~0)
        clr_win = await self._window("sync clear window", 0, self._equals_base)
        self._mark_step("S3")
        self.phases += 1
        self._log_legs(
            "CHK-SYNCIRQ-SET-CLR",
            "SYNC_REG.sync written 1",
            f"tb_sync_irq high after {up} rises, vector at baseline",
            "SYNC_REG.sync written 0",
            f"tb_sync_irq low after {down} rises, vector at baseline",
        )
        self._log_chk(
            "CHK-SYNCIRQ-SET-CLR",
            f"SYNC_REG read 0x{set_rd:x} then tb_sync_irq=1 after {up} rises and "
            f"vector==0x{self._base:x} at {len(set_win)} rises; SYNC_REG read "
            f"0x{clr_rd:x} then tb_sync_irq=0 after {down} rises and vector==baseline "
            f"at {len(clr_win)} rises",
        )

        self._drive_pins(1, 1, "sources with sync low")
        await self.csr_write("HANG_SYS_FIRE", HANG_DET_SYS_AXI_CTRL, HANG_FIRE)
        want = self._base | SOURCES_MASK
        srcs = await self._reach("sources raw bits", 0, want & SOURCES_MASK, SOURCES_MASK)
        src_win = await self._window("sources window", 0, self._sources_high)
        self._mark_step("S4")
        self.phases += 1
        self._log_legs(
            "CHK-SYNCIRQ-SOURCES-ZERO",
            "raw bits 0, 256, 286 asserted with sync low",
            f"raw bits high after {srcs} rises",
            "sources released in S5",
            "tb_sync_irq reads 0 after the release",
        )
        self._log_chk(
            "CHK-SYNCIRQ-SOURCES-ZERO",
            f"raw bits 0,256,286 = 1 and tb_sync_irq = 0 at each of {len(src_win)} "
            f"consecutive rises (vector 0x{src_win[-1][1]:x}, raw bits high after "
            f"{srcs} rises, SYNC_REG.sync 0)",
        )

        sync_rd = await self._write_read_sync("SET_SRC", SYNC_REG_SYNC_BM)
        ctl = await self._reach("sync set with sources", 1)
        _, vec_set = self._sample("sources set vector")
        assert vec_set & SOURCES_MASK == SOURCES_MASK, (
            f"a source bit dropped when sync rose (vector 0x{vec_set:x})"
        )
        self._drive_pins(0, 0, "sources released")
        await self.csr_write("HANG_SYS_OFF", HANG_DET_SYS_AXI_CTRL, 0)
        await self.csr_write("SYNC_REG_CLR_SRC", SYNC_REG, 0)
        fin = await self._reach("final clear", 0, self._base, ~0)
        _, vec_end = self._sample("final vector")
        self._mark_step("S5")
        self.phases += 1
        self._log_legs(
            "CHK-SYNCIRQ-POSCTRL",
            "SYNC_REG.sync written 1 with sources asserted",
            f"tb_sync_irq high after {ctl} rises",
            "SYNC_REG.sync written 0",
            f"tb_sync_irq low after {fin} rises, vector==0x{vec_end:x}",
        )
        self._log_chk(
            "CHK-SYNCIRQ-POSCTRL",
            f"SYNC_REG read 0x{sync_rd:x}, tb_sync_irq=1 after {ctl} rises with "
            f"sources high (vector 0x{vec_set:x}); after the releases and clears "
            f"tb_sync_irq=0 and vector 0x{vec_end:x}==baseline after {fin} rises",
        )

        self._nonvac_fence()
        self._log_timeout_paths()

    @staticmethod
    def _sources_high(name: str, n: int, vec: int) -> None:
        assert vec & SOURCES_MASK == SOURCES_MASK, (
            f"{name}: raw bits 0,256,286 not all high at rise {n} (vector 0x{vec:x})"
        )

    def _nonvac_fence(self) -> None:
        ids = tuple(s for s, _ in self._stamps)
        assert ids == _STEPS, f"step ids {ids}, want {_STEPS}"
        times = [t for _, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"step stamps not increasing: {times}"
        chk_ids = tuple(c for c, _ in self._chk_marks)
        assert chk_ids == _CHECKERS, f"checker lines {chk_ids}, want {_CHECKERS}"
        stamp_of = dict(self._stamps)
        for (chk_id, when), step in zip(self._chk_marks, _CHECK_STEP):
            assert when >= stamp_of[step], f"{chk_id} printed before its step {step} stamp"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence BASELINE<SET<CLEAR<SOURCES-SYNC-LOW<POSITIVE-CONTROL; "
            "checker lines %s; stamps %s",
            ",".join(chk_ids),
            ",".join(f"{s}={t}" for s, t in self._stamps),
        )

    @staticmethod
    def _level(name: str) -> str:
        sig = getattr(cocotb.top, name, None)
        return "absent" if sig is None else str(int(sig.value))

    def _log_timeout_paths(self) -> None:
        dut = cocotb.top
        fuse = (
            f"{FUSE_SENSE_RISES} rises",
            f"tb_fuse_sense_done={int(dut.tb_fuse_sense_done.value)}",
        )
        subs = {
            "fuse sense wait tb_fuse_sense_done (AssertionError on expiry)": fuse,
            "fuse sense wait tb_fuse_reset_n (AssertionError on expiry)": (
                f"{FUSE_SENSE_RISES} rises",
                f"tb_fuse_reset_n={self._level('tb_fuse_reset_n')}",
            ),
            "fuse sense wait tb_rst_warm_smc_clk_n (AssertionError on expiry)": (
                f"{FUSE_SENSE_RISES} rises",
                f"tb_rst_warm_smc_clk_n={self._level('tb_rst_warm_smc_clk_n')}",
            ),
            "SEP_IN csr_write/csr_read SYNC_REG and csr_write HANG_DET_SYS_AXI_CTRL "
            f"x{self.accesses} accesses (AssertionError on expiry)": (
                f"{AXI_TIMEOUT_NS} ns",
                f"{self.accesses} accesses completed",
            ),
        }
        waits = "; ".join(
            f"{name} bound={bound} last[{last}]"
            for name, (bound, last) in {**subs, **self._waits}.items()
        )
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: every bounded wait raises AssertionError on expiry; "
            "pin-wait expiry reports the last tb_sync_irq and vector; %s",
            waits,
        )
