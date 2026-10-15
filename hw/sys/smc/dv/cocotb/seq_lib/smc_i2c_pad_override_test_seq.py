# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
# Spec sources: hw/ip/i2c/regs/i2c.rdl OVRD and VAL; hw/ip/i2c/doc/index.adoc per-instance ports.
"""I2C OVRD pull control as sampled levels on the I2C0 pads and the per-instance pull probes.

``i2c.rdl`` gives ``OVRD.TXOVRDEN`` control of the SDA and SCL lines, with
``SCLVAL`` / ``SDAVAL`` of 0 pulling the line low and 1 releasing it. The
frontdoor writes OVRD words on instance 0 and the bench samples ``tb_i2c0_scl``,
``tb_i2c0_sda`` and the pull probes ``tb_i2cN_scl_dut_low`` / ``_sda_dut_low`` as
levels. The pad pull-up model, the VAL cadence and reset and the per-instance pad
history: the specification does not state the values, so the pad, settle and VAL
legs print measured values and compare nothing on the pad levels. The pull probes are
compared with the OVRD value in the pull and release legs and read 0 with TXOVRDEN=0.
Instance isolation compares the per-instance pull probes only.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from cocotb.utils import get_sim_time

from .smc_addr_map import I2C_CG_EN, smc_addr, smc_indexed_addr
from .smc_cg_obs_utils import assert_fence_progress
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_i2c_field_masks import I2C_WRAP_CTRL_TARGET
from .smc_i2c_master_target_test_seq import _i2c_u32


def _ovrd(idx: int) -> int:
    return smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_OVRD_BASE_ADDR", idx)


CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")
I2C0_WRAP_CTRL = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR", 0)
I2C0_VAL = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_VAL_BASE_ADDR", 0)

TXOVRDEN = _i2c_u32("I2C__OVRD__TXOVRDEN_bm")
SCLVAL = _i2c_u32("I2C__OVRD__SCLVAL_bm")
SDAVAL = _i2c_u32("I2C__OVRD__SDAVAL_bm")
SCL_RX_BM = _i2c_u32("I2C__VAL__SCL_RX_bm")
SDA_RX_BM = _i2c_u32("I2C__VAL__SDA_RX_bm")
SCL_RX_BP = _i2c_u32("I2C__VAL__SCL_RX_bp")
SDA_RX_BP = _i2c_u32("I2C__VAL__SDA_RX_bp")

DISABLED_SAMPLES = 16
HELD_SAMPLES = 8
ISOLATION_SAMPLES = 8
POLL_BOUND_CYCLES = 400
VAL_SETTLE_CYCLES = 64
VAL_BURST_READS = 16
VAL_BURST_GAP_CYCLES = 8
BUS_RELEASE_POLLS = 2000

FENCE_TERMS = ("S1", "S2", "S3", "S4", "S5", "S6")
PROBES = ("tb_i2c0_scl", "tb_i2c0_sda", "tb_i2c0_scl_dut_low", "tb_i2c0_sda_dut_low")
INSTANCES = (0, 1, 2)


def _sample(name: str) -> int:
    value = getattr(cocotb.top, name).value
    assert value.is_resolvable, f"{name} sample is X/Z ({value})"
    return int(value)


def _levels(names: tuple[str, ...] = PROBES) -> tuple[int, ...]:
    return tuple(_sample(n) for n in names)


def _word_name(word: int) -> str:
    fields = (("TXOVRDEN", TXOVRDEN), ("SCLVAL", SCLVAL), ("SDAVAL", SDAVAL))
    parts = [n for n, bm in fields if word & bm]
    return "|".join(parts) if parts else "0x0"


def _fmt(levels: tuple[int, ...]) -> str:
    return "".join(str(v) for v in levels)


class smc_i2c_pad_override_test_seq(SmcCsrSeq):
    """Write OVRD words and log the sampled pad, probe and VAL levels."""

    def __init__(self, name: str = "smc_i2c_pad_override_test_seq") -> None:
        super().__init__(name)
        self.fence: list[tuple[str, int]] = []
        self.chk_lines: list[tuple[str, str]] = []

    def _mark(self, step: str) -> None:
        self.fence.append((step, int(get_sim_time("ps"))))

    def _chk(self, step: str, chk_id: str, text: str) -> None:
        assert self.fence and self.fence[-1][0] == step, (
            f"{chk_id} printed before its step {step} was recorded (fence {self.fence})"
        )
        cocotb.log.info("%s: %s", chk_id, text)
        self.chk_lines.append((chk_id, step))

    async def _sample_cycles(self, count: int) -> list[tuple[int, ...]]:
        rows = []
        for _ in range(count):
            await ClockCycles(cocotb.top.clk_smc_i, 1)
            rows.append(_levels())
        return rows

    async def _settle(self, label: str) -> tuple[int, tuple[int, ...]]:
        """Poll until all four levels are unchanged for HELD_SAMPLES samples; bounded."""
        clk = cocotb.top.clk_smc_i
        cur = _levels()
        run_start = 0
        held = 1
        for cycle in range(1, POLL_BOUND_CYCLES + 1):
            await ClockCycles(clk, 1)
            now = _levels()
            if now == cur:
                held += 1
            else:
                cur, run_start, held = now, cycle, 1
            if held > HELD_SAMPLES:
                return run_start, cur
        raise AssertionError(
            f"{label}: pad and probe levels not stable for {HELD_SAMPLES} samples within "
            f"{POLL_BOUND_CYCLES} clk_smc_i cycles (last {_fmt(cur)}, changed at cycle {run_start})"
        )

    async def _s1(self) -> None:
        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write("CLOCK_GATE_UNGATE_I2C", CLOCK_GATE_CONTROL, cg & ~I2C_CG_EN)
        await self.csr_write("I2C0_WRAP_EN", I2C0_WRAP_CTRL, I2C_WRAP_CTRL_TARGET)
        await self.wait_i2c0_lsio_ready("I2C0_PAD_OVRD")
        await self.wait_i2c_bus_released("I2C0_PAD_OVRD_BUS", BUS_RELEASE_POLLS)
        assert _levels(PROBES[:2]) == (1, 1), "tb_i2c0 pads not released after bring-up"
        self._mark("S1")

    async def _s2(self) -> None:
        words = (0, SCLVAL, SDAVAL, SCLVAL | SDAVAL)
        parts = []
        for word in words:
            await self.csr_write(f"OVRD_DISABLED_{word:x}", _ovrd(0), word)
            rows = await self._sample_cycles(DISABLED_SAMPLES)
            assert all(r[2:] == (0, 0) for r in rows), (
                f"OVRD {_word_name(word)} with TXOVRDEN=0: a pull probe is set "
                f"({' '.join(_fmt(r) for r in rows)})"
            )
            parts.append(f"{_word_name(word)}:{' '.join(_fmt(r) for r in rows)}")
        self._mark("S2")
        self._chk(
            "S2",
            "CHK-I2C-OVRD-DISABLED-OBS",
            f"TXOVRDEN=0 observation, {DISABLED_SAMPLES} samples per word as "
            f"scl,sda,scl_dut_low,sda_dut_low: " + "; ".join(parts),
        )

    async def _drive_and_settle(self, label: str, word: int) -> str:
        await self.csr_write(f"OVRD_{label}", _ovrd(0), word)
        settle, held = await self._settle(label)
        exp = (int(bool(word & SCLVAL)), int(bool(word & SDAVAL)))
        assert held[2:] == (1 - exp[0], 1 - exp[1]), (
            f"OVRD {_word_name(word)}: pull probes scl_dut_low,sda_dut_low={held[2]},{held[3]}, "
            f"want {1 - exp[0]},{1 - exp[1]} (a VAL of 0 pulls the line low)"
        )
        return (
            f"{_word_name(word)}: settle_cycle={settle} held scl,sda,scl_dut_low,sda_dut_low="
            f"{_fmt(held)} (RDL line level scl,sda={exp[0]}{exp[1]}; pull probes compared)"
        )

    async def _s3(self) -> None:
        words = (TXOVRDEN | SDAVAL, TXOVRDEN | SCLVAL, TXOVRDEN)
        parts = [await self._drive_and_settle(f"PULL_{w:x}", w) for w in words]
        self._mark("S3")
        self._chk("S3", "CHK-I2C-OVRD-PULL-OBS", "; ".join(parts))

    async def _s4(self) -> None:
        words = (TXOVRDEN | SCLVAL | SDAVAL, TXOVRDEN | SDAVAL, TXOVRDEN | SCLVAL)
        parts = [await self._drive_and_settle(f"REL_{w:x}", w) for w in words]
        self._mark("S4")
        self._chk("S4", "CHK-I2C-OVRD-RELEASE-OBS", "; ".join(parts))

    async def _s5(self) -> None:
        summary = []
        for n in INSTANCES:
            own = (f"tb_i2c{n}_scl_dut_low", f"tb_i2c{n}_sda_dut_low")
            others = tuple(
                f"tb_i2c{m}_{line}_dut_low" for m in INSTANCES if m != n for line in ("scl", "sda")
            )
            await self.csr_write(f"OVRD{n}_PULL", _ovrd(n), TXOVRDEN)
            for i in range(ISOLATION_SAMPLES):
                await ClockCycles(cocotb.top.clk_smc_i, 1)
                own_v, other_v = _levels(own), _levels(others)
                assert own_v == (1, 1) and not any(other_v), (
                    f"OVRD[{n}]=TXOVRDEN sample {i}: own probes {own_v} (want 1,1) "
                    f"other instances' probes {other_v} (want all 0)"
                )
            await self.csr_write(f"OVRD{n}_RELEASE", _ovrd(n), 0)
            for i in range(ISOLATION_SAMPLES):
                await ClockCycles(cocotb.top.clk_smc_i, 1)
                own_v = _levels(own)
                assert own_v == (0, 0), (
                    f"OVRD[{n}]=0 sample {i}: own probes {own_v} still pulling (want 0,0)"
                )
            summary.append(f"I2C{n}")
        self._mark("S5")
        self._chk(
            "S5",
            "CHK-I2C-OVRD-INSTANCE-ISOLATION",
            f"for {', '.join(summary)}: OVRD=TXOVRDEN held own scl/sda probes 1,1 and the other "
            f"two instances' probes 0 on {ISOLATION_SAMPLES} of {ISOLATION_SAMPLES} samples; "
            f"OVRD=0 returned own probes to 0,0 on {ISOLATION_SAMPLES} of {ISOLATION_SAMPLES}",
        )

    async def _read_val(self, label: str) -> str:
        word = await self.csr_read(label, I2C0_VAL)
        scl_rx = (word & SCL_RX_BM) >> SCL_RX_BP
        sda_rx = (word & SDA_RX_BM) >> SDA_RX_BP
        return f"{scl_rx:04x}/{sda_rx:04x}"

    async def _val_phase(self, tag: str, low_word: int) -> list[str]:
        out = []
        await self.csr_write(f"OVRD_{tag}_LOW", _ovrd(0), low_word)
        await ClockCycles(cocotb.top.clk_smc_i, VAL_SETTLE_CYCLES)
        out.append(f"{tag}_low_after_{VAL_SETTLE_CYCLES}={await self._read_val(f'VAL_{tag}_LOW')}")
        await self.csr_write(f"OVRD_{tag}_RELEASE", _ovrd(0), TXOVRDEN | SCLVAL | SDAVAL)
        burst = []
        for i in range(VAL_BURST_READS):
            burst.append(await self._read_val(f"VAL_{tag}_REL{i}"))
            await ClockCycles(cocotb.top.clk_smc_i, VAL_BURST_GAP_CYCLES)
        out.append(f"{tag}_release_burst={' '.join(burst)}")
        return out

    async def _s6(self) -> None:
        await self.csr_write("OVRD_VAL_RELEASED", _ovrd(0), TXOVRDEN | SCLVAL | SDAVAL)
        parts = [f"released={await self._read_val('VAL_RELEASED')}"]
        parts += await self._val_phase("SCL", TXOVRDEN | SDAVAL)
        parts += await self._val_phase("SDA", TXOVRDEN | SCLVAL)
        await self.csr_write("OVRD_RESTORE", _ovrd(0), 0)
        self._mark("S6")
        self._chk(
            "S6",
            "CHK-I2C-VAL-SENSE-OBS",
            "VAL words as SCL_RX/SDA_RX hex, not compared: " + "; ".join(parts),
        )

    async def body(self) -> None:
        await self._s1()
        await self._s2()
        await self._s3()
        await self._s4()
        await self._s5()
        await self._s6()
        stamps = assert_fence_progress(self.fence, list(FENCE_TERMS))
        ids = [c for c, _ in self.chk_lines]
        assert len(ids) == 5 and all(
            any(s == term for _, s in self.chk_lines) for term in FENCE_TERMS[1:]
        ), f"checker lines {self.chk_lines} do not cover S2-S6"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s ps",
            " < ".join(FENCE_TERMS),
            ",".join(ids),
            stamps,
        )
