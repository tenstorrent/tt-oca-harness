# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
# Contract SMC_I2C_CSR_IRQ_013, anchor smc_i2c_intr_output_path_test.
# Scenarios I2C-INTR-ENABLE-MASK.S1-S4, I2C-IRQ-PERIPH-OUT.S1/S3/S4, I2C-IRQ-CPU-VEC.S1-S3,
# I2C-INSTANCE-ISOLATION.S2.
# Spec sources: hw/ip/i2c/regs/i2c.rdl INTR_STATE, INTR_ENABLE, INTR_TEST;
# hw/sys/smc/doc/interrupts.adoc; hw/ip/i2c/doc/index.adoc.
"""I2C INTR_ENABLE and INTR_TEST through the instance outputs to peripheral and CPU interrupts.

Frontdoor only, one reset, no bus traffic. `CMD_COMPLETE` is raised through the
`singlepulse` `INTR_TEST` field of instance n (n = 0, 1, 2) and observed on
`tb_i2c_irq[n]` (peripheral interrupts 23 to 25) and on `tb_cpu_interrupts`
(IDs 279 to 281). The combination of `INTR_ENABLE` and `INTR_STATE` into the
output (SF-012), the CPU vector bit numbering (SF-014) and the write-to-output
latency (SF-013) are open: those steps print measured values and compare none
of them.
"""

from __future__ import annotations

import os
from pathlib import Path

import cocotb
from cocotb.triggers import ClockCycles
from cocotb.utils import get_sim_time

from .smc_addr_map import I2C_CG_EN, _field_mask, _parse_simple_defines, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_rdl_regmap import rdl_contract

_NUM_I2C = 3
_PERIPH_BASE = 23
_CPU_BASE = 279

CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")

_I2C_H = Path(__file__).resolve().parents[6] / "hw" / "ip" / "i2c" / "regs" / "gen" / "c" / "i2c.h"


def _reg(name: str, n: int) -> int:
    return smc_indexed_addr(f"SMC_TOP_SMC_I2C_WRAP_I2C_{name}_BASE_ADDR", n)


INTR_STATE = [_reg("INTR_STATE", n) for n in range(_NUM_I2C)]
INTR_ENABLE = [_reg("INTR_ENABLE", n) for n in range(_NUM_I2C)]
INTR_TEST = [_reg("INTR_TEST", n) for n in range(_NUM_I2C)]


def _bm(kind: str, name: str) -> int:
    return _field_mask(_I2C_H, f"I2C__INTR_{kind}__{name}_bm")


def _enable_all_mask() -> int:
    table = _parse_simple_defines(_I2C_H)
    mask = 0
    for key, val in table.items():
        if key.startswith("I2C__INTR_ENABLE__") and key.endswith("_bm"):
            mask |= val
    return mask


ENABLE_ALL = _enable_all_mask()
CMD_COMPLETE = "CMD_COMPLETE"

# (A enabled, B forced): adjacent, far, status-versus-event.
PAIRS = (
    ("CMD_COMPLETE", "TX_STRETCH"),
    ("RX_OVERFLOW", "TARGET_RX_FIFO_ERROR"),
    ("TX_STRETCH", "SMBALERT"),
)

# Bench liveness bounds in clk_smc_i cycles; the IRQ crosses the peripheral CDC.
IRQ_BOUND = 512
CPU_BOUND = 2000
HOLD_SAMPLES = 64
NEIGHBOUR_STEPS = ("S3", "S6", "S8")

STEPS = ["S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10"]
CHK_STEPS = {
    "CHK-I2C-IRQ-RESET-LOW": ("S2", "S3"),
    "CHK-I2C-IRQ-PERIPH-ONEHOT": ("S3",),
    "CHK-I2C-CPU-VEC-RAISE-OBS": ("S3",),
    "CHK-I2C-ENABLE-MASK-OBS": ("S4", "S10"),
    "CHK-I2C-PAIR-MASK": ("S5",),
    "CHK-I2C-IRQ-THREE-INDEPENDENT": ("S6",),
    "CHK-I2C-INSTANCE-INTR-ISOLATION": ("S7",),
    "CHK-I2C-CPU-VEC-FALL-OBS": ("S8",),
    "CHK-I2C-CPU-NEIGHBOURS": ("S9",),
}


def _is_event(n_reg: int, name: str) -> bool:
    """True when INTR_TEST of `name` is write-only (Event: W1C releases it)."""
    test = {f.name: f for f in rdl_contract(f"smc_i2c_wrap/i2c[{n_reg}]/INTR_TEST").fields}
    return test[name].access == "write-only"


class smc_i2c_intr_output_path_test_seq(SmcCsrSeq):
    """INTR_ENABLE and INTR_TEST to tb_i2c_irq, tb_peripheral_interrupts, tb_cpu_interrupts."""

    def __init__(self, name: str = "smc_i2c_intr_output_path_test_seq") -> None:
        super().__init__(name)
        self.fence: list[tuple[str, int]] = []
        self.events: list[tuple[str, str]] = []
        self.lines: dict[str, str] = {}
        self.neigh_samples: list[tuple[str, int, int, int, int]] = []
        self.baseline: tuple[int, int, int, int] | None = None

    # ---- probes -------------------------------------------------------------
    def _irq_vec(self, dut) -> int:
        sig = dut.tb_i2c_irq.value
        assert sig.is_resolvable, "tb_i2c_irq is X/Z"
        return int(sig) & 0x7

    def _cpu_vec(self, dut) -> int:
        sig = dut.tb_cpu_interrupts.value
        assert sig.is_resolvable, "tb_cpu_interrupts is X/Z"
        return int(sig)

    def _periph_vec(self, dut) -> int:
        sig = dut.tb_peripheral_interrupts.value
        assert sig.is_resolvable, "tb_peripheral_interrupts is X/Z"
        return int(sig)

    def _neighbours(self, dut) -> tuple[int, int, int, int]:
        p = self._periph_vec(dut)
        c = self._cpu_vec(dut)
        return ((p >> 22) & 1, (p >> 26) & 1, (c >> 278) & 1, (c >> 282) & 1)

    def _sample_neighbours(self, dut, tag: str) -> tuple[int, int, int, int]:
        got = self._neighbours(dut)
        self.neigh_samples.append((tag, *got))
        return got

    def _cpu_window(self, dut) -> int:
        return (self._cpu_vec(dut) >> _CPU_BASE) & 0x7

    # ---- bookkeeping --------------------------------------------------------
    def _step(self, step: str) -> None:
        self.fence.append((step, int(get_sim_time("ps"))))
        self.events.append(("STEP", step))
        cocotb.log.info("STEP %s done @ %d ps", step, self.fence[-1][1])

    def _chk(self, chk: str, line: str) -> None:
        cocotb.log.info("%s: %s", chk, line)
        self.events.append(("CHK", chk))
        self.lines[chk] = line

    # ---- waits --------------------------------------------------------------
    async def _wait_irq(self, dut, mask: int, want: int, label: str, bound: int = IRQ_BOUND) -> int:
        """Poll tb_i2c_irq & mask == want; return the cycle count at which it held."""
        got = self._irq_vec(dut) & mask
        for cyc in range(bound):
            got = self._irq_vec(dut) & mask
            if label[:2] in NEIGHBOUR_STEPS:
                self._sample_neighbours(dut, label)
            if got == want:
                return cyc
            await ClockCycles(dut.clk_smc_i, 1)
        raise AssertionError(
            f"{label}: tb_i2c_irq&0x{mask:x} still 0x{got:x}, expected 0x{want:x}, after "
            f"{bound} clk_smc_i cycles"
        )

    async def _observe_irq(self, dut, n: int, want: int, bound: int = IRQ_BOUND):
        """Observe-only poll of tb_i2c_irq[n]; return (cycles, level) with cycles None on expiry."""
        got = (self._irq_vec(dut) >> n) & 1
        for cyc in range(bound):
            got = (self._irq_vec(dut) >> n) & 1
            if got == want:
                return cyc, got
            await ClockCycles(dut.clk_smc_i, 1)
        return None, got

    async def _wait_cpu(self, dut, bit: int, want: int, label: str) -> int:
        got = (self._cpu_vec(dut) >> bit) & 1
        for cyc in range(CPU_BOUND):
            got = (self._cpu_vec(dut) >> bit) & 1
            self._sample_neighbours(dut, label)
            if got == want:
                return cyc
            await ClockCycles(dut.clk_smc_i, 1)
        raise AssertionError(
            f"{label}: tb_cpu_interrupts[{bit}] still {got}, expected {want}, after "
            f"{CPU_BOUND} clk_smc_i cycles (hang)"
        )

    # ---- register helpers ---------------------------------------------------
    async def _force(self, n: int, name: str, tag: str) -> None:
        await self.csr_write(f"INTR_TEST_{tag}_{name}_{n}", INTR_TEST[n], _bm("TEST", name))

    async def _w1c(self, n: int, name: str, tag: str) -> None:
        await self.csr_write(f"INTR_STATE_W1C_{tag}_{name}_{n}", INTR_STATE[n], _bm("STATE", name))

    async def _state(self, n: int, tag: str) -> int:
        return await self.csr_read(f"INTR_STATE_{tag}_{n}", INTR_STATE[n])

    async def _enable(self, n: int, tag: str) -> int:
        return await self.csr_read(f"INTR_ENABLE_{tag}_{n}", INTR_ENABLE[n])

    async def _release(self, n: int, name: str, tag: str) -> None:
        if _is_event(n, name):
            await self._w1c(n, name, tag)
        else:
            await self.csr_write(f"INTR_TEST_REL_{tag}_{name}_{n}", INTR_TEST[n], 0)

    # ---- body ---------------------------------------------------------------
    async def body(self) -> None:
        dut = cocotb.top
        cc_state = _bm("STATE", CMD_COMPLETE)
        cc_enable = _bm("ENABLE", CMD_COMPLETE)

        # S1: bring-up, ungate, neighbour baseline.
        cg = await self.csr_read("I2C_CG", CLOCK_GATE_CONTROL)
        await self.csr_write("I2C_UNGATE", CLOCK_GATE_CONTROL, cg & ~I2C_CG_EN)
        self.baseline = self._neighbours(dut)
        self._sample_neighbours(dut, "S1")
        cocotb.log.info(
            "S1 neighbour baseline: periph22=%d periph26=%d cpu278=%d cpu282=%d",
            *self.baseline,
        )
        self._step("S1")

        # S2: reset-low and INTR_ENABLE round trip.
        irq0 = self._irq_vec(dut)
        cpu0 = self._cpu_window(dut)
        assert irq0 == 0, f"tb_i2c_irq reads 0b{irq0:03b} before any INTR write, expected 0b000"
        assert cpu0 == 0, (
            f"tb_cpu_interrupts[281:279] reads 0b{cpu0:03b} before any INTR write, expected 0b000"
        )
        rst_en = [await self._enable(n, "RST") for n in range(_NUM_I2C)]
        assert rst_en == [0] * _NUM_I2C, f"INTR_ENABLE at reset {[hex(v) for v in rst_en]}"
        ones_back: list[int] = []
        ones_irq: list[int] = []
        for n in range(_NUM_I2C):
            await self.csr_write(f"INTR_ENABLE_ONES_{n}", INTR_ENABLE[n], ENABLE_ALL)
            back = await self._enable(n, "ONES")
            assert back == ENABLE_ALL, (
                f"INTR_ENABLE[{n}] wrote 0x{ENABLE_ALL:x}, read back 0x{back:x}"
            )
            ones_back.append(back)
            ones_irq.append(self._irq_vec(dut))
            await self.csr_write(f"INTR_ENABLE_ZERO_{n}", INTR_ENABLE[n], 0)
            back0 = await self._enable(n, "ZERO")
            assert back0 == 0, f"INTR_ENABLE[{n}] wrote 0, read back 0x{back0:x}"
        await self._wait_irq(dut, 0x7, 0, "S2 enables cleared")
        cocotb.log.info(
            "S2 tb_i2c_irq during the all-ones enable of instance 0,1,2: %s",
            [f"0b{v:03b}" for v in ones_irq],
        )
        self._step("S2")

        # S3: one-hot raise of each instance with the other two at baseline.
        raise_lat: list[int] = []
        cpu_sets: list[str] = []
        onehot_parts: list[str] = []
        for n in range(_NUM_I2C):
            others = 0x7 & ~(1 << n)
            await self.csr_write(f"INTR_ENABLE_CC_{n}", INTR_ENABLE[n], cc_enable)
            cpu_before = self._cpu_vec(dut)
            await self._force(n, CMD_COMPLETE, "S3")
            lat = await self._wait_irq(dut, 1 << n, 1 << n, f"S3 raise {n}")
            raise_lat.append(lat)
            assert (self._irq_vec(dut) & others) == 0, (
                f"S3 n={n}: other tb_i2c_irq bits 0b{self._irq_vec(dut) & others:03b} "
                f"while instance {n} is high"
            )
            neigh = self._sample_neighbours(dut, f"S3 raise {n} neighbours")
            assert neigh[:2] == self.baseline[:2], (
                f"S3 n={n}: tb_peripheral_interrupts bits 22/26 {neigh[:2]} differ from "
                f"baseline {self.baseline[:2]}"
            )
            cpu_hits: list[int] = []
            for cyc in range(CPU_BOUND):
                changed = self._cpu_vec(dut) ^ cpu_before
                cpu_hits = [i for i in range(328) if (self._cpu_vec(dut) >> i) & 1]
                if (self._cpu_vec(dut) >> _CPU_BASE) & 0x7 or changed:
                    break
                await ClockCycles(dut.clk_smc_i, 1)
            window = [i for i in cpu_hits if _CPU_BASE <= i < _CPU_BASE + _NUM_I2C]
            cpu_sets.append(f"n={n}: window279-281={window} all_set={cpu_hits}")
            await self._w1c(n, CMD_COMPLETE, "S3")
            await self.csr_write(f"INTR_ENABLE_OFF_{n}", INTR_ENABLE[n], 0)
            fall = await self._wait_irq(dut, 1 << n, 0, f"S3 fall {n}")
            st = await self._state(n, "S3CLR")
            assert (st & cc_state) == 0, f"S3 n={n}: CMD_COMPLETE still set 0x{st:x} after W1C"
            onehot_parts.append(
                f"n={n} raise_lat_cycles={lat} others_irq=0b000 neighbours={neigh} "
                f"fall_lat_cycles={fall} state_after=0x{st:x}"
            )
        self._step("S3")
        reset_low = (
            f"INTR_ENABLE reset={[hex(v) for v in rst_en]} all_ones_readback="
            f"{[hex(v) for v in ones_back]} then 0x0; tb_i2c_irq=0b{irq0:03b} "
            f"cpu[281:279]=0b{cpu0:03b} before any write; each bit rose in S3 "
            f"(latency cycles {raise_lat})"
        )
        self._chk("CHK-I2C-IRQ-RESET-LOW", reset_low)
        self._chk("CHK-I2C-IRQ-PERIPH-ONEHOT", "; ".join(onehot_parts))
        self._chk("CHK-I2C-CPU-VEC-RAISE-OBS", "; ".join(cpu_sets))

        # S4: INTR_ENABLE as a mask over a pending state (observation only, SF-012).
        mask_parts: list[str] = []
        await self._force(0, CMD_COMPLETE, "S4")
        held = []
        for _ in range(HOLD_SAMPLES):
            held.append((self._irq_vec(dut) >> 0) & 1)
            await ClockCycles(dut.clk_smc_i, 1)
        st = await self._state(0, "S4HELD")
        mask_parts.append(
            f"state set enable 0: irq0_over_{HOLD_SAMPLES}_samples={sorted(set(held))} "
            f"INTR_STATE=0x{st:x}"
        )
        await self.csr_write("INTR_ENABLE_S4", INTR_ENABLE[0], cc_enable)
        cyc, lvl = await self._observe_irq(dut, 0, 1)
        mask_parts.append(f"after enable: irq0={lvl} latency_cycles={cyc}")
        await self.csr_write("INTR_ENABLE_S4_OFF", INTR_ENABLE[0], 0)
        await ClockCycles(dut.clk_smc_i, IRQ_BOUND)
        lvl = (self._irq_vec(dut) >> 0) & 1
        st = await self._state(0, "S4OFF")
        mask_parts.append(
            f"after enable cleared and {IRQ_BOUND} cycles: irq0={lvl} INTR_STATE=0x{st:x}"
        )
        await self._w1c(0, CMD_COMPLETE, "S4")
        st = await self._state(0, "S4CLR")
        assert (st & cc_state) == 0, f"S4: CMD_COMPLETE still set 0x{st:x} after W1C"
        await self._wait_irq(dut, 0x7, 0, "S4 quiet")
        self._step("S4")

        # S5: bit pairs.
        pair_parts: list[str] = []
        seed = os.environ.get("RANDOM_SEED", "1")
        for a, b in PAIRS:
            a_en, b_en = _bm("ENABLE", a), _bm("ENABLE", b)
            b_st, b_te = _bm("STATE", b), _bm("TEST", b)
            await self.csr_write(f"INTR_ENABLE_PAIR_A_{a}", INTR_ENABLE[0], a_en)
            await self.csr_write(f"INTR_TEST_PAIR_B_{b}", INTR_TEST[0], b_te)
            st = await self._state(0, f"PAIR_{b}")
            assert (st & b_st) == b_st, f"S5 {a}/{b}: INTR_STATE 0x{st:x} lacks B bit 0x{b_st:x}"
            for i in range(HOLD_SAMPLES):
                lvl = (self._irq_vec(dut) >> 0) & 1
                assert lvl == 0, (
                    f"S5 {a}/{b}: tb_i2c_irq[0] reads 1 at sample {i} with only {a} enabled"
                )
                await ClockCycles(dut.clk_smc_i, 1)
            await self.csr_write(f"INTR_ENABLE_PAIR_AB_{b}", INTR_ENABLE[0], a_en | b_en)
            rise = await self._wait_irq(dut, 1, 1, f"S5 {a}/{b} rise")
            await self._release(0, b, "S5")
            fall = await self._wait_irq(dut, 1, 0, f"S5 {a}/{b} fall")
            st = await self._state(0, f"PAIR_CLR_{b}")
            assert (st & b_st) == 0, f"S5 {a}/{b}: B bit still set 0x{st:x} after release"
            await self.csr_write("INTR_ENABLE_PAIR_OFF", INTR_ENABLE[0], 0)
            pair_parts.append(
                f"A={a}(bit {a_en.bit_length() - 1}) "
                f"B={b}(bit {b_en.bit_length() - 1}) quiet_samples={HOLD_SAMPLES} "
                f"rise_cycles={rise} fall_cycles={fall}"
            )
        self._step("S5")
        self._chk("CHK-I2C-PAIR-MASK", f"seed={seed} fixed pairs; " + "; ".join(pair_parts))

        # S6: three independent instances.
        indep_parts: list[str] = []
        for n in range(_NUM_I2C):
            await self.csr_write(f"INTR_ENABLE_ALL3_{n}", INTR_ENABLE[n], cc_enable)
        for order, expect in (
            ((0, 1, 2), (0b110, 0b100, 0b000)),
            ((2, 1, 0), (0b011, 0b001, 0b000)),
        ):
            for n in range(_NUM_I2C):
                await self._force(n, CMD_COMPLETE, "S6")
            await self._wait_irq(dut, 0x7, 0b111, "S6 all raised")
            cpu_win = self._cpu_window(dut)
            seen = []
            for n, want in zip(order, expect):
                await self._w1c(n, CMD_COMPLETE, "S6")
                lat = await self._wait_irq(dut, 0x7, want, f"S6 clear {n}")
                seen.append(f"clear {n}->0b{want:03b}({lat}cyc)")
            indep_parts.append(
                f"order {order}: 0b111 (cpu[281:279]=0b{cpu_win:03b}) " + " ".join(seen)
            )
        for n in range(_NUM_I2C):
            await self.csr_write(f"INTR_ENABLE_ALL3_OFF_{n}", INTR_ENABLE[n], 0)
        self._step("S6")
        self._chk("CHK-I2C-IRQ-THREE-INDEPENDENT", "; ".join(indep_parts))

        # S7: isolation.
        iso_parts: list[str] = []
        for n in range(_NUM_I2C):
            others = [m for m in range(_NUM_I2C) if m != n]
            snap = {}
            for m in others:
                snap[m] = (await self._state(m, "SNAP"), await self._enable(m, "SNAP"))
            irq_snap = self._irq_vec(dut) & sum(1 << m for m in others)
            await self.csr_write(f"INTR_ENABLE_ISO_{n}", INTR_ENABLE[n], cc_enable)
            await self._force(n, CMD_COMPLETE, "S7")
            await self._wait_irq(dut, 1 << n, 1 << n, f"S7 raise {n}")
            st_n = await self._state(n, "ISO")
            assert (st_n & cc_state) == cc_state, (
                f"S7 n={n}: INTR_STATE 0x{st_n:x} lacks CMD_COMPLETE"
            )
            for m in others:
                got = (await self._state(m, "ISO"), await self._enable(m, "ISO"))
                assert got == snap[m], (
                    f"S7 n={n}: instance {m} INTR_STATE/ENABLE {got} differ from snapshot {snap[m]}"
                )
            irq_now = self._irq_vec(dut) & sum(1 << m for m in others)
            assert irq_now == irq_snap == 0, (
                f"S7 n={n}: other tb_i2c_irq bits 0b{irq_now:03b} vs snapshot 0b{irq_snap:03b}"
            )
            await self._w1c(n, CMD_COMPLETE, "S7")
            await self.csr_write(f"INTR_ENABLE_ISO_OFF_{n}", INTR_ENABLE[n], 0)
            await self._wait_irq(dut, 1 << n, 0, f"S7 fall {n}")
            st_n = await self._state(n, "ISOCLR")
            assert (st_n & cc_state) == 0, f"S7 n={n}: CMD_COMPLETE still set 0x{st_n:x}"
            for m in others:
                got = (await self._state(m, "ISOCLR"), await self._enable(m, "ISOCLR"))
                assert got == snap[m], f"S7 n={n}: instance {m} changed after clear: {got}"
            iso_parts.append(
                f"n={n} others {others} words {[(hex(s), hex(e)) for s, e in snap.values()]} "
                f"unchanged, irq bits 0b{irq_now:03b}"
            )
        self._step("S7")
        self._chk("CHK-I2C-INSTANCE-INTR-ISOLATION", "; ".join(iso_parts))

        # S8: CPU vector bits.
        fall_parts: list[str] = []
        for n in range(_NUM_I2C):
            await self.csr_write(f"INTR_ENABLE_CPU_{n}", INTR_ENABLE[n], cc_enable)
            await self._force(n, CMD_COMPLETE, "S8")
            rise = await self._wait_cpu(dut, _CPU_BASE + n, 1, f"S8 rise {n}")
            await self._w1c(n, CMD_COMPLETE, "S8")
            fall = await self._wait_cpu(dut, _CPU_BASE + n, 0, f"S8 fall {n}")
            await self.csr_write(f"INTR_ENABLE_CPU_OFF_{n}", INTR_ENABLE[n], 0)
            await self._wait_irq(dut, 0x7, 0, f"S8 quiet {n}")
            fall_parts.append(f"n={n} cpu[{_CPU_BASE + n}] rise_cycles={rise} fall_cycles={fall}")
        self._step("S8")
        self._chk("CHK-I2C-CPU-VEC-FALL-OBS", "; ".join(fall_parts))

        # S9: neighbour samples.
        for n in range(_NUM_I2C):
            st = await self._state(n, "S9")
            assert (st & cc_state) == 0, f"S9: instance {n} CMD_COMPLETE still set 0x{st:x}"
        assert self.neigh_samples, "no neighbour sample was taken in S3, S6 or S8"
        bad = [s for s in self.neigh_samples if s[1:] != self.baseline]
        assert not bad, f"neighbour samples differ from baseline {self.baseline}: {bad[:5]}"
        self._step("S9")
        self._chk(
            "CHK-I2C-CPU-NEIGHBOURS",
            f"{len(self.neigh_samples)} samples of periph22 periph26 cpu278 cpu282 all equal "
            f"baseline {self.baseline}",
        )

        # S10: three pending enabled bits cleared one at a time (observation only, SF-012).
        trio = (CMD_COMPLETE, "SDA_UNSTABLE", "RX_OVERFLOW")
        trio_en = 0
        for name in trio:
            trio_en |= _bm("ENABLE", name)
        await self.csr_write("INTR_ENABLE_TRIO", INTR_ENABLE[0], trio_en)
        for name in trio:
            await self._force(0, name, "S10")
        trio_rise, lvl = await self._observe_irq(dut, 0, 1)
        trio_parts = [f"three pending enabled: irq0={lvl} rise_cycles={trio_rise}"]
        for i, name in enumerate(trio):
            await self._w1c(0, name, "S10")
            if i < len(trio) - 1:
                cyc, lvl = await self._observe_irq(dut, 0, 0)
            else:
                cyc = await self._wait_irq(dut, 1, 0, "S10 final fall")
                lvl = 0
            st = await self._state(0, f"S10_{name}")
            trio_parts.append(f"after W1C {name}: irq0={lvl} fall_cycles={cyc} INTR_STATE=0x{st:x}")
        await self.csr_write("INTR_ENABLE_TRIO_OFF", INTR_ENABLE[0], 0)
        await self.csr_write("I2C_CG_RESTORE", CLOCK_GATE_CONTROL, cg)
        self._step("S10")
        self._chk(
            "CHK-I2C-ENABLE-MASK-OBS",
            "S4: " + "; ".join(mask_parts) + " | S10: " + "; ".join(trio_parts),
        )

        # Fence.
        order = [t for t, _ in self.fence]
        assert order == STEPS, f"fence order {order}"
        stamps = [t for _, t in self.fence]
        assert all(b > a for a, b in zip(stamps, stamps[1:])), f"stamps not increasing {stamps}"
        for chk, steps in CHK_STEPS.items():
            assert ("CHK", chk) in self.events, f"{chk} never printed"
            pos = self.events.index(("CHK", chk))
            for s in steps:
                assert self.events.index(("STEP", s)) < pos, f"{chk} printed before {s}"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s ps",
            " ".join(order),
            " ".join(CHK_STEPS),
            stamps,
        )
