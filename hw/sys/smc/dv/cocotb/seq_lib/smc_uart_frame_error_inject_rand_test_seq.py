# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Seeded UART0 receive frames with an injected fault, graded on the `LSR` flag of the fault.

Specs: hw/ip/uart/uart_16550/regs/uart_16550_dl.rdl (DLL, DLM: baud = clock / (16 x (divisor +
1))), hw/ip/uart/uart_16550/regs/uart_16550_main.rdl (LCR.WLS, PEN, EPS, DLAB; LSR.DR, PE, FE,
BI, each `rclr`) and hw/ip/uart/uart_16550/doc/architecture.adoc (FIFO Protection and Line
Errors, the UART serial errors table).

Every pass programs its own drawn divisor (1 to 8, `DLM` 0, never the divisor of the pass before)
and format (`WLS`, `PEN`, `EPS`), reads the divisor latches and `LCR` back, resets the FIFOs,
requires `LSR` to read DR, PE, FE and BI clear, drives one frame bit by bit on
`tb_uart0_rx_ext_drive` at the bit time of the divisor and the peripheral clock (`MCR.LOOP`
clear), and ORs the error flags of every `LSR` read from the first `LSR.DR` until the receive
FIFO is drained. Pinned on every seed: a clean frame with `PEN` 0, a clean frame with `PEN` 1, a
parity flip under odd and under even parity, a low stop bit and a break. Two more passes draw their
kind (a parity flip only under `PEN` 1). Every break, the pinned one included, starts on a bit drawn
from the bits of its frame. A low-stop frame carries a 1 in its data bits, so the frame is not all
low, and the line idles high one frame time longer after it, so a character the receiver starts on
the low half of that stop bit ends inside the pass.
"""

from __future__ import annotations

import random
from functools import reduce
from operator import or_

import cocotb
from cocotb.triggers import Timer
from cocotb.utils import get_sim_time

from .smc_addr_map import (
    UART_CG_EN,
    smc_addr,
    smc_indexed_addr,
    uart_16550_dl_u32,
    uart_16550_main_u32,
)
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_log_engine_utils import (
    DLL_OFFSET,
    DLM_OFFSET,
    FCR_FIFO_ENABLE,
    FCR_OFFSET,
    FCR_RCVR_FIFO_RESET,
    FCR_XMIT_FIFO_RESET,
    LCR_DLAB,
    LSR_DR,
    MCR_RTS,
    UART_EN,
    uart_base,
    uart_reg,
)

UART = 0
CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")
UART_CTRL = smc_indexed_addr(
    "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_CTRL_BASE_ADDR", UART
)
LCR_WLS_BP = uart_16550_main_u32("UART_16550_MAIN__LCR__WLS_bp")
LCR_WLS = uart_16550_main_u32("UART_16550_MAIN__LCR__WLS_bm")
LCR_PEN = uart_16550_main_u32("UART_16550_MAIN__LCR__PEN_bm")
LCR_EPS = uart_16550_main_u32("UART_16550_MAIN__LCR__EPS_bm")
LSR_PE = uart_16550_main_u32("UART_16550_MAIN__LSR__PE_bm")
LSR_FE = uart_16550_main_u32("UART_16550_MAIN__LSR__FE_bm")
LSR_BI = uart_16550_main_u32("UART_16550_MAIN__LSR__BI_bm")
LSR_FLAGS = LSR_PE | LSR_FE | LSR_BI
DLL_MASK = uart_16550_dl_u32("UART_16550_DL__DLL__DLL_bm")
DLM_MASK = uart_16550_dl_u32("UART_16550_DL__DLM__DLM_bm")
LCR_FIELDS = reduce(
    or_,
    (
        uart_16550_main_u32(f"UART_16550_MAIN__LCR__{name}_bm")
        for name in ("WLS", "STB", "PEN", "EPS", "STICK_PARITY", "SET_BREAK", "DLAB")
    ),
)

# uart_16550_dl.rdl: 16 baud ticks per bit, the clock divided by divisor + 1; the UART runs on
# the peripheral clock.
TICKS_PER_BIT = 16
DIVISOR_MIN, DIVISOR_MAX = 1, 8
EXTRA_PASSES = 2
KIND_FLAG = {"parity": LSR_PE, "stop": LSR_FE, "break": LSR_BI}
# Step of each pass kind; the step stamp closes when its last frame is graded.
KIND_STEP = {"clean": "S2", "parity": "S3", "stop": "S4", "break": "S5"}
KIND_CHK = {
    "clean": "CHK-UFE-CLEAN",
    "parity": "CHK-UFE-PE",
    "stop": "CHK-UFE-FE",
    "break": "CHK-UFE-BI",
}
STEPS = ("S1", "S2", "S3", "S4", "S5", "S6")
CHK_STEPS = (
    ("CHK-UFE-RESET", "S1"),
    ("CHK-UFE-CLEAN", "S2"),
    ("CHK-UFE-PE", "S3"),
    ("CHK-UFE-FE", "S4"),
    ("CHK-UFE-BI", "S5"),
    ("CHK-UFE-DIVISOR", "S6"),
)
FUSE_SENSE_BOUND = 200_000
# The first LSR.DR within three frame times of the end of the drive.
DR_BOUND_FRAMES = 3
DRAIN_BOUND_CHARS = 8
IDLE_BITS_AFTER_FRAME = 4
# The low half of a low stop bit can start a character (midpoint sampling, architecture.adoc);
# the extra frame time of idle line ends it inside the pass.
IDLE_FRAMES_AFTER_STOP_FAULT = 1
BREAK_FRAMES = 2
IDLE_FRAMES_AFTER_BREAK = 2


def data_bits(wls: int) -> int:
    return 5 + wls


def frame_bits(wls: int, pen: int) -> int:
    """Start, data, parity when enabled, one stop bit."""
    return 1 + data_bits(wls) + pen + 1


def parity_bit(data: int, eps: int) -> int:
    """uart_16550_main.rdl EPS: 1 even parity, 0 odd parity."""
    ones = bin(data).count("1") & 1
    return ones if eps else ones ^ 1


def draw_passes(rng: random.Random) -> list[dict]:
    """Pinned passes, then the drawn extras; divisors and formats drawn per pass."""
    plan: list[dict] = [
        {"kind": "clean", "pen": 0, "pinned": "clean PEN 0"},
        {"kind": "clean", "pen": 1, "pinned": "clean PEN 1"},
        {"kind": "parity", "pen": 1, "eps": 0, "pinned": "parity flip odd"},
        {"kind": "parity", "pen": 1, "eps": 1, "pinned": "parity flip even"},
        {"kind": "stop", "pinned": "low stop bit"},
        {"kind": "break", "pinned": "break from a drawn bit"},
    ]
    for _ in range(EXTRA_PASSES):
        pen = rng.randint(0, 1)
        kinds = ["clean", "stop", "break"] + (["parity"] if pen else [])
        plan.append({"kind": rng.choice(kinds), "pen": pen, "pinned": ""})
    passes: list[dict] = []
    for p in plan:
        cell = dict(p)
        cell.setdefault("pen", rng.randint(0, 1))
        cell.setdefault("eps", rng.randint(0, 1))
        cell["wls"] = rng.randint(0, 3)
        mask = (1 << data_bits(cell["wls"])) - 1
        if cell["kind"] == "stop":
            cell["data"] = rng.choice([b for b in range(256) if b & mask])
        else:
            cell["data"] = rng.randint(0, 255)
        cell["data"] &= mask
        if cell["kind"] == "break":
            cell["bit"] = rng.randrange(frame_bits(cell["wls"], cell["pen"]))
        passes.append(cell)
    order = {k: i for i, k in enumerate(KIND_STEP)}
    rng.shuffle(passes)
    passes.sort(key=lambda c: order[c["kind"]])
    prev = 0
    for cell in passes:
        cell["div"] = rng.choice([d for d in range(DIVISOR_MIN, DIVISOR_MAX + 1) if d != prev])
        prev = cell["div"]
    check_passes(passes)
    return passes


def check_passes(passes: list[dict]) -> None:
    pinned = {c["pinned"] for c in passes if c["pinned"]}
    want = {
        "clean PEN 0",
        "clean PEN 1",
        "parity flip odd",
        "parity flip even",
        "low stop bit",
        "break from a drawn bit",
    }
    assert pinned == want, f"pinned cells {sorted(pinned)}, want {sorted(want)}"
    prev = 0
    for c in passes:
        assert DIVISOR_MIN <= c["div"] <= DIVISOR_MAX and c["div"] != prev, f"divisor {c}"
        prev = c["div"]
        assert c["kind"] != "parity" or c["pen"] == 1, f"parity flip with PEN 0: {c}"
        if c["kind"] == "stop":
            assert c["data"], f"low-stop frame with all data bits 0 is a break: {c}"
        if c["kind"] == "break":
            assert 0 <= c["bit"] < frame_bits(c["wls"], c["pen"]), f"break start bit: {c}"
    assert [c["kind"] for c in passes] == sorted(
        (c["kind"] for c in passes), key=list(KIND_STEP).index
    ), "passes not grouped by step"


def cell_text(c: dict) -> str:
    text = (
        f"{c['kind']} div {c['div']} WLS {c['wls']} PEN {c['pen']} EPS {c['eps']} "
        f"data 0x{c['data']:02x}"
    )
    if c["kind"] == "break":
        text += f" from bit {c['bit']}"
    return text + (f" (pinned: {c['pinned']})" if c["pinned"] else " (drawn)")


class smc_uart_frame_error_inject_rand_test_seq(SmcCsrSeq):
    """Drawn divisor, format and fault per pass; the fault's LSR flag set, a clean frame none."""

    def __init__(self, name: str = "smc_uart_frame_error_inject_rand_test_seq", *, seed: int):
        super().__init__(name)
        self.seed = seed
        self.rng = random.Random(self.seed)
        self.passes: list[dict] = []
        self.steps: list[tuple[str, int]] = []
        self.chk_lines: list[tuple[str, str]] = []
        self.waits: list[str] = []
        self.driven = 0
        self.periph_ps = 0
        self.cg_reset = 0
        self.done = False
        self.base = uart_base(UART)
        self.reg = {name: uart_reg(UART, name) for name in ("RBR", "IER", "LCR", "MCR", "LSR")}

    # -- plumbing ---------------------------------------------------------

    def _mark(self, step: str) -> None:
        self.steps.append((step, int(get_sim_time("ps"))))

    def _chk(self, step: str, chk_id: str, text: str) -> None:
        assert self.steps and self.steps[-1][0] == step, f"{chk_id} printed before {step} ended"
        self.chk_lines.append((chk_id, step))
        cocotb.log.info("%s: %s", chk_id, text)

    def _bit_ps(self, div: int) -> int:
        return TICKS_PER_BIT * (div + 1) * self.periph_ps

    async def _rd(self, name: str, addr: int) -> int:
        return int(await self.csr_read(name, addr))

    async def _read_dl(self, tag: str, lcr: int) -> tuple[int, int, int]:
        await self.csr_write(f"{tag}_LCR_DLAB", self.reg["LCR"], lcr | LCR_DLAB)
        dll = await self._rd(f"{tag}_DLL", self.base + DLL_OFFSET) & DLL_MASK
        dlm = await self._rd(f"{tag}_DLM", self.base + DLM_OFFSET) & DLM_MASK
        await self.csr_write(f"{tag}_LCR", self.reg["LCR"], lcr)
        got_lcr = await self._rd(f"{tag}_LCR_RB", self.reg["LCR"])
        return dll, dlm, got_lcr

    # -- frame drive and collection --------------------------------------

    async def _drive(self, c: dict) -> None:
        rx = cocotb.top.tb_uart0_rx_ext_drive
        bit = self._bit_ps(c["div"])
        nbits = data_bits(c["wls"])
        levels = [0] + [(c["data"] >> n) & 1 for n in range(nbits)]
        if c["pen"]:
            levels.append(parity_bit(c["data"], c["eps"]) ^ int(c["kind"] == "parity"))
        levels.append(0 if c["kind"] == "stop" else 1)
        assert len(levels) == frame_bits(c["wls"], c["pen"])
        if c["kind"] == "break":
            levels = levels[: c["bit"]]
        for level in levels:
            rx.value = level
            await Timer(bit, "ps")
        if c["kind"] == "break":
            rx.value = 0
            await Timer(BREAK_FRAMES * frame_bits(c["wls"], c["pen"]) * bit, "ps")
            rx.value = 1
            await Timer(IDLE_FRAMES_AFTER_BREAK * frame_bits(c["wls"], c["pen"]) * bit, "ps")
        else:
            rx.value = 1
            idle_bits = IDLE_BITS_AFTER_FRAME
            if c["kind"] == "stop":
                idle_bits += IDLE_FRAMES_AFTER_STOP_FAULT * frame_bits(c["wls"], c["pen"])
            await Timer(idle_bits * bit, "ps")
        self.driven += 1

    async def _collect(self, tag: str, c: dict) -> tuple[int, int, list[int]]:
        """OR of PE, FE and BI over every LSR read from the first DR until the FIFO drains."""
        bit = self._bit_ps(c["div"])
        bound_ps = DR_BOUND_FRAMES * frame_bits(c["wls"], c["pen"]) * bit
        start = int(get_sim_time("ps"))
        seen = 0
        reads: list[int] = []
        while True:
            lsr = await self._rd(f"{tag}_LSR_DR", self.reg["LSR"])
            reads.append(lsr)
            seen |= lsr & LSR_FLAGS
            if lsr & LSR_DR:
                break
            waited = int(get_sim_time("ps")) - start
            assert waited <= bound_ps, (
                f"{tag}: LSR.DR not set {waited} ps after the frame, bound {bound_ps} ps "
                f"({DR_BOUND_FRAMES} frame times); reads {[hex(r) for r in reads]}; "
                f"drawn={cell_text(c)}"
            )
            await Timer(bit, "ps")
        self.waits.append(f"{tag}_DR={int(get_sim_time('ps')) - start}/{bound_ps} ps")
        chars = 0
        while lsr & LSR_DR:
            assert chars < DRAIN_BOUND_CHARS, (
                f"{tag}: LSR.DR still set after {chars} RBR pops; drawn={cell_text(c)}"
            )
            await self._rd(f"{tag}_RBR_POP{chars}", self.reg["RBR"])
            chars += 1
            lsr = await self._rd(f"{tag}_LSR_POP{chars}", self.reg["LSR"])
            reads.append(lsr)
            seen |= lsr & LSR_FLAGS
        return seen, chars, reads

    async def _pass(self, i: int, c: dict) -> str:
        tag = f"P{i}_{c['kind'].upper()}"
        lcr = ((c["wls"] << LCR_WLS_BP) & LCR_WLS) | (LCR_PEN if c["pen"] else 0)
        lcr |= LCR_EPS if c["eps"] else 0
        await self.csr_write(f"{tag}_MCR", self.reg["MCR"], MCR_RTS)
        await self.csr_write(f"{tag}_LCR_DLAB", self.reg["LCR"], lcr | LCR_DLAB)
        await self.csr_write(f"{tag}_DLL", self.base + DLL_OFFSET, c["div"])
        await self.csr_write(f"{tag}_DLM", self.base + DLM_OFFSET, 0)
        dll, dlm, got_lcr = await self._read_dl(tag, lcr)
        assert (dll, dlm) == (c["div"], 0), (
            f"{tag}: with LCR.DLAB set DLL 0x{dll:02x} DLM 0x{dlm:02x}, wrote 0x{c['div']:02x} "
            f"and 0x00 (uart_16550_dl.rdl, rw); drawn={cell_text(c)}"
        )
        assert got_lcr & LCR_FIELDS == lcr, (
            f"{tag}: LCR reads 0x{got_lcr:02x}, wrote 0x{lcr:02x} (uart_16550_main.rdl, rw); "
            f"drawn={cell_text(c)}"
        )
        c["readback"] = (dll, dlm, got_lcr & LCR_FIELDS)
        await self.csr_write(f"{tag}_IER", self.reg["IER"], 0)
        await self.csr_write(
            f"{tag}_FCR",
            self.base + FCR_OFFSET,
            FCR_FIFO_ENABLE | FCR_RCVR_FIFO_RESET | FCR_XMIT_FIFO_RESET,
        )
        pre = await self._rd(f"{tag}_LSR_PRE", self.reg["LSR"])
        assert pre & (LSR_DR | LSR_FLAGS) == 0, (
            f"{tag}: LSR 0x{pre:02x} before the frame, want DR, PE, FE and BI clear, so the "
            f"flags after it come from this frame; drawn={cell_text(c)}"
        )
        await self._drive(c)
        seen, chars, reads = await self._collect(tag, c)
        flag = KIND_FLAG.get(c["kind"])
        names = f"PE {int(bool(seen & LSR_PE))} FE {int(bool(seen & LSR_FE))} BI " + str(
            int(bool(seen & LSR_BI))
        )
        if flag is None:
            assert seen == 0, (
                f"{tag}: a clean frame left {names} in the LSR reads {[hex(r) for r in reads]}"
                f" (architecture.adoc, the UART serial errors table); drawn={cell_text(c)}"
            )
        else:
            assert seen & flag, (
                f"{tag}: the {c['kind']} fault did not set its LSR flag (0x{flag:02x}); "
                f"{names} over the reads {[hex(r) for r in reads]}; drawn={cell_text(c)}"
            )
        return (
            f"{tag} [{cell_text(c)}] LSR before 0x{pre:02x}, {names} over {len(reads)} LSR "
            f"reads, {chars} character(s) popped, bit time {self._bit_ps(c['div'])} ps"
        )

    # -- steps ------------------------------------------------------------

    async def _s1(self) -> None:
        dut = cocotb.top
        await self.wait_fuse_sense_done(FUSE_SENSE_BOUND)
        self.waits.append(f"fuse_sense_done<={FUSE_SENSE_BOUND} clk_smc_i")
        assert hasattr(dut, "tb_uart0_rx_ext_drive"), "tb_top has no tb_uart0_rx_ext_drive"
        assert int(dut.tb_uart0_rx_ext_drive.value) == 1, "UART0 RX pad drive not idle high"
        self.periph_ps = int(round(self.cfg.periph_clk_period_ns * 1000))
        assert self.periph_ps > 0, "periph_clk_period_ns must be positive"
        self.passes = draw_passes(self.rng)
        cocotb.log.info(
            "RAND-SEED: %d; RAND-DRAW: %d passes (%d pinned, %d drawn; divisor %d..%d never the "
            "divisor of the pass before): %s; peripheral clock %d ps",
            self.seed,
            len(self.passes),
            sum(1 for c in self.passes if c["pinned"]),
            sum(1 for c in self.passes if not c["pinned"]),
            DIVISOR_MIN,
            DIVISOR_MAX,
            "; ".join(cell_text(c) for c in self.passes),
            self.periph_ps,
        )
        self.cg_reset = await self._rd("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write("UART_UNGATE", CLOCK_GATE_CONTROL, self.cg_reset & ~UART_CG_EN)
        await self.csr_write("UART0_EN", UART_CTRL, UART_EN)
        dll, dlm, lcr = await self._read_dl("RESET", 0)
        lsr = await self._rd("RESET_LSR", self.reg["LSR"])
        self._mark("S1")
        self._chk(
            "S1",
            "CHK-UFE-RESET",
            f"logged control, not graded: UART0 before the first divisor write DLL 0x{dll:02x} "
            f"DLM 0x{dlm:02x} (control word 0; LCR read 0x{lcr:02x} after the DLAB clear), and "
            f"before the first frame "
            f"LSR 0x{lsr:02x}: PE {int(bool(lsr & LSR_PE))} FE {int(bool(lsr & LSR_FE))} BI "
            f"{int(bool(lsr & LSR_BI))} (control word 0); graded by smc_uart_reg_reset_rw_test",
        )

    async def _kind_step(self, kind: str) -> None:
        step, chk = KIND_STEP[kind], KIND_CHK[kind]
        rows = []
        for i, c in enumerate(self.passes):
            if c["kind"] == kind:
                rows.append(await self._pass(i, c))
        assert rows, f"no {kind} pass in the plan"
        self._mark(step)
        what = {
            "clean": "PE, FE and BI read 0 over every LSR read of every clean frame",
            "parity": "every parity-flip frame set LSR.PE (FE and BI printed, not asserted)",
            "stop": "every low-stop-bit frame set LSR.FE (PE and BI printed, not asserted)",
            "break": "every break, from its drawn bit, set LSR.BI (PE and FE printed, not graded)",
        }[kind]
        self._chk(step, chk, f"{what}; {len(rows)} frame(s): drawn=" + " | ".join(rows))

    async def _s6(self) -> None:
        await self.csr_write("RESTORE_LCR_DLAB", self.reg["LCR"], LCR_DLAB)
        await self.csr_write("RESTORE_DLL", self.base + DLL_OFFSET, 0)
        await self.csr_write("RESTORE_DLM", self.base + DLM_OFFSET, 0)
        dll, dlm, lcr = await self._read_dl("RESTORE", 0)
        assert (dll, dlm, lcr & LCR_FIELDS) == (0, 0, 0), (
            f"restore: DLL 0x{dll:02x} DLM 0x{dlm:02x} LCR 0x{lcr:02x}, wrote 0 to each"
        )
        await self.csr_write("RESTORE_FCR", self.base + FCR_OFFSET, 0)
        await self.csr_write("RESTORE_MCR", self.reg["MCR"], 0)
        await self.csr_write("RESTORE_UART0_EN", UART_CTRL, 0)
        await self.csr_write("RESTORE_CG", CLOCK_GATE_CONTROL, self.cg_reset)
        self._mark("S6")
        rows = [
            f"P{i} div {c['div']} -> DLL 0x{c['readback'][0]:02x} DLM 0x{c['readback'][1]:02x}"
            f" LCR 0x{c['readback'][2]:02x}"
            for i, c in enumerate(self.passes)
        ]
        self._chk(
            "S6",
            "CHK-UFE-DIVISOR",
            f"with LCR.DLAB set DLL read back the drawn divisor and DLM 0, and LCR read back the "
            f"drawn format, on all {len(self.passes)} passes (each divisor differs from the one "
            f"before it, the first from the reset value 0) and on the restore to 0 after the "
            f"last pass (previous divisor {self.passes[-1]['div']}): drawn=" + "; ".join(rows),
        )
        bound = self.cfg.axi_timeout_ns
        self.waits.append(f"axi_access<={bound} ns per access ({self.accesses} accesses)")
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits: %s; LSR.DR bound %d frame times after each "
            "frame, drain bound %d characters per frame; expiry raises AssertionError",
            len(self.waits),
            "; ".join(self.waits),
            DR_BOUND_FRAMES,
            DRAIN_BOUND_CHARS,
        )
        self._nonvac()

    def _nonvac(self) -> None:
        assert [st for st, _ in self.steps] == list(STEPS), f"step order {self.steps}"
        stamps = [ps for _, ps in self.steps]
        assert all(b > a for a, b in zip(stamps, stamps[1:])), f"stamps not increasing {stamps}"
        assert self.chk_lines == list(CHK_STEPS), f"checker lines {self.chk_lines}"
        assert self.driven == len(self.passes), (
            f"{self.driven} frames driven on the RX pad, {len(self.passes)} drawn"
        )
        kinds = {c["kind"] for c in self.passes}
        assert kinds == set(KIND_STEP), f"fault kinds driven {sorted(kinds)}"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; stamps %s; checker lines %s; %d of %d frames driven "
            "on tb_uart0_rx_ext_drive, every kind (%s) at least once; seed %d",
            " < ".join(STEPS),
            ",".join(str(ps) for ps in stamps),
            ",".join(chk for chk, _ in self.chk_lines),
            self.driven,
            len(self.passes),
            ", ".join(sorted(kinds)),
            self.seed,
        )

    async def body(self) -> None:
        await self._s1()
        for kind in KIND_STEP:
            await self._kind_step(kind)
        await self._s6()
        self.done = True
