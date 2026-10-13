# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC scratchpad zero-fill completion indication and its order against the first ROM read.

Contract SMU_SMC_BOOT_005, anchor smu_smc_sram_init_sequence_test.
Spec: hw/sys/smc/doc/cpu.adoc Reset and Boot; hw/sys/smu/doc/port_table.adoc
smc_init_mem_done_o and smc_disable_sram_auto_init_i rows.

One sampler reads smc_init_mem_done_o, smc_scratch_write_count_dv_o and smc_rom_read_count_o on
every clk_smu_i edge from before the shared bring-up. The only stimulus is a second cold reset on
rst_cold_ni. The done level during that reset is open (SF-010) and is logged, never compared.
"""

from __future__ import annotations

import time

import cocotb
from cocotb.triggers import RisingEdge

SAMPLER_BOUND = 1_200_000
DONE_BOUND = 400_000
POST_RISE_CYCLES = 64
RESET_HOLD_REF_EDGES = 600
SITE_NAMES = ("S1_sampler", "S2_done_rise_boot1", "S3_first_rom_read", "S4_done_rise_boot2")


def _rd(sig, name: str) -> int:
    val = sig.value
    if not val.is_resolvable:
        raise AssertionError(f"X/Z sample on {name}: {val}")
    return int(val)


class smu_smc_sram_init_sampler:
    """Per-clk_smu_i record of the done pin and the two bench counters."""

    def __init__(self) -> None:
        dut = cocotb.top
        self.dut = dut
        self.stop = False
        self.edges = 0
        self.done = 0
        self.writes = 0
        self.rom = 0
        self.rises: list[int] = []
        self.writes_at_rise: list[int] = []
        self.writes_after: dict[int, int] = {}
        self.rom_at_rise: list[int] = []
        self.first_rom: tuple[int, int] | None = None
        self.expired = 0
        self.task = None

    def arm(self) -> None:
        self.task = cocotb.start_soon(self._run())

    async def _run(self) -> None:
        dut = self.dut
        prev = None
        for k in range(SAMPLER_BOUND):
            await RisingEdge(dut.clk_smu_i)
            self.done = _rd(dut.smc_init_mem_done_o, "smc_init_mem_done_o")
            self.writes = _rd(dut.smc_scratch_write_count_dv_o, "smc_scratch_write_count_dv_o")
            self.rom = _rd(dut.smc_rom_read_count_o, "smc_rom_read_count_o")
            self.edges = k + 1
            if prev == 0 and self.done == 1:
                self.rises.append(k)
                self.writes_at_rise.append(self.writes)
                self.rom_at_rise.append(self.rom)
            for idx, rise in enumerate(self.rises):
                if k == rise + POST_RISE_CYCLES:
                    self.writes_after[idx] = self.writes
            if self.first_rom is None and self.rom:
                self.first_rom = (k, self.rom)
            prev = self.done
            if self.stop:
                return
        self.expired = 1
        raise AssertionError(f"TIMEOUT S1_sampler: still running after {SAMPLER_BOUND} clk_smu")


class smu_smc_sram_init_sequence_test_seq:
    """smc_init_mem_done_o across two cold boots with the automatic initialization enabled."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.sb = test.env.scoreboard
        self.sampler = test.sampler
        self.step_ts: dict[str, float] = {}
        self.sites = {
            name: {"bound": 0, "count": 0, "last": "none", "expired": 0} for name in SITE_NAMES
        }

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    def _mark(self, step: str, text: str) -> None:
        self.step_ts[step] = time.monotonic()
        self._log(f"STEP {step}: {text}")

    def _state(self) -> str:
        s = self.sampler
        return f"done={s.done} writes={s.writes} rom={s.rom} rises={len(s.rises)}"

    async def _wait(self, site: str, cond) -> int:
        """clk_smu_i edges until cond() holds, under DONE_BOUND, recording the last state."""
        rec = self.sites[site]
        rec["bound"] = DONE_BOUND
        rec["last"] = self._state()
        for n in range(DONE_BOUND):
            if cond():
                rec["count"] = n
                rec["last"] = self._state()
                return n
            await RisingEdge(self.dut.clk_smu_i)
        rec["count"] = DONE_BOUND
        rec["last"] = self._state()
        rec["expired"] = 1
        raise AssertionError(f"TIMEOUT {site}: bound {DONE_BOUND} clk_smu, last {rec['last']}")

    async def run(self) -> None:
        dut = self.dut
        sb = self.sb
        s = self.sampler

        # S1: sampler armed before the bring-up; automatic initialization enabled.
        await self.test.cfg.reset_done.wait()
        self._mark("S1", "sampler armed before the bring-up, no scratch RAM preload")
        sb.expect_true(
            "no +smc_scratch_ram_hex image, so the wrapper leaves smc_disable_sram_auto_init_i low",
            cocotb.plusargs.get("smc_scratch_ram_hex") is None,
        )

        # S2: one done rise per cold boot, after the last zero-fill write.
        self._mark("S2", "first done rise and the write count 64 clk_smu later")
        await self._wait("S2_done_rise_boot1", lambda: bool(s.rises) and 0 in s.writes_after)
        rise1 = s.rises[0]
        at_rise = s.writes_at_rise[0]
        after = s.writes_after[0]
        self._log(
            f"CELL done_single_rise smc_init_mem_done_o={s.done} rises={len(s.rises)} cycle={rise1}"
        )
        self._log(f"CELL done_after_last_write smc_scratch_write_count_dv_o={at_rise}/{after}")
        sb.expect_eq(
            "one done rise, writes above 0 at the rise and unchanged 64 cycles later, done high",
            (len(s.rises), at_rise > 0, after == at_rise, s.done),
            (1, True, True, 1),
            evidence="BOOT_INIT_DONE_ONCE",
        )

        # S3: no ROM read before the rise, the first one after it.
        self._mark("S3", "ROM read counter zero until the done rise, first read after it")
        await self._wait("S3_first_rom_read", lambda: s.first_rom is not None)
        first_cycle, first_val = s.first_rom
        self._log(
            f"CELL no_rom_read_before_init_done smc_rom_read_count_o={s.rom_at_rise[0]} "
            f"at the rise cycle={rise1}"
        )
        self._log(
            f"CELL first_rom_read_after_init_done smc_rom_read_count_o={first_val} cycle={first_cycle}"
        )
        sb.expect_eq(
            "ROM read counter is 0 at the rise and its first increment is later than the rise",
            (s.rom_at_rise[0], first_cycle > rise1),
            (0, True),
            evidence="BOOT_INIT_BEFORE_FETCH",
        )

        # S4: second cold boot re-arms the indication.
        self._mark("S4", "second cold reset, hold, release, second done rise")
        dut.rst_cold_ni.value = 0
        for _ in range(RESET_HOLD_REF_EDGES):
            await RisingEdge(dut.clk_ref_i)
        done_in_reset = _rd(dut.smc_init_mem_done_o, "smc_init_mem_done_o")
        primary = _rd(dut.rst_primary_smc_clk_n_o, "rst_primary_smc_clk_n_o")
        writes_in_reset = _rd(dut.smc_scratch_write_count_dv_o, "smc_scratch_write_count_dv_o")
        self._log(
            f"CHK-BOOT-INIT-REARM: done_during_reset={done_in_reset} primary_smc={primary} "
            f"write_count={writes_in_reset}"
        )
        dut.rst_cold_ni.value = 1
        await self._wait("S4_done_rise_boot2", lambda: len(s.rises) >= 2)
        rise2 = s.rises[1]
        writes2 = s.writes_at_rise[1]
        self._log(
            f"CELL second_cold_boot_rearm smc_init_mem_done_o={s.done} rises={len(s.rises)} "
            f"cycle={rise2} writes={writes_in_reset}->{writes2}"
        )
        sb.expect_eq(
            "second done rise after the writes restarted, done high",
            (len(s.rises), writes2 > writes_in_reset, s.done),
            (2, True, 1),
            evidence="BOOT_INIT_REARM",
        )
        s.stop = True
        await s.task
        rec = self.sites["S1_sampler"]
        rec.update(
            bound=SAMPLER_BOUND,
            count=s.edges,
            last=self._state(),
            expired=s.expired,
        )

        # S5: timeout records and ordered fence.
        self._mark("S5", "TIMEOUT: bounded waits and last state")
        for site, r in self.sites.items():
            state = "EXPIRED" if r["expired"] else "ok"
            self._log(
                f"TIMEOUT-PATH {site}: bound={r['bound']} {state} count={r['count']} last={r['last']}"
            )
        expired = sum(r["expired"] for r in self.sites.values())
        self._log(f"CHK-TIMEOUT-PATHS: sites={len(self.sites)} expired={expired}")
        sb.expect_eq("expired TIMEOUT-PATH records", expired, 0, evidence="CHK_TIMEOUT_PATHS")
        sb.expect_eq(
            "bounded wait sites named by the contract",
            sorted(self.sites),
            [
                "S1_sampler",
                "S2_done_rise_boot1",
                "S3_first_rom_read",
                "S4_done_rise_boot2",
            ],
        )

        self.step_ts["PASS"] = time.monotonic()
        order = ["S1", "S2", "S3", "S4", "S5", "PASS"]
        for a, b in zip(order, order[1:]):
            if self.step_ts[a] >= self.step_ts[b]:
                raise AssertionError(f"CHK-NONVAC order fail: {a} not before {b}")
        self._log("CHK-NONVAC: PASS (ordered fence S1<S2<S3<S4<S5<PASS)")
        sb.expect_eq("CHK-NONVAC ordered fence", len(order), 6, evidence="CHK-NONVAC")
        dut.rst_cold_ni.value = 1
