# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Raw interrupt vector assembly across regions, reserved bits and region edges.

Spec sources: interrupts.adoc SMC indexed interrupt map table, CPU interrupt vector map.
"""

from __future__ import annotations

import os

import cocotb
from cocotb.triggers import RisingEdge
from cocotb.utils import get_sim_time

from .smc_addr_map import (
    CLOCK_GATE_CONTROL,
    HANG_DET_FIRE,
    HANG_DET_SYS_AXI_CTRL,
    ZEROER_CTRL_DEST_ADDR,
    ZEROER_CTRL_SIZE,
    ZEROER_CTRL_STATUS,
)
from .smc_mailbox_multi_instance_test_seq import (
    _CTRL_OFFSET,
    _CTRL_WFLUSH,
    _INBOUND_MAILBOX_BASE,
    _IRQ_PATTERN,
    _IRQEN_OFFSET,
    _IRQEN_WTIRQ,
    _IRQS_OFFSET,
    _IRQS_WTIRQ,
    _MAILBOX_CG_EN,
    _MAILBOX_STRIDE,
    _WRITE_DATA_OFFSET,
)
from .smc_output_fabric_vip_utils import output_fabric_pass_all_cfg_seq
from .smc_zeroer_dma_timeout_test_seq import ZEROER_CTRL_STATUS_START

# TB ceilings in clk_smc_i rises for every pin or register wait; not latency claims.
CEILING_RISES = 64
MAILBOX_CEILING_RISES = 128
HOLD_RISES = 256
ZEROER_CEILING_RISES = 4096
FUSE_SENSE_RISES = 200_000
AXI_TIMEOUT_NS = 50_000
MASKED_OUT = ((1 << 32) - 1) << 288
TAIL = 0xF << 324
ZEROER_BIT = 323
ZEROER_BYTES = 256
ZEROER_DEST = 0x0200_3000
MAILBOXES = (0, 31)
# (name, raw bit or None for the masked-out inbound mailboxes)
SOURCES = (
    ("ext0", 0),
    ("ext16", 16),
    ("sep0", 256),
    ("sep7", 263),
    ("ndm", 267),
    ("hang", 286),
    ("mbx0", None),
    ("mbx31", None),
)
_PINS = {
    "ext0": "tb_ext_interrupt_0_i",
    "ext16": "tb_ext_interrupts_hi_i",
    "sep0": "tb_sep_mailbox_interrupts",
    "sep7": "tb_sep_mailbox_interrupts",
    "ndm": "tb_ndmreset_request",
}
_PIN_VALUE = {"ext0": 1, "ext16": 1 << 14, "sep0": 1, "sep7": 1 << 7, "ndm": 1}
_STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7")
_CHECKERS = (
    "CHK-VECASM-ALL-REGIONS",
    "CHK-VECASM-HOLD",
    "CHK-VECASM-DROP-EACH",
    "CHK-VECASM-RSVD-287",
    "CHK-VECASM-EDGES",
    "CHK-VECASM-TAIL-ZERO",
    "CHK-VECASM-INBOUND-LOG",
)
_CHECK_STEP = ("S2", "S3", "S4", "S5", "S5", "S6", "S6")


def _bit(vec: int, n: int) -> int:
    return vec >> n & 1


class smc_irq_vector_assembly_test_seq(output_fabric_pass_all_cfg_seq):
    """Assert sources from every region together and compare the vector with the baseline."""

    def __init__(self, name: str = "smc_irq_vector_assembly_test_seq") -> None:
        super().__init__(name)
        self._stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []
        self._waits: dict[str, tuple[str, str]] = {}
        self._base = 0
        self._pin_state = {
            "tb_ext_interrupt_0_i": 0,
            "tb_ext_interrupts_hi_i": 0,
            "tb_sep_mailbox_interrupts": 0,
            "tb_ndmreset_request": 0,
        }
        self._edges = False
        self.samples = 0
        self.inbound = {288: 0, 319: 0}
        self.zeroer_high = 0

    def _mark_step(self, step_id: str) -> None:
        self._stamps.append((step_id, int(get_sim_time("ps"))))

    def _log_chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self._chk_marks.append((chk_id, int(get_sim_time("ps"))))

    @staticmethod
    def _log_legs(chk: str, set_text: str, observed: str, cleared: str, checked: str) -> None:
        for leg, text in (
            ("set", set_text),
            ("observed", observed),
            ("cleared", cleared),
            ("checked_cleared", checked),
        ):
            cocotb.log.info("LIFECYCLE %s %s: %s", chk, leg, text)

    def _sample(self, label: str) -> int:
        """Return tb_cpu_interrupts after the reserved-bit and edge-neighbour checks."""
        dut = cocotb.top
        for sig in (dut.tb_cpu_interrupts, dut.tb_peripheral_interrupts, dut.tb_mailbox_interrupts):
            assert sig.value.is_resolvable, f"{label}: {sig._name} is X/Z ({sig.value})"
        vec = int(dut.tb_cpu_interrupts.value)
        assert _bit(vec, 287) == 0, f"{label}: raw bit 287 reads 1 (vector 0x{vec:x})"
        assert vec & TAIL == 0, f"{label}: raw bits 327:324 read 0x{vec >> 324 & 0xF:x}"
        if self._edges:
            assert _bit(vec, 255) == 0, f"{label}: raw bit 255 reads 1"
            assert _bit(vec, 320) == _bit(self._base, 320), f"{label}: raw bit 320 moved"
        self.samples += 1
        for n in self.inbound:
            self.inbound[n] += _bit(vec, n)
        return vec

    def _masked(self, vec: int) -> int:
        return (vec ^ self._base) & ~MASKED_OUT

    async def _reach(self, name: str, want: int, mbx: tuple[int, int] | None = None) -> int:
        """Wait until the masked XOR vector equals want (and the mailbox bit its level)."""
        bound = MAILBOX_CEILING_RISES if mbx else CEILING_RISES
        vec = self._sample(f"{name} entry")
        for n in range(1, bound + 1):
            await RisingEdge(cocotb.top.clk_smc_i)
            vec = self._sample(f"{name}[{n}]")
            mb = int(cocotb.top.tb_mailbox_interrupts.value)
            self._waits[name] = (f"{bound} rises", f"xor=0x{self._masked(vec):x} after {n}")
            if self._masked(vec) == want and (mbx is None or _bit(mb, mbx[0]) == mbx[1]):
                return n
        raise AssertionError(
            f"{name}: masked xor 0x{self._masked(vec):x} did not reach "
            f"0x{want:x} within {bound} rises (mailbox bits {mbx})"
        )

    async def _mailbox(self, idx: int, level: int) -> None:
        base = _INBOUND_MAILBOX_BASE + idx * _MAILBOX_STRIDE
        await self.csr_write(
            f"MBOX_IN_{idx}_IRQEN", base + _IRQEN_OFFSET, _IRQEN_WTIRQ * level, length=8
        )
        if level:
            await self.csr_write(
                f"MBOX_IN_{idx}_WRITE_DATA", base + _WRITE_DATA_OFFSET, _IRQ_PATTERN, length=8
            )

    async def _mailbox_clear(self, idx: int) -> None:
        base = _INBOUND_MAILBOX_BASE + idx * _MAILBOX_STRIDE
        await self.csr_write(f"MBOX_IN_{idx}_WFLUSH", base + _CTRL_OFFSET, _CTRL_WFLUSH, length=8)
        await self.csr_write(
            f"MBOX_IN_{idx}_IRQS_CLEAR", base + _IRQS_OFFSET, _IRQS_WTIRQ, length=8
        )

    async def _act(self, src: str, level: int) -> None:
        if src in _PINS:
            pin = _PINS[src]
            state = self._pin_state[pin]
            state = state | _PIN_VALUE[src] if level else state & ~_PIN_VALUE[src]
            self._pin_state[pin] = state
            getattr(cocotb.top, pin).value = state
            cocotb.log.info(
                "DRIVE %s=0x%x (%s level %d) at %d ps",
                pin,
                state,
                src,
                level,
                int(get_sim_time("ps")),
            )
        elif src == "hang":
            await self.csr_write("HANG_SYS_CTRL", HANG_DET_SYS_AXI_CTRL, HANG_DET_FIRE * level)
        else:
            await self._mailbox(MAILBOXES[src == "mbx31"], level)

    async def _toggle(self, src: str, level: int, want: int) -> int:
        await self._act(src, level)
        mbx = (MAILBOXES[src == "mbx31"], level) if src.startswith("mbx") else None
        return await self._reach(f"{src} {level}", want, mbx)

    async def _hold(self, name: str, want: int) -> int:
        peri = int(cocotb.top.tb_peripheral_interrupts.value)
        for n in range(1, HOLD_RISES + 1):
            await RisingEdge(cocotb.top.clk_smc_i)
            vec = self._sample(f"{name}[{n}]")
            assert self._masked(vec) == want, (
                f"{name}: masked xor 0x{self._masked(vec):x} != 0x{want:x} at rise {n}"
            )
            assert int(cocotb.top.tb_peripheral_interrupts.value) == peri, (
                f"{name}: tb_peripheral_interrupts changed at rise {n}"
            )
            self._waits[name] = (f"{HOLD_RISES} rises", f"xor=0x{self._masked(vec):x} at {n}")
        return peri

    async def _watch_zeroer(self) -> tuple[int, int]:
        """Sample every rise until raw 323 has pulsed and fallen; expiry raises."""
        dut = cocotb.top
        high = 0
        for rises in range(1, ZEROER_CEILING_RISES + 1):
            await RisingEdge(dut.clk_smc_i)
            vec = self._sample(f"zeroer[{rises}]")
            assert dut.tb_zeroer_intp.value.is_resolvable, "tb_zeroer_intp is X/Z"
            high += _bit(vec, ZEROER_BIT)
            self._waits["zeroer"] = (
                f"{ZEROER_CEILING_RISES} rises",
                f"raw323={_bit(vec, ZEROER_BIT)} intp={int(dut.tb_zeroer_intp.value)} "
                f"high={high} at {rises}",
            )
            if high and not _bit(vec, ZEROER_BIT):
                return high, rises
        raise AssertionError(
            f"raw bit 323 pulse not completed within {ZEROER_CEILING_RISES} "
            f"rises ({self._waits['zeroer'][1]})"
        )

    async def _zeroer_job(self) -> tuple[int, int]:
        """Program one INT_EN zeroer job while a watcher samples every rise."""
        watcher = cocotb.start_soon(self._watch_zeroer())
        await self.csr_write("ZEROER_DEST_ADDR", ZEROER_CTRL_DEST_ADDR, ZEROER_DEST, length=8)
        await self.csr_write("ZEROER_SIZE", ZEROER_CTRL_SIZE, ZEROER_BYTES, length=8)
        await self.csr_write(
            "ZEROER_CTRL_STATUS_START", ZEROER_CTRL_STATUS, ZEROER_CTRL_STATUS_START, length=8
        )
        return await watcher

    async def body(self) -> None:
        dut = cocotb.top
        await self.wait_fuse_sense_done()
        assert len(dut.tb_cpu_interrupts) >= 328, "tb_cpu_interrupts narrower than 328 bits"
        cocotb.log.info("SEED RANDOM_SEED=%s", os.environ.get("RANDOM_SEED", "1"))
        await RisingEdge(dut.clk_smc_i)
        self._base = self._sample("baseline")
        cocotb.log.info("BASELINE vector=0x%x", self._base)
        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write("CLOCK_GATE_CONTROL_EN", CLOCK_GATE_CONTROL, cg | _MAILBOX_CG_EN)
        await self.program_inbound_pass_all()
        await self.program_outbound_pass_all()
        self._mark_step("S1")

        want, up = 0, []
        for src, bit in SOURCES:
            want |= (1 << bit) if bit is not None else 0
            up.append(f"{src}:{await self._toggle(src, 1, want)}")
        full = want
        self._mark_step("S2")
        self._log_legs(
            "CHK-VECASM-ALL-REGIONS",
            "sources asserted one by one",
            "tb_cpu_interrupts each rise",
            "sources dropped in S4",
            "masked vector equals the baseline after the last drop",
        )
        self._log_chk(
            "CHK-VECASM-ALL-REGIONS",
            f"masked xor equals the cumulative mask after each assertion, final "
            f"0x{full:x} (raw 0,16,256,263,267,286); rises to reach {','.join(up)}",
        )

        peri = await self._hold("hold", full)
        self._mark_step("S3")
        self._log_legs(
            "CHK-VECASM-HOLD",
            "all sources held asserted",
            "tb_cpu_interrupts and tb_peripheral_interrupts each rise",
            "sources dropped in S4",
            "masked vector equals the baseline after S4",
        )
        self._log_chk(
            "CHK-VECASM-HOLD",
            f"masked xor stayed 0x{full:x} and "
            f"tb_peripheral_interrupts stayed 0x{peri:x} for "
            f"{HOLD_RISES} consecutive rises",
        )

        down = []
        for src, bit in reversed(SOURCES):
            want &= ~((1 << bit) if bit is not None else 0)
            down.append(f"{src}:{await self._toggle(src, 0, want)}")
        assert want == 0
        self._mark_step("S4")
        self._log_legs(
            "CHK-VECASM-DROP-EACH",
            "all sources asserted",
            "tb_cpu_interrupts each rise",
            "one source dropped at a time",
            "masked xor 0x0 after the last drop",
        )
        self._log_chk(
            "CHK-VECASM-DROP-EACH",
            "masked xor equaled the remaining mask after each "
            f"drop in reverse order, final 0x0; rises to settle {','.join(down)}",
        )

        self._edges = True
        for idx in MAILBOXES:
            await self._mailbox_clear(idx)
        edge_rises = [f"sep0:{await self._toggle('sep0', 1, 1 << 256)}"]
        await self._toggle("sep0", 0, 0)
        edge_rises.append(f"hang+mbx0:{await self._toggle('hang', 1, 1 << 286)}")
        await self._toggle("mbx0", 1, 1 << 286)
        mbx0_raw = {n: _bit(self._sample("mbx0 288"), n) for n in self.inbound}
        await self._toggle("hang", 0, 0)
        await self._toggle("mbx0", 0, 0)
        await self._mailbox_clear(0)
        edge_rises.append(f"mbx31:{await self._toggle('mbx31', 1, 0)}")
        mbx31_raw = {n: _bit(self._sample("mbx31 319"), n) for n in self.inbound}
        await self._toggle("mbx31", 0, 0)
        await self._mailbox_clear(31)
        self._edges = False
        self._mark_step("S5")
        self._log_chk(
            "CHK-VECASM-RSVD-287",
            f"raw bit 287 = 0 at each of {self.samples} sampled "
            "rises of S2 to S5, including while raw 286 was high and inbound mailbox 0 "
            "was pushed",
        )
        self._log_chk(
            "CHK-VECASM-EDGES",
            "raw 255 = 0 with raw 256 high; raw 287 = 0 with raw 286 "
            "high; raw 320 equal to the baseline with inbound mailbox 31 pushed, "
            f"at every sampled rise; rises to reach {','.join(edge_rises)}",
        )

        high, pulse = await self._zeroer_job()
        self._mark_step("S6")
        self._log_chk(
            "CHK-VECASM-TAIL-ZERO",
            f"raw bits 327:324 = 0 at each of {self.samples} "
            f"sampled rises of S2 to S6; raw bit 323 read 1 at {high} rises and fell "
            f"after {pulse} rises of the zeroer job",
        )
        self._log_chk(
            "CHK-VECASM-INBOUND-LOG",
            f"observe-and-log (owner value pending): expected raw 288 (mailbox 0) and "
            f"raw 319 (mailbox 31); after the mailbox 0 push raw 288={mbx0_raw[288]} raw 319="
            f"{mbx0_raw[319]}; after the mailbox 31 push raw 288={mbx31_raw[288]} "
            f"raw 319={mbx31_raw[319]}; rises high over the run raw 288="
            f"{self.inbound[288]} raw 319={self.inbound[319]} of {self.samples}",
        )

        for idx in MAILBOXES:
            await self._mailbox(idx, 0)
            await self._mailbox_clear(idx)
        await self._act("hang", 0)
        await self.csr_write("CLOCK_GATE_CONTROL_RESTORE", CLOCK_GATE_CONTROL, cg)
        self._mark_step("S7")
        self._nonvac_fence()
        self._log_timeout_paths()

    def _nonvac_fence(self) -> None:
        ids = tuple(s for s, _ in self._stamps)
        assert ids == _STEPS, f"step ids {ids}, want {_STEPS}"
        times = [t for _, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"step stamps not increasing: {times}"
        chk_ids = tuple(c for c, _ in self._chk_marks)
        assert sorted(chk_ids) == sorted(_CHECKERS), f"checker lines {chk_ids}, want {_CHECKERS}"
        stamp_of = dict(self._stamps)
        step_of = dict(zip(_CHECKERS, _CHECK_STEP))
        for chk_id, when in self._chk_marks:
            assert when >= stamp_of[step_of[chk_id]], f"{chk_id} printed before its step stamp"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence SETUP<ASSEMBLE<HOLD<DROP-EACH<EDGES<ZEROER<TEARDOWN; "
            "checker lines %s; stamps %s",
            ",".join(chk_ids),
            ",".join(f"{s}={t}" for s, t in self._stamps),
        )

    @staticmethod
    def _level(name: str) -> str:
        sig = getattr(cocotb.top, name, None)
        return "absent" if sig is None else str(int(sig.value))

    def _log_timeout_paths(self) -> None:
        fuse = f"{FUSE_SENSE_RISES} rises"
        subs = {
            "fuse sense wait tb_fuse_sense_done (AssertionError on expiry)": (
                fuse,
                f"tb_fuse_sense_done={self._level('tb_fuse_sense_done')}",
            ),
            "fuse sense wait tb_fuse_reset_n (AssertionError on expiry)": (
                fuse,
                f"tb_fuse_reset_n={self._level('tb_fuse_reset_n')}",
            ),
            "fuse sense wait tb_rst_warm_smc_clk_n (AssertionError on expiry)": (
                fuse,
                f"tb_rst_warm_smc_clk_n={self._level('tb_rst_warm_smc_clk_n')}",
            ),
            "SEP_IN csr_read/csr_write CLOCK_GATE_CONTROL, output-fabric filters, "
            f"HANG_DET_SYS_AXI_CTRL, inbound mailbox IRQEN/WRITE_DATA/CTRL/IRQS and "
            f"ZEROER_CTRL x{self.accesses} "
            "accesses (AssertionError on expiry)": (
                f"{AXI_TIMEOUT_NS} ns",
                f"{self.accesses} accesses completed",
            ),
        }
        waits = "; ".join(
            f"{name} bound={bound} last[{last}]"
            for name, (bound, last) in {**subs, **self._waits}.items()
        )
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: every bounded wait raises AssertionError on expiry "
            "with the last masked xor, mailbox bit and tb_zeroer_intp; %s",
            waits,
        )
