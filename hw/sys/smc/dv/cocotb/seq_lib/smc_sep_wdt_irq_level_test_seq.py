# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP watchdog reset input into raw tb_cpu_interrupts bit 282 and tb_sep_wdt_irq_sync.

Spec sources: interrupts.adoc SMC indexed interrupt map table; port_table.adoc
sep_wdt_reset_n_i.
"""

from __future__ import annotations

import os

import cocotb
from cocotb.triggers import RisingEdge
from cocotb.utils import get_sim_time

from .smc_addr_map import smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

SCRATCH_COLD_WARM_0 = smc_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_WARM_BASE_ADDR")
WDT_BIT = 282
WINDOW_RISES = 64
# Ceilings in clk_smc_i rises; not latency claims.
ASSERT_CEILING_RISES = 64
WARM_RELEASE_CEILING_RISES = 200000
_STEPS = ("S1", "S2", "S3", "S4", "S5")
_CHECKERS = (
    "CHK-SEPWDT-IDLE-ZERO",
    "CHK-SEPWDT-ASSERT-HIGH",
    "CHK-SEPWDT-RELEASE-ZERO",
    "CHK-SEPWDT-LATENCY-LOG",
)
_CHECK_STEP = ("S2", "S3", "S4", "S5")


class smc_sep_wdt_irq_level_test_seq(SmcCsrSeq):
    """Drive tb_sep_wdt_reset_n and observe raw bit 282, the synchroniser and the warm reset."""

    def __init__(self, name: str = "smc_sep_wdt_irq_level_test_seq") -> None:
        super().__init__(name)
        self.phases = 0
        self._stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []
        self._waits: dict[str, tuple[int, str]] = {}

    def _mark_step(self, step_id: str) -> None:
        self._stamps.append((step_id, int(get_sim_time("ps"))))

    def _log_chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self._chk_marks.append((chk_id, int(get_sim_time("ps"))))

    @staticmethod
    def _resolved(sig, label: str) -> int:
        assert sig.value.is_resolvable, f"{label}: {sig._name} is X/Z ({sig.value})"
        return int(sig.value)

    def _sample(self, label: str) -> tuple[int, int, int]:
        """Return (raw bit 282, tb_sep_wdt_irq_sync, tb_rst_warm_smc_clk_n) at this rise."""
        dut = cocotb.top
        raw = self._resolved(dut.tb_cpu_interrupts, label) >> WDT_BIT & 1
        sync = self._resolved(dut.tb_sep_wdt_irq_sync, label)
        warm = self._resolved(dut.tb_rst_warm_smc_clk_n, label)
        return raw, sync, warm

    def _drive(self, value: int, why: str) -> None:
        cocotb.top.tb_sep_wdt_reset_n.value = value
        cocotb.log.info(
            "DRIVE tb_sep_wdt_reset_n=%d (%s) at %d ps", value, why, int(get_sim_time("ps"))
        )

    async def _window_zero(self, name: str) -> None:
        for n in range(1, WINDOW_RISES + 1):
            await RisingEdge(cocotb.top.clk_smc_i)
            raw, sync, warm = self._sample(f"{name}[{n}]")
            self._waits[name] = (WINDOW_RISES, f"raw282={raw} sync={sync} warm_n={warm} rise {n}")
            assert raw == 0 and sync == 0, (
                f"{name}: raw282={raw} sync={sync} warm_n={warm} at rise {n}, want 0/0"
            )

    async def _await_high(self) -> int:
        name = "assert wait"
        raw, sync, warm = self._sample(f"{name} entry")
        self._waits[name] = (ASSERT_CEILING_RISES, f"raw282={raw} sync={sync} warm_n={warm}")
        raw_at = sync_at = 0
        for n in range(1, ASSERT_CEILING_RISES + 1):
            await RisingEdge(cocotb.top.clk_smc_i)
            raw, sync, warm = self._sample(f"{name}[{n}]")
            self._waits[name] = (
                ASSERT_CEILING_RISES,
                f"raw282={raw} sync={sync} warm_n={warm} after {n} rises",
            )
            cocotb.log.info(
                "WDT-LOG assert rise %d raw282=%d sync=%d warm_n=%d", n, raw, sync, warm
            )
            raw_at = raw_at or (n if raw else 0)
            sync_at = sync_at or (n if sync else 0)
            if raw_at and sync_at:
                self._first_high = raw_at
                return sync_at
        raise AssertionError(
            f"{name}: raw282 high at rise {raw_at}, sync high at rise {sync_at} within "
            f"{ASSERT_CEILING_RISES} clk_smc_i rises (last raw282={raw} sync={sync} warm_n={warm})"
        )

    async def _log_through_warm(self) -> str:
        """Log raw bit 282 for one window of rises while the pin is held low; never compared."""
        values = []
        warm_low = 0
        for n in range(1, WINDOW_RISES + 1):
            await RisingEdge(cocotb.top.clk_smc_i)
            raw, sync, warm = self._sample(f"through warm[{n}]")
            values.append(raw)
            warm_low += 1 - warm
            cocotb.log.info(
                "WDT-LOG through-warm rise %d raw282=%d sync=%d warm_n=%d", n, raw, sync, warm
            )
        bits = "".join(map(str, values))
        return f"raw282 over {WINDOW_RISES} rises {bits}, warm_n low at {warm_low} rises"

    async def _await_release(self) -> tuple[int, int]:
        """Return (rises to warm_n=1, rises to first raw282 low), counted from the pin release."""
        name = "warm release wait"
        bound = WARM_RELEASE_CEILING_RISES
        raw, sync, warm = self._sample(f"{name} entry")
        first_low = 0 if raw == 0 else None
        self._waits[name] = (bound, f"raw282={raw} sync={sync} warm_n={warm}")
        for n in range(1, bound + 1):
            await RisingEdge(cocotb.top.clk_smc_i)
            raw, sync, warm = self._sample(f"{name}[{n}]")
            if first_low is None and raw == 0:
                first_low = n
            self._waits[name] = (bound, f"raw282={raw} sync={sync} warm_n={warm} after {n} rises")
            if n <= WINDOW_RISES:
                cocotb.log.info(
                    "WDT-LOG release rise %d raw282=%d sync=%d warm_n=%d", n, raw, sync, warm
                )
            if warm:
                return n, first_low if first_low is not None else -1
        raise AssertionError(
            f"{name}: tb_rst_warm_smc_clk_n still 0 after {bound} clk_smc_i rises "
            f"(last raw282={raw} sync={sync})"
        )

    def _log_legs(self, chk: str, set_text: str, observed: str, cleared: str, checked: str):
        cocotb.log.info("LIFECYCLE %s set: %s", chk, set_text)
        cocotb.log.info("LIFECYCLE %s observed: %s", chk, observed)
        cocotb.log.info("LIFECYCLE %s cleared: %s", chk, cleared)
        cocotb.log.info("LIFECYCLE %s checked_cleared: %s", chk, checked)

    async def body(self) -> None:
        dut = cocotb.top
        await self.wait_fuse_sense_done()
        for sig in (
            "tb_sep_wdt_reset_n",
            "tb_cpu_interrupts",
            "tb_sep_wdt_irq_sync",
            "tb_rst_warm_smc_clk_n",
        ):
            assert hasattr(dut, sig), f"{sig} missing"
        got = await self.csr_read("SCRATCH_COLD_WARM_0", SCRATCH_COLD_WARM_0)
        cocotb.log.info(
            "SEED RANDOM_SEED=%s SCRATCH_COLD_WARM_0=0x%x", os.environ.get("RANDOM_SEED", "1"), got
        )
        self._drive(1, "idle before baseline")
        await RisingEdge(dut.clk_smc_i)
        base = self._resolved(dut.tb_cpu_interrupts, "baseline")
        pin = self._resolved(dut.tb_sep_wdt_reset_n, "baseline")
        raw, sync, warm = self._sample("baseline")
        assert pin == 1, f"baseline tb_sep_wdt_reset_n={pin}"
        assert raw == 0 and sync == 0, f"baseline raw282={raw} sync={sync}"
        cocotb.log.info(
            "BASELINE vector=0x%x pin=%d raw282=%d sync=%d warm_n=%d", base, pin, raw, sync, warm
        )
        self._mark_step("S1")

        await self._window_zero("idle window")
        self.phases += 1
        self._mark_step("S2")
        self._log_legs(
            "CHK-SEPWDT-IDLE-ZERO",
            "tb_sep_wdt_reset_n held 1 at idle",
            "tb_cpu_interrupts[282] and tb_sep_wdt_irq_sync each rise",
            "not applicable",
            "both read 0 for 64 rises",
        )
        self._log_chk(
            "CHK-SEPWDT-IDLE-ZERO",
            f"pin=1 raw282=0 sync=0 at each of {WINDOW_RISES} consecutive rises",
        )

        await RisingEdge(dut.clk_smc_i)
        self._drive(0, "assert")
        sync_at = await self._await_high()
        raw_at = self._first_high
        through = await self._log_through_warm()
        self.phases += 1
        self._mark_step("S3")
        self._log_legs(
            "CHK-SEPWDT-ASSERT-HIGH",
            "tb_sep_wdt_reset_n driven 0",
            "tb_cpu_interrupts[282] and tb_sep_wdt_irq_sync each rise",
            "tb_sep_wdt_reset_n driven 1 in S4",
            "raw bit 282 reads 0 after the warm reset releases",
        )
        self._log_chk(
            "CHK-SEPWDT-ASSERT-HIGH",
            f"raw282 first 1 after {raw_at} rises, sync first 1 after {sync_at} rises "
            f"(ceiling {ASSERT_CEILING_RISES}); through-warm log (not compared): "
            f"{through}",
        )

        await RisingEdge(dut.clk_smc_i)
        self._drive(1, "release")
        warm_rises, first_low = await self._await_release()
        await self._window_zero("release window")
        self.phases += 1
        self._mark_step("S4")
        self._log_legs(
            "CHK-SEPWDT-RELEASE-ZERO",
            "tb_sep_wdt_reset_n driven 0 in S3",
            "tb_cpu_interrupts[282] and tb_rst_warm_smc_clk_n each rise",
            "tb_sep_wdt_reset_n driven 1",
            "raw282 and sync read 0 for 64 rises after warm reset release",
        )
        self._log_chk(
            "CHK-SEPWDT-RELEASE-ZERO",
            f"pin=1, warm_n=1 after {warm_rises} rises (ceiling "
            f"{WARM_RELEASE_CEILING_RISES}); raw282=0 sync=0 at each of {WINDOW_RISES} "
            f"consecutive rises after warm_n=1",
        )

        await RisingEdge(dut.clk_smc_i)
        raw, sync, warm = self._sample("latency rise")
        assert raw == 0 and sync == 0, f"after latency measurement raw282={raw} sync={sync}"
        self.phases += 1
        self._mark_step("S5")
        self._log_chk(
            "CHK-SEPWDT-LATENCY-LOG",
            f"fall_to_first_raw282_high_rises={raw_at} "
            f"release_to_first_raw282_low_rises={first_low} "
            "(observe-and-log, not specified, measured)",
        )

        self._nonvac_fence()
        self._log_timeout_paths()

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
            "CHK-NONVAC: ordered fence IDLE<ASSERT<WARM-RESET-RELEASE<RELEASE-ZERO<LATENCY-LOG; "
            "checker lines %s; stamps %s",
            ",".join(chk_ids),
            ",".join(f"{s}={t}" for s, t in self._stamps),
        )

    def _log_timeout_paths(self) -> None:
        waits = "; ".join(
            f"{name} bound={bound} rises last[{last}]"
            for name, (bound, last) in self._waits.items()
        )
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: every expiry raises AssertionError with the last sampled "
            "values; %s",
            waits,
        )
