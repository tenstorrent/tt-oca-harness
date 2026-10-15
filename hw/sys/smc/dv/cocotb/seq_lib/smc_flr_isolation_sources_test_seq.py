# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Isolation request sources, the FLR latch and skip_mem_repair_o.

Sources: smc/doc/clk_rst.adoc (Function Level Reset and Isolation), smc/doc/cpu.adoc.

isolate_req_o bit 3 is ISOLATE_REQ_REG[3] OR (PINEN[3] AND pin) OR (SMCEN[3] AND latch). The
FLR counters stay at their reset value 0, so an FLR edge sets the latch without a cool reset.
The pin is the isolate-request pad driven through the bench GPIO external drive.
"""

from __future__ import annotations

import csv

import cocotb
from cocotb.triggers import ClockCycles
from cocotb.utils import get_sim_time

from .smc_addr_map import _REPO, smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

ISO_REG = smc_addr("SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_REG_BASE_ADDR")
PINEN_REG = smc_addr("SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_PINEN_REG_BASE_ADDR")
SMCEN_REG = smc_addr("SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_SMCEN_REG_BASE_ADDR")
SMC_REG = smc_addr("SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_SMC_REG_BASE_ADDR")
BIT3 = 1 << 3
_PAD_TABLE = _REPO / "doc" / "integrator" / "meta" / "ocah_gpio_table.csv"

#: Ceiling in clk_smc_i cycles for an output to follow its inputs; expiry fails.
_BOUND = 128
#: Consecutive rises that must agree where the spec asks for a held level.
_HOLD = 32
_NO_SKIP_RISES = 64
#: Largest delay, in clk_smc_i cycles, between the write launch and the FLR raise.
_SWEEP_MAX = 96
_STEP_IDS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7")
_CHK_IDS = (
    "CHK-FLR-REG-SOURCE",
    "CHK-FLR-PIN-SOURCE",
    "CHK-FLR-SOURCE-OR",
    "CHK-FLR-LATCH-SET",
    "CHK-FLR-LATCH-CLEAR",
    "CHK-FLR-SW-NO-SKIP",
)
_CHK_STEP = dict(zip(_CHK_IDS, ("S2", "S3", "S4", "S5", "S6", "S7")))


def _isolate_req_pad() -> int:
    with _PAD_TABLE.open(newline="", encoding="utf-8") as handle:
        rows = [row for row in csv.DictReader(handle) if row.get("Function") == "Isolate Request"]
    if len(rows) != 1:
        raise AssertionError(f"{_PAD_TABLE}: expected one Isolate Request pad, found {len(rows)}")
    return int(rows[0]["Index"])


class smc_flr_isolation_sources_test_seq(SmcCsrSeq):
    """Walk steps S1-S7 and print one evidence line per checker."""

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self._stamps: list[tuple[str, int]] = []
        self._chk_lines: list[tuple[str, str, int]] = []
        self._pad_mask = 1 << _isolate_req_pad()

    @staticmethod
    def _bit(sig, label: str) -> int:
        raw = sig.value
        assert raw.is_resolvable, f"{label} is X/Z: {raw}"
        return int(raw)

    def _iso3(self) -> int:
        return (self._bit(cocotb.top.tb_isolate_req_o, "tb_isolate_req_o") >> 3) & 1

    def _skip(self) -> int:
        return self._bit(cocotb.top.tb_skip_mem_repair_o, "tb_skip_mem_repair_o") & 1

    def _assert_no_cool_reset(self, label: str) -> None:
        level = self._bit(cocotb.top.tb_rst_cool_from_flr, "tb_rst_cool_from_flr") & 1
        assert level == 1, f"{label}: cool reset output asserted (tb_rst_cool_from_flr=0)"

    def _pin(self, level: int) -> None:
        dut = cocotb.top
        val = int(dut.tb_gpio_ext_drive_value.value)
        val = (val | self._pad_mask) if level else (val & ~self._pad_mask)
        dut.tb_gpio_ext_drive_value.value = val
        dut.tb_gpio_ext_drive_en.value = int(dut.tb_gpio_ext_drive_en.value) | self._pad_mask

    async def _await(self, probe, want: int, label: str) -> int:
        """Return the cycle count at which ``probe()`` first reads ``want``; fail on expiry."""
        last = -1
        for cycle in range(1, _BOUND + 1):
            await ClockCycles(cocotb.top.clk_smc_i, 1)
            self._assert_no_cool_reset(label)
            last = probe()
            if last == want:
                return cycle
        raise AssertionError(f"{label}: stayed {last} for {_BOUND} clk_smc_i cycles, want {want}")

    async def _await_after(self, probe, want: int, label: str, elapsed: int) -> int:
        """Like ``_await``, counted from the rise ``elapsed`` rises after the stimulus."""
        if probe() == want:
            return elapsed
        return elapsed + await self._await(probe, want, label)

    async def _hold(self, probe, want: int, rises: int, label: str) -> None:
        for n in range(rises):
            await ClockCycles(cocotb.top.clk_smc_i, 1)
            self._assert_no_cool_reset(label)
            got = probe()
            assert got == want, f"{label}: rise {n + 1}/{rises} read {got}, want {want}"

    def _stamp(self, step: str) -> None:
        now = int(get_sim_time("ps"))
        assert not self._stamps or now > self._stamps[-1][1], f"{step}: stamp {now} not increasing"
        self._stamps.append((step, now))

    def _chk(self, chk_id: str, text: str) -> None:
        step = _CHK_STEP[chk_id]
        assert self._stamps and self._stamps[-1][0] == step, f"{chk_id} printed outside {step}"
        self._chk_lines.append((chk_id, step, len(self._stamps)))
        cocotb.log.info("%s: %s", chk_id, text)

    async def _flr_low_and_clear_latch(self, label: str) -> None:
        dut = cocotb.top
        dut.tb_cfg_flr_pf_active.value = 0
        await self._await(lambda: self._bit(dut.tb_flr_sync_ref, "tb_flr_sync_ref") & 1, 0, label)
        await self.csr_write(f"{label}_CLEAR", SMC_REG, 0)
        await self._await(self._skip, 0, f"{label}_SKIP0")
        await self._await(self._iso3, 0, f"{label}_ISO0")

    async def _clear_latency(self) -> tuple[int, int]:
        """Rises from the write launch until skip reads 0 and until iso[3] reads 0."""
        dut = cocotb.top
        skip_at = None
        for cycle in range(1, _BOUND + 1):
            await ClockCycles(dut.clk_smc_i, 1)
            skip, iso = self._skip(), self._iso3()
            if skip_at is None:
                assert skip == 0 or iso == 1, f"iso[3] fell before skip_mem_repair_o at {cycle}"
                if skip == 0:
                    skip_at = cycle
            if skip_at is not None and iso == 0:
                return skip_at, cycle
        raise AssertionError(f"clear write: outputs still skip={skip} iso3={iso} after {_BOUND}")

    async def _flr_edge_trial(self, delay: int) -> tuple[int, int]:
        """Write the latch clear while FLR rises ``delay`` cycles after the write launch."""
        dut = cocotb.top
        await self._flr_low_and_clear_latch(f"TRIAL{delay}")

        async def raise_flr() -> None:
            if delay:
                await ClockCycles(dut.clk_smc_i, delay)
            dut.tb_cfg_flr_pf_active.value = 1

        raiser = cocotb.start_soon(raise_flr())
        await self.csr_write(f"TRIAL{delay}_WR", SMC_REG, 0)
        await raiser
        tail = []
        for _ in range(_HOLD):
            await ClockCycles(dut.clk_smc_i, 1)
            self._assert_no_cool_reset(f"TRIAL{delay}")
            tail.append((self._skip(), self._iso3()))
        final = tail[_HOLD // 2 :]
        assert len(set(final)) == 1, f"TRIAL{delay}: outputs still moving at the end: {final}"
        return final[-1]

    async def body(self) -> None:
        dut = cocotb.top
        for name in (
            "tb_isolate_req_o",
            "tb_skip_mem_repair_o",
            "tb_cfg_flr_pf_active",
            "tb_rst_cool_from_flr",
            "tb_flr_sync_ref",
            "tb_gpio_ext_drive_en",
            "tb_gpio_ext_drive_value",
        ):
            assert hasattr(dut, name), f"{name} missing from tb_top"
        await self.wait_fuse_sense_done()

        # S1: all sources inactive.
        dut.tb_cfg_flr_pf_active.value = 0
        self._pin(0)
        await self.csr_read("ISO_REG_IDLE", ISO_REG, expected=0)
        await self.csr_read("PINEN_IDLE", PINEN_REG, expected=0)
        await self.csr_read("SMCEN_IDLE", SMCEN_REG, expected=0)
        await self.csr_read("SMC_REG_IDLE", SMC_REG, expected=0)
        await self._hold(self._iso3, 0, 8, "S1_ISO")
        await self._hold(self._skip, 0, 8, "S1_SKIP")
        self._stamp("S1")

        # S2: the register source.
        await self.csr_write("ISO_REG_SET", ISO_REG, BIT3)
        up = await self._await(self._iso3, 1, "S2_UP")
        await self.csr_write("ISO_REG_CLR", ISO_REG, 0)
        down = await self._await(self._iso3, 0, "S2_DOWN")
        self._stamp("S2")
        self._chk(
            "CHK-FLR-REG-SOURCE",
            f"tb_isolate_req_o[3] read 1 {up} rises after ISOLATE_REQ_REG[3] set and 0 {down} "
            "rises after it cleared; tb_rst_cool_from_flr stayed 1",
        )

        # S3: the pin source, gated by PINEN.
        self._pin(1)
        pin_arrived = await self._await(self._skip, 1, "S3_PIN_SYNC")
        await self._hold(self._iso3, 0, _HOLD, "S3_PINEN_CLEAR")
        await self.csr_write("PINEN_SET", PINEN_REG, BIT3)
        pin_up = await self._await(self._iso3, 1, "S3_PINEN_UP")
        self._pin(0)
        await self._await(self._iso3, 0, "S3_PIN_DROP")
        self._stamp("S3")
        self._chk(
            "CHK-FLR-PIN-SOURCE",
            f"pin high: tb_isolate_req_o[3] read 0 on {_HOLD} of {_HOLD} rises with PINEN[3] "
            f"clear (pin seen by skip_mem_repair_o after {pin_arrived} rises), read 1 {pin_up} "
            "rises after PINEN[3] set",
        )

        # S4: the register source cleared while the pin source holds the request.
        self._pin(1)
        await self._await(self._skip, 1, "S4_PIN_SYNC")
        await self.csr_write("ISO_REG_SET2", ISO_REG, BIT3)
        await self._await(self._iso3, 1, "S4_REG_UP")
        await self.csr_write("ISO_REG_CLR2", ISO_REG, 0)
        await self._hold(self._iso3, 1, _HOLD, "S4_PIN_HOLDS")
        self._pin(0)
        pin_down = await self._await(self._iso3, 0, "S4_PIN_DROP")
        self._stamp("S4")
        self._chk(
            "CHK-FLR-SOURCE-OR",
            f"register cleared with pin active: tb_isolate_req_o[3] read 1 on {_HOLD} of {_HOLD} "
            f"rises; read 0 {pin_down} rises after the pin dropped",
        )

        # S5: the FLR edge sets the latch.
        await self.csr_write("PINEN_CLR", PINEN_REG, 0)
        await self.csr_write("SMCEN_SET", SMCEN_REG, BIT3)
        await self._hold(self._skip, 0, 8, "S5_PRE_SKIP")
        await self._hold(self._iso3, 0, 8, "S5_PRE_ISO")
        dut.tb_cfg_flr_pf_active.value = 1
        skip_up = await self._await(self._skip, 1, "S5_SKIP_UP")
        iso_up = await self._await_after(self._iso3, 1, "S5_ISO_UP", skip_up)
        sync_rise = await self._await_after(
            lambda: self._bit(dut.tb_flr_sync_ref, "tb_flr_sync_ref") & 1,
            1,
            "S5_FLR_SYNC",
            iso_up,
        )
        await self._hold(self._skip, 1, _HOLD, "S5_SKIP_HOLD")
        await self._hold(self._iso3, 1, _HOLD, "S5_ISO_HOLD")
        self._stamp("S5")
        self._chk(
            "CHK-FLR-LATCH-SET",
            f"before the edge both outputs read 0 on 8 of 8 rises; after tb_cfg_flr_pf_active rose "
            f"tb_skip_mem_repair_o read 1 after {skip_up} rises and tb_isolate_req_o[3] read 1 "
            f"after {iso_up} rises (reference-domain sync after {sync_rise}); both held on "
            f"{_HOLD} of {_HOLD} rises",
        )

        # S6: write 0 clears the latch; a write at a new FLR edge leaves it set.
        # With FLR low again the latch outputs must stay set until the clearing write lands.
        dut.tb_cfg_flr_pf_active.value = 0
        for cycle in range(1, _BOUND + 1):
            await ClockCycles(dut.clk_smc_i, 1)
            assert (self._skip(), self._iso3()) == (1, 1), "latch output dropped on FLR fall"
            if not self._bit(dut.tb_flr_sync_ref, "tb_flr_sync_ref") & 1:
                break
        else:
            raise AssertionError(f"S6_FLR_LOW: tb_flr_sync_ref still 1 after {_BOUND} cycles")
        launch_sampler = cocotb.start_soon(self._clear_latency())
        await self.csr_write("SMC_REG_CLR", SMC_REG, 0xFFFF_FFFF)
        clr_skip, clr_iso = await launch_sampler
        await self._hold(self._skip, 0, _HOLD, "S6_SKIP_STAYS")
        outcomes: list[tuple[int, int, int]] = []
        first_set = None
        for delay in range(_SWEEP_MAX + 1):
            skip, iso = await self._flr_edge_trial(delay)
            outcomes.append((delay, skip, iso))
            assert skip == iso, f"delay {delay}: skip={skip} but isolate[3]={iso} with SMCEN[3] set"
            if skip and first_set is None:
                first_set = delay
            if first_set is not None and delay >= first_set + 2:
                break
        assert outcomes[0][1] == 0, f"write after the FLR edge left the latch set: {outcomes[:3]}"
        assert first_set is not None, f"no trial left the latch set: {outcomes[-3:]}"
        coincident = clr_skip - skip_up
        assert first_set == coincident, (
            f"latch left set from delay {first_set}, a coincident edge is delay {coincident} "
            f"(write clears skip after {clr_skip} rises, edge sets it after {skip_up})"
        )
        later = [o for o in outcomes if o[0] >= first_set]
        assert all(o[1] == 1 for o in later), f"latch outcome not monotonic: {outcomes}"
        await self._flr_low_and_clear_latch("S6_END")
        self._stamp("S6")
        self._chk(
            "CHK-FLR-LATCH-CLEAR",
            f"ISOLATE_REQ_SMC_REG written 0xffffffff: tb_skip_mem_repair_o read 0 after "
            f"{clr_skip} rises and tb_isolate_req_o[3] read 0 after {clr_iso} rises; FLR edge "
            f"swept against the write "
            f"launch: latch cleared by the write for delays 0..{first_set - 1}, left set from "
            f"delay {first_set} = write-clear latency {clr_skip} - edge-set latency {skip_up}, "
            f"the coincident delay (swept {len(outcomes)} delays)",
        )

        # S7: a software request does not assert skip_mem_repair_o.
        await self.csr_write("ISO_REG_SET3", ISO_REG, BIT3)
        await self._await(self._iso3, 1, "S7_ISO_UP")
        for n in range(_NO_SKIP_RISES):
            await ClockCycles(dut.clk_smc_i, 1)
            self._assert_no_cool_reset("S7")
            skip, iso = self._skip(), self._iso3()
            assert (skip, iso) == (0, 1), f"rise {n + 1}/{_NO_SKIP_RISES}: skip={skip} iso3={iso}"
        self._stamp("S7")
        self._chk(
            "CHK-FLR-SW-NO-SKIP",
            f"ISOLATE_REQ_REG[3] set, no FLR edge: tb_isolate_req_o[3]=1 and "
            f"tb_skip_mem_repair_o=0 on {_NO_SKIP_RISES} of {_NO_SKIP_RISES} consecutive rises",
        )

        await self.csr_restore("ISO_REG_RESTORE", ISO_REG, 0)
        await self.csr_restore("SMCEN_RESTORE", SMCEN_REG, 0)

        assert [s for s, _ in self._stamps] == list(_STEP_IDS), f"steps {self._stamps}"
        times = [t for _, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing {times}"
        assert [c for c, _, _ in self._chk_lines] == list(_CHK_IDS), f"lines {self._chk_lines}"
        assert all(n == _STEP_IDS.index(s) + 1 for _, s, n in self._chk_lines)
        cocotb.log.info(
            "CHK-NONVAC: ordered fence checker lines in step order, step stamps strictly "
            "increasing, each line after its own compare; checker lines %s; stamps %s",
            ",".join(_CHK_IDS),
            ",".join(f"{s}@{t}" for s, t in self._stamps),
        )
