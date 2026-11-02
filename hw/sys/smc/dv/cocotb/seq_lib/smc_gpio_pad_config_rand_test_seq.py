# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Seeded per-pad GPIO direction and interrupt configurations against a drawn pad level sequence.

Specs: hw/ip/gpio/regs/gpio_intf.rdl (DATA_CTRL: enable_rx_tx, interface_enable, core2pad,
interrupt_enable, interrupt_type; ACCESS_FILTER), hw/ip/gpio/doc/architecture.adoc (Data and
Direction Ownership, Interrupts), hw/ip/gpio/doc/memmap.adoc (ACCESS_FILTER) and
hw/sys/smc/doc/memmap.adoc (AXI-Lite External Window) for the GPIO_CTRL `CONTROL` read.

The seed draws 8 configurations on 8 distinct GPIO interface instances, each a pad and a pad level
sequence of 4 to 8 levels, the RX code of the six RX-enabled instances, a level type and an edge
type; the interrupt type class and enable of every RX-enabled instance are fixed by its slot. Pinned
on every seed: the four `enable_rx_tx` codes each on at least one instance, the four interrupt types
each with `interrupt_enable` set on an RX-enabled instance, one RX-enabled instance of a level type
and one of an edge type with `interrupt_enable` clear, both RX codes among the interrupt
configurations, and in every level sequence a rising and a falling transition from the idle level of
its type.

Instances are drawn from the pads the bench drive path can move (the bench drives the I2C0, I3C0,
UART0 RX, AVS SDATA and system-timer pads itself), excluding the pads the integrator pad table
reserves, the isolate-request pad and the input pads the SMC acts on (boot stall, cool reset in,
OCCP interface, thermal emergency), and among those the pads with no hardware LSIO selection and
their `core2pad_en_o` bit clear before the pass.

Code 10 takes its levels on the bench drive; code 11 drives its own pad, so its levels are written
to `DATA_CTRL.core2pad` with the bench drive released. Every `clk_smc_i` rise of the interrupt leg
samples `tb_gpio_irq_any`; each level's window is graded from those samples.
"""

from __future__ import annotations

import random

import cocotb
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import (
    _GPIO_INTF_H,
    external_gpio_ctrl_addr,
    external_gpio_ctrl_indices,
    gpio_intf_u32,
    reg_reset_word,
    smc_indexed_addr,
)
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_gpio_vip_utils import drive_gpio_pad
from .smc_pad_table import gpio_pad_count, pad_function, pad_index
from .smc_probe_positive_control import _pad_vec

_IF_ENABLE = gpio_intf_u32("GPIO_INTF__DATA_CTRL__INTERFACE_ENABLE_bm")
_IRQ_ENABLE = gpio_intf_u32("GPIO_INTF__DATA_CTRL__INTERRUPT_ENABLE_bm")
_CORE2PAD = gpio_intf_u32("GPIO_INTF__DATA_CTRL__CORE2PAD_bm")
_RXTX_BP = gpio_intf_u32("GPIO_INTF__DATA_CTRL__ENABLE_RX_TX_bp")
_RXTX_BM = gpio_intf_u32("GPIO_INTF__DATA_CTRL__ENABLE_RX_TX_bm")
_TYPE_BP = gpio_intf_u32("GPIO_INTF__DATA_CTRL__INTERRUPT_TYPE_bp")
_TYPE_BM = gpio_intf_u32("GPIO_INTF__DATA_CTRL__INTERRUPT_TYPE_bm")
DATA_CTRL_RESET = reg_reset_word(_GPIO_INTF_H, "GPIO_INTF", "DATA_CTRL")
ACCESS_FILTER_RESET = reg_reset_word(_GPIO_INTF_H, "GPIO_INTF", "ACCESS_FILTER")
RXTX_RESET = gpio_intf_u32("GPIO_INTF__DATA_CTRL__ENABLE_RX_TX_reset")
TYPE_RESET = gpio_intf_u32("GPIO_INTF__DATA_CTRL__INTERRUPT_TYPE_reset")

# gpio_intf.rdl enable_rx_tx: bit 0 TX, bit 1 RX.
CODES = (0, 1, 2, 3)
TX_CODES = (1, 3)
RX_CODES = (2, 3)
# gpio_intf.rdl interrupt_type: 0 active-high level, 1 active-low level, 2 rising, 3 falling.
TYPES = (0, 1, 2, 3)
LEVEL_TYPES = (0, 1)
EDGE_TYPES = (2, 3)
TYPE_NAME = {0: "high-level", 1: "low-level", 2: "rising", 3: "falling"}
IDLE_LEVEL = {0: 0, 1: 1, 2: 0, 3: 1}

N_CFG = 8
LEVELS_MIN, LEVELS_MAX = 4, 8
REDRAW_BOUND = 64

BENCH_DRIVEN_FUNCTIONS = (
    "UART[0].RX",
    "I3C[0] SCL",
    "I3C[0] SDA",
    "I2C[0] SCL",
    "I2C[0] SDA",
    "AVS.SDATA",
    "System Timer Sync Load",
    "System Timer Credit Count",
)
EXCLUDED_FUNCTIONS = (
    "Reserved",
    "Isolate Request",
    "Boot Stall",
    "Cool Reset In",
    "OCCP Interface",
    "Thermal Emergency N",
)

FUSE_SENSE_BOUND = 200_000
OE_BOUND = 64
SETTLE = 24
HOLD = 8

STEPS = ("S1", "S2", "S3", "S4", "S5", "S6")
CHK_STEPS = (
    ("CHK-PADCFG-RESET", "S3"),
    ("CHK-PADCFG-DIR", "S4"),
    ("CHK-PADCFG-LEVEL", "S5"),
    ("CHK-PADCFG-EDGE", "S5"),
)


def draw_configs(rng: random.Random, candidates: list[int]) -> tuple[list[dict], int]:
    """The drawn configurations and the number of attempts the pinned cells took."""
    for attempt in range(1, REDRAW_BOUND + 1):
        pads = rng.sample(candidates, N_CFG)
        cfgs = []
        for i in range(N_CFG):
            if i < 4:
                code, itype, en = rng.choice(RX_CODES), TYPES[i], 1
            elif i == 4:
                code, itype, en = rng.choice(RX_CODES), rng.choice(LEVEL_TYPES), 0
            elif i == 5:
                code, itype, en = 0, rng.choice(TYPES), rng.randint(0, 1)
            elif i == 6:
                code, itype, en = 1, rng.choice(TYPES), rng.randint(0, 1)
            else:
                code, itype, en = rng.choice(RX_CODES), rng.choice(EDGE_TYPES), 0
            n = rng.randint(LEVELS_MIN, LEVELS_MAX)
            levels = [rng.randint(0, 1) for _ in range(n)]
            cfgs.append({"pad": pads[i], "code": code, "type": itype, "en": en, "levels": levels})
        rng.shuffle(cfgs)
        if pinned_ok(cfgs):
            return cfgs, attempt
    raise AssertionError(f"pinned cells not drawn within {REDRAW_BOUND} attempts")


def transitions(itype: int, levels: list[int]) -> list[tuple[int, int]]:
    prev = IDLE_LEVEL[itype]
    out = []
    for lvl in levels:
        out.append((prev, lvl))
        prev = lvl
    return out


def pinned_ok(cfgs: list[dict]) -> bool:
    if {c["code"] for c in cfgs} != set(CODES):
        return False
    irq = [c for c in cfgs if c["code"] in RX_CODES]
    if {c["code"] for c in irq} != set(RX_CODES):
        return False
    if {c["type"] for c in irq if c["en"]} != set(TYPES):
        return False
    for group in (LEVEL_TYPES, EDGE_TYPES):
        if not any(not c["en"] and c["type"] in group for c in irq):
            return False
    for c in irq:
        tr = transitions(c["type"], c["levels"])
        if (0, 1) not in tr or (1, 0) not in tr:
            return False
    return True


class _IrqSampler:
    """`tb_gpio_irq_any` at every `clk_smc_i` rise while running."""

    def __init__(self) -> None:
        self.samples: list[int] = []
        self.running = True

    async def run(self) -> None:
        dut = cocotb.top
        while self.running:
            await RisingEdge(dut.clk_smc_i)
            await ReadOnly()
            value = dut.tb_gpio_irq_any.value
            assert value.is_resolvable, f"tb_gpio_irq_any is X/Z at sample {len(self.samples)}"
            self.samples.append(int(value) & 1)


class smc_gpio_pad_config_rand_test_seq(SmcCsrSeq):
    """Drawn per-pad configurations: output enable per code, interrupt per type and enable."""

    def __init__(self, name: str = "smc_gpio_pad_config_rand_test_seq", *, seed: int) -> None:
        super().__init__(name)
        self.seed = seed
        self.rng = random.Random(self.seed)
        self.cfgs: list[dict] = []
        self.reset_log: list[str] = []
        self.candidates: list[int] = []
        self.attempts = 0
        self.sampler: _IrqSampler | None = None
        self.steps: list[tuple[str, int]] = []
        self.chk_lines: list[tuple[str, str]] = []
        self.waits: list[str] = []
        self.dir_log: list[str] = []
        self.level_log: list[str] = []
        self.edge_log: list[str] = []
        self.windows = 0
        self.window_samples = 0
        self.pads_moved: set[int] = set()
        self.done = False

    # -- plumbing ---------------------------------------------------------

    def _mark(self, step: str) -> None:
        self.steps.append((step, int(get_sim_time("ps"))))

    def _chk(self, step: str, chk_id: str, text: str) -> None:
        assert self.steps and self.steps[-1][0] == step, f"{chk_id} printed before {step} ended"
        self.chk_lines.append((chk_id, step))
        cocotb.log.info("%s: %s", chk_id, text)

    @staticmethod
    def _cfg_str(c: dict) -> str:
        return (
            f"pad {c['pad']} enable_rx_tx {c['code']:02b} type {c['type']} "
            f"({TYPE_NAME[c['type']]}) interrupt_enable {c['en']} levels "
            f"{''.join(str(v) for v in c['levels'])}"
        )

    def _drawn(self) -> str:
        return "drawn=" + "; ".join(self._cfg_str(c) for c in self.cfgs)

    @staticmethod
    def _data_ctrl(pad: int) -> int:
        return smc_indexed_addr("SMC_TOP_GPIO_INTF_WRAP_GPIO_INTF_DATA_CTRL_BASE_ADDR", pad)

    @staticmethod
    def _access_filter(pad: int) -> int:
        return smc_indexed_addr("SMC_TOP_GPIO_INTF_WRAP_GPIO_INTF_ACCESS_FILTER_BASE_ADDR", pad)

    @staticmethod
    def _word(code: int, itype: int = 0, irq: int = 0, core2pad: int = 0) -> int:
        word = _IF_ENABLE | (code << _RXTX_BP) | (itype << _TYPE_BP)
        if irq:
            word |= _IRQ_ENABLE
        if core2pad:
            word |= _CORE2PAD
        return word

    async def _read_raw(self, name: str, addr: int) -> tuple[int | None, int]:
        item = SmcSysAxiItem(f"rd_{name}")
        item.op, item.addr, item.length = SmcSysAxiOp.READ, addr, 4
        item.allow_error = True
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        return item.resp_code, int(item.rdata)

    # -- steps ------------------------------------------------------------

    def _static_candidates(self) -> list[int]:
        driven = {pad_index(f) for f in BENCH_DRIVEN_FUNCTIONS}
        out = []
        for pad in range(gpio_pad_count()):
            if pad in driven or pad_function(pad) in EXCLUDED_FUNCTIONS:
                continue
            out.append(pad)
        return out

    async def _s1(self) -> None:
        dut = cocotb.top
        await self.wait_fuse_sense_done(FUSE_SENSE_BOUND)
        self.waits.append(f"fuse_sense_done<={FUSE_SENSE_BOUND} clk_smc_i")
        for name in (
            "tb_gpio_irq_any",
            "tb_core2pad_en_o",
            "tb_lsio_interface_select",
            "tb_gpio_ext_drive_en",
            "tb_gpio_ext_drive_value",
        ):
            assert hasattr(dut, name), f"tb_top has no {name}"
        dut.tb_gpio_ext_drive_en.value = 0
        dut.tb_gpio_ext_drive_value.value = 0
        await ClockCycles(dut.clk_smc_i, SETTLE)
        lsio = _pad_vec(dut, "tb_lsio_interface_select")
        oe = _pad_vec(dut, "tb_core2pad_en_o")
        static = self._static_candidates()
        self.candidates = [p for p in static if not (lsio >> p) & 1 and not (oe >> p) & 1]
        assert len(self.candidates) >= N_CFG, (
            f"{len(self.candidates)} free pads ({self.candidates}), want {N_CFG}"
        )
        assert int(dut.tb_gpio_irq_any.value) == 0, "tb_gpio_irq_any high before the pass"
        self.cfgs, self.attempts = draw_configs(self.rng, self.candidates)
        assert pinned_ok(self.cfgs)
        assert len({c["pad"] for c in self.cfgs}) == N_CFG
        cocotb.log.info(
            "RAND-SEED: %d; RAND-DRAW: %d configurations on distinct pads from %d free pads "
            "(static %d, minus hardware LSIO selection 0x%x and core2pad_en_o 0x%x), "
            "pinned cells after %d attempt(s) of %d: %s",
            self.seed,
            N_CFG,
            len(self.candidates),
            len(static),
            lsio,
            oe,
            self.attempts,
            REDRAW_BOUND,
            "; ".join(self._cfg_str(c) for c in self.cfgs),
        )
        self._mark("S1")

    async def _s2(self) -> None:
        for c in self.cfgs:
            pad = c["pad"]
            dc = await self.csr_read(f"GPIO{pad}_DATA_CTRL_RESET", self._data_ctrl(pad))
            af = await self.csr_read(f"GPIO{pad}_ACCESS_FILTER_RESET", self._access_filter(pad))
            self.reset_log.append(
                f"pad {pad} enable_rx_tx {(dc & _RXTX_BM) >> _RXTX_BP} (control "
                f"{RXTX_RESET}) interrupt_type {(dc & _TYPE_BM) >> _TYPE_BP} (control "
                f"{TYPE_RESET}) ACCESS_FILTER 0x{af:08x} (control 0x{ACCESS_FILTER_RESET:08x})"
            )
        self._mark("S2")

    async def _s3(self) -> None:
        monitor = getattr(self.env, "axi_monitor", None)
        assert monitor is not None, "no axi_monitor on this sequence's env"
        ctrl_log = []
        for c in self.cfgs:
            pad = c["pad"]
            assert pad in external_gpio_ctrl_indices(), f"no GPIO_CTRL entry for pad {pad}"
            addr = external_gpio_ctrl_addr(pad)
            monitor.expected_decerr_addrs.add(addr)
            resp, data = await self._read_raw(f"GPIO_CTRL{pad}_CONTROL", addr)
            ctrl_log.append(f"GPIO_CTRL {pad} CONTROL@0x{addr:08x} resp {resp} data 0x{data:08x}")
        self._mark("S3")
        self._chk(
            "S3",
            "CHK-PADCFG-RESET",
            "logged control, not graded: " + "; ".join(self.reset_log) + "; printed, not "
            "compared: " + "; ".join(ctrl_log) + f"; {self._drawn()}",
        )

    async def _await_oe(self, pad: int, want: int, base: int, label: str, full: bool) -> int:
        """Polls core2pad_en_o[pad] for `want` (held `OE_BOUND` rises when `full`)."""
        dut = cocotb.top
        reached = -1
        for cycle in range(OE_BOUND):
            await RisingEdge(dut.clk_smc_i)
            await ReadOnly()
            en = _pad_vec(dut, "tb_core2pad_en_o")
            moved = (en ^ base) & ~(1 << pad)
            assert moved == 0, (
                f"{label}: core2pad_en_o bits other than {pad} moved (delta 0x{moved:x})"
            )
            bit = (en >> pad) & 1
            if full:
                assert bit == want, f"{label}: core2pad_en_o[{pad}] read {bit} at rise {cycle}"
            elif bit == want:
                reached = cycle
                break
        if not full:
            assert reached >= 0, (
                f"{label}: core2pad_en_o[{pad}] not {want} within {OE_BOUND} clk_smc_i rises"
            )
        await RisingEdge(dut.clk_smc_i)
        return reached

    async def _s4(self) -> None:
        dut = cocotb.top
        dut.tb_gpio_ext_drive_en.value = 0
        for c in self.cfgs:
            pad, code = c["pad"], c["code"]
            base = _pad_vec(dut, "tb_core2pad_en_o")
            assert not (base >> pad) & 1, f"core2pad_en_o[{pad}] set before its write"
            tx = 1 if code in TX_CODES else 0
            await self.csr_write(
                f"GPIO{pad}_DIR_{code:02b}", self._data_ctrl(pad), self._word(code)
            )
            rise = await self._await_oe(pad, tx, base, f"pad {pad} code {code:02b}", not tx)
            await self.csr_write(f"GPIO{pad}_DIR_CLEAR", self._data_ctrl(pad), self._word(0))
            fall = await self._await_oe(pad, 0, base, f"pad {pad} field cleared", not tx)
            await self.csr_write(f"GPIO{pad}_DIR_RESET", self._data_ctrl(pad), DATA_CTRL_RESET)
            if tx:
                self.dir_log.append(f"pad {pad} {code:02b}: rose at {rise}, released at {fall}")
                self.pads_moved.add(pad)
            else:
                self.dir_log.append(f"pad {pad} {code:02b}: 0 for {OE_BOUND} rises, twice")
        self.waits.append(f"oe_follow<={OE_BOUND} clk_smc_i per write")
        assert {c["code"] for c in self.cfgs} == set(CODES)
        self._mark("S4")
        self._chk(
            "S4",
            "CHK-PADCFG-DIR",
            f"core2pad_en_o bit of the drawn pad rose for TX codes 01/11 and stayed 0 for 00/10, "
            f"released when enable_rx_tx was cleared, no other bit of tb_core2pad_en_o moved at "
            f"any sampled rise: {'; '.join(self.dir_log)}; {self._drawn()}",
        )

    async def _level(self, c: dict, level: int) -> tuple[int, int]:
        """Applies `level` on the pad and returns the sample window of its settle."""
        dut = cocotb.top
        start = len(self.sampler.samples)
        pad = c["pad"]
        if c["code"] == 3:
            word = self._word(3, c["type"], c["en"], level)
            await self.csr_write(f"GPIO{pad}_CORE2PAD_{level}", self._data_ctrl(pad), word)
        else:
            drive_gpio_pad(dut, pad, level)
        await ClockCycles(dut.clk_smc_i, SETTLE)
        await ReadOnly()
        end = len(self.sampler.samples)
        await RisingEdge(dut.clk_smc_i)
        self.windows += 1
        self.window_samples += end - start
        self.pads_moved.add(pad)
        return start, end

    async def _irq_cfg(self, c: dict) -> None:
        dut = cocotb.top
        pad, code, itype, en = c["pad"], c["code"], c["type"], c["en"]
        idle = IDLE_LEVEL[itype]
        addr = self._data_ctrl(pad)
        if code == 2:
            drive_gpio_pad(dut, pad, idle)
        else:
            drive_gpio_pad(dut, pad, None)
        await self.csr_write(f"GPIO{pad}_IRQ_CFG", addr, self._word(code, itype, 0, idle))
        await ClockCycles(dut.clk_smc_i, SETTLE)
        await self.csr_write(f"GPIO{pad}_IRQ_EN{en}", addr, self._word(code, itype, en, idle))
        s0, e0 = await self._level(c, idle)
        idle_s = self.sampler.samples[s0:e0]
        assert not any(idle_s), (
            f"pad {pad}: tb_gpio_irq_any high at the idle level {idle}: {idle_s}; "
            f"{self._cfg_str(c)}"
        )
        cells = []
        c["graded"] = []
        for prev, lvl in transitions(itype, c["levels"]):
            s, e = await self._level(c, lvl)
            win = self.sampler.samples[s:e]
            if itype in LEVEL_TYPES:
                active = lvl == (1 if itype == 0 else 0)
                want = 1 if (active and en) else 0
                tail = win[-HOLD:]
                assert len(win) >= HOLD and all(v == want for v in tail), (
                    f"pad {pad}: level {lvl} after {prev}, tb_gpio_irq_any tail {tail}, want "
                    f"{want}; window {win}; {self._cfg_str(c)}"
                )
                if not en:
                    assert not any(win), f"pad {pad}: interrupt with enable clear: {win}"
                cells.append(f"{prev}->{lvl}:{tail[-1]}")
            else:
                named = (prev, lvl) == ((0, 1) if itype == 2 else (1, 0))
                want = 1 if (named and en) else 0
                got = sum(win)
                assert got == want, (
                    f"pad {pad}: edge {prev}->{lvl}, {got} high samples of tb_gpio_irq_any, "
                    f"want {want}; window {win}; {self._cfg_str(c)}"
                )
                cells.append(f"{prev}->{lvl}:{got}")
            c["graded"].append((prev, lvl))
        log = self.level_log if itype in LEVEL_TYPES else self.edge_log
        log.append(f"pad {pad} code {code:02b} type {itype} enable {en}: {' '.join(cells)}")
        await self.csr_write(f"GPIO{pad}_IRQ_RESET", addr, DATA_CTRL_RESET)
        drive_gpio_pad(dut, pad, None)
        await ClockCycles(dut.clk_smc_i, SETTLE)
        assert int(dut.tb_gpio_irq_any.value) == 0, f"pad {pad}: interrupt after its reset"

    async def _s5(self) -> None:
        self.sampler = _IrqSampler()
        cocotb.start_soon(self.sampler.run())
        await RisingEdge(cocotb.top.clk_smc_i)
        for c in self.cfgs:
            if c["code"] in RX_CODES:
                await self._irq_cfg(c)
        self.sampler.running = False
        await RisingEdge(cocotb.top.clk_smc_i)
        self.waits.append(f"level_settle={SETTLE} clk_smc_i per level (tail {HOLD} graded)")
        irq = [c for c in self.cfgs if c["code"] in RX_CODES]
        assert {c["type"] for c in irq if c["en"]} == set(TYPES)
        for group in (LEVEL_TYPES, EDGE_TYPES):
            assert any(not c["en"] and c["type"] in group for c in irq), (
                f"no RX instance of type {group} with interrupt_enable clear; {self._drawn()}"
            )
        for c in irq:
            assert (0, 1) in c["graded"] and (1, 0) in c["graded"], (
                f"pad {c['pad']}: graded transitions {c['graded']} lack a 0->1 or a 1->0 from the "
                f"idle level; {self._cfg_str(c)}"
            )
        self._mark("S5")
        self._chk(
            "S5",
            "CHK-PADCFG-LEVEL",
            f"per level 'prev->level:expected', the last {HOLD} of {SETTLE} samples equal: "
            f"type 0 high while the pad is high, type 1 high while low, 0 at the idle level and "
            f"throughout with interrupt_enable clear: {'; '.join(self.level_log)}; "
            f"{self._drawn()}",
        )
        self._chk(
            "S5",
            "CHK-PADCFG-EDGE",
            f"per transition 'prev->level:high samples' over {SETTLE} rises: exactly one "
            f"one-clock pulse on the named edge with interrupt_enable set, none on the "
            f"opposite edge, an unchanged level, or with the enable clear: "
            f"{'; '.join(self.edge_log)}; {self._drawn()}",
        )

    async def _s6(self) -> None:
        dut = cocotb.top
        dut.tb_gpio_ext_drive_en.value = 0
        for c in self.cfgs:
            pad = c["pad"]
            await self.csr_write(f"GPIO{pad}_RESTORE", self._data_ctrl(pad), DATA_CTRL_RESET)
            got = await self.csr_read(f"GPIO{pad}_RESTORE_RB", self._data_ctrl(pad))
            assert (got & (_IF_ENABLE | _IRQ_ENABLE | _RXTX_BM | _TYPE_BM)) == (
                DATA_CTRL_RESET & (_IF_ENABLE | _IRQ_ENABLE | _RXTX_BM | _TYPE_BM)
            ), f"pad {pad}: DATA_CTRL 0x{got:08x} after the restore"
        self._mark("S6")
        bound = self.cfg.axi_timeout_ns
        self.waits.append(f"axi_access<={bound} ns per access ({self.accesses} accesses)")
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits: %s; expiry raises AssertionError",
            len(self.waits),
            "; ".join(self.waits),
        )
        self._nonvac()

    def _nonvac(self) -> None:
        assert [st for st, _ in self.steps] == list(STEPS), f"step order {self.steps}"
        stamps = [ps for _, ps in self.steps]
        assert all(b > a for a, b in zip(stamps, stamps[1:])), f"stamps not increasing {stamps}"
        assert self.chk_lines == list(CHK_STEPS), f"checker lines {self.chk_lines}"
        assert self.pads_moved, "no drawn pad moved"
        irq = [c for c in self.cfgs if c["code"] in RX_CODES]
        want_windows = sum(len(c["levels"]) + 1 for c in irq)
        assert self.windows == want_windows, f"{self.windows} windows, want {want_windows}"
        assert self.window_samples >= self.windows * (SETTLE - 1), (
            f"{self.window_samples} samples over {self.windows} windows of {SETTLE} rises"
        )
        sb = self.env.scoreboard
        assert sb.sys_axi_checks_seen >= self.accesses, (
            f"scoreboard checked {sb.sys_axi_checks_seen} SEP_IN items for {self.accesses}"
        )
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; stamps %s; checker lines %s; %d pads moved; "
            "%d level windows, %d samples of tb_gpio_irq_any (every rise); %d accesses; %s",
            " < ".join(STEPS),
            ",".join(str(ps) for ps in stamps),
            ",".join(cid for cid, _ in self.chk_lines),
            len(self.pads_moved),
            self.windows,
            self.window_samples,
            self.accesses,
            self._drawn(),
        )

    async def body(self) -> None:
        await self._s1()
        await self._s2()
        await self._s3()
        await self._s4()
        await self._s5()
        await self._s6()
        self.done = True
