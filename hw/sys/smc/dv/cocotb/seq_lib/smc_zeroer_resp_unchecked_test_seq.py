# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Zeroer jobs whose write responses carry SLVERR, DECERR or a mix.

Sources hw/sys/smc/doc/zeroer.adoc (Outstanding Transaction Management, Status Features).

A 6 KiB region is poisoned and zeroed by an uninjected job that records the
write-address handshakes, burst count and completion interrupt count as the
baseline. Each later job re-poisons the region and has the SYS_OUT responder
answer the first beat of chosen bursts with SLVERR or DECERR. The zeroer
consumes write responses without checking the code, so every job has to finish
with STATUS 0, the baseline burst count and its completion interrupt, and the
bursts that were not errored have to be zeroed.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from cocotb.utils import get_sim_time

from .smc_addr_map import _REPO, reg_field_encode
from .smc_output_fabric_vip_utils import (
    OUTPUT_FABRIC_ADDR,
    output_fabric_pass_all_cfg_seq,
)

_SMC_REG_PY = Path(__file__).resolve().parents[3] / "regs" / "gen" / "py"
if str(_SMC_REG_PY) not in sys.path:
    sys.path.insert(0, str(_SMC_REG_PY))

from smc_reg import (  # noqa: E402
    ZEROER_CTRL_CTRL_STATUS_REG_ADDR,
    ZEROER_CTRL_DEST_ADDR_REG_ADDR,
    ZEROER_CTRL_SIZE_REG_ADDR,
)

ZEROER_DEST_ADDR = ZEROER_CTRL_DEST_ADDR_REG_ADDR
ZEROER_SIZE = ZEROER_CTRL_SIZE_REG_ADDR
ZEROER_CTRL_STATUS = ZEROER_CTRL_CTRL_STATUS_REG_ADDR
_ZEROER_CTRL_H = _REPO / "hw" / "ip" / "zeroer" / "regs" / "gen" / "c" / "zeroer_ctrl.h"
ZEROER_CTRL_STATUS_START = reg_field_encode(_ZEROER_CTRL_H, "ZEROER_CTRL", "CTRL_STATUS", int_en=1)
STATUS_BM = reg_field_encode(_ZEROER_CTRL_H, "ZEROER_CTRL", "CTRL_STATUS", status=1)

RESP_OKAY = 0
RESP_SLVERR = 2
RESP_DECERR = 3
_RESP_NAME = {RESP_OKAY: "OKAY", RESP_SLVERR: "SLVERR", RESP_DECERR: "DECERR"}

_JOB_BYTES = 6 * 1024
_MIXED_JOB_BYTES = 12 * 1024
_BEAT_BYTES = 8
_POISON_BYTE = 0xA5
_MIN_MIXED_BURSTS = 6

# Bounds are liveness ceilings, not checked quantities: expiry FAILS.
_FIRST_AW_CYCLES = 4000
_STATUS_CLEAR_CYCLES = 40000


class _Wire:
    """Passive clk_smc_i sampler of the zeroer's AW handshakes and completion interrupt."""

    def __init__(self) -> None:
        self.aw: list[tuple[int, int]] = []
        self.intp_rises = 0
        self._task = None

    def start(self) -> None:
        self._task = cocotb.start_soon(self._run())

    def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None

    async def _run(self) -> None:
        dut = cocotb.top
        prev_intp = 0
        while True:
            await RisingEdge(dut.clk_smc_i)
            sigs = (dut.tb_zeroer_awvalid, dut.tb_zeroer_awready, dut.tb_zeroer_intp)
            for sig in sigs:
                assert sig.value.is_resolvable, f"{sig._name} is X/Z: {sig.value}"
            valid, ready, intp = (int(sig.value) for sig in sigs)
            if valid and ready:
                addr, length = dut.tb_zeroer_awaddr.value, dut.tb_zeroer_awlen.value
                assert addr.is_resolvable and length.is_resolvable, (
                    f"AW payload is X/Z at a handshake: addr={addr} len={length}"
                )
                self.aw.append((int(addr), int(length)))
            if intp and not prev_intp:
                self.intp_rises += 1
            prev_intp = intp


class smc_zeroer_resp_unchecked_test_seq(output_fabric_pass_all_cfg_seq):
    """Complete multi-burst zeroer jobs under SLVERR, DECERR and mixed B responses."""

    def __init__(self, name: str = "smc_zeroer_resp_unchecked_test_seq") -> None:
        super().__init__(name)
        self.runs = 0
        self._job_bytes = _JOB_BYTES
        self._stamps: list[tuple[str, int]] = []
        self._printed: list[tuple[str, str]] = []

    def _stamp(self, step: str) -> None:
        self._stamps.append((step, int(get_sim_time("ps"))))

    def _chk(self, step: str, chk_id: str, text: str, *args) -> None:
        assert self._stamps and self._stamps[-1][0] == step, (
            f"{chk_id} printed while the last completed step is "
            f"{self._stamps[-1][0] if self._stamps else None}, expected {step}"
        )
        cocotb.log.info(f"{chk_id}: {text}", *args)
        self._printed.append((chk_id, step))

    async def _status(self) -> int:
        word = await self.csr_read("ZEROER_CTRL_STATUS_POLL", ZEROER_CTRL_STATUS, length=8)
        return 1 if word & STATUS_BM else 0

    def _poison(self) -> None:
        poison = bytes([_POISON_BYTE]) * self._job_bytes
        self._responder.write(OUTPUT_FABRIC_ADDR, poison)
        got = self._responder.read(OUTPUT_FABRIC_ADDR, self._job_bytes)
        assert got == poison, f"the {self._job_bytes}-byte region did not take its poison"

    def _nonzero(self, addr: int, length: int) -> int:
        return sum(1 for b in self._responder.read(addr, length) if b)

    async def _run_job(self, label: str, plan: dict[int, int] | None) -> dict:
        """Re-poison, inject `plan` (burst index -> response code), run and observe one job."""
        mon = self.env.output_axi_monitor
        self._poison()
        before = mon.snapshot()
        wire = _Wire()
        wire.start()
        try:
            if plan:
                for index, resp in plan.items():
                    self._responder.inject_error(self._base_aw[index][0], resp, read=False)
            await self.csr_write(
                f"ZEROER_CTRL_STATUS_START_{label}",
                ZEROER_CTRL_STATUS,
                ZEROER_CTRL_STATUS_START,
                length=8,
            )
            for _ in range(_FIRST_AW_CYCLES):
                if wire.aw:
                    break
                await ClockCycles(cocotb.top.clk_smc_i, 1)
            else:
                raise AssertionError(
                    f"{label}: no zeroer AW handshake within {_FIRST_AW_CYCLES} clk_smc_i cycles "
                    f"of the start write; the job never issued a burst"
                )
            for _ in range(_STATUS_CLEAR_CYCLES):
                if await self._status() == 0:
                    break
                await ClockCycles(cocotb.top.clk_smc_i, 1)
            else:
                raise AssertionError(
                    f"{label}: STATUS still 1 {_STATUS_CLEAR_CYCLES} polls after the start write; "
                    f"AW handshakes {len(wire.aw)}, interrupt pulses {wire.intp_rises}, "
                    f"responses injected {plan}"
                )
            status_first = 0
            status_word = await self.csr_read(
                f"ZEROER_CTRL_STATUS_SECOND_{label}", ZEROER_CTRL_STATUS, length=8
            )
        finally:
            wire.stop()
        after = mon.snapshot()
        obs = {
            "label": label,
            "status": status_first,
            "status2": 1 if status_word & STATUS_BM else 0,
            "other_bits": status_word & ~STATUS_BM,
            "bursts": len(wire.aw),
            "aw": list(wire.aw),
            "intp": wire.intp_rises,
            "slverr_seen": after["b_slverr"] - before["b_slverr"],
            "decerr_seen": after["b_decerr"] - before["b_decerr"],
        }
        self._responder.clear_errors()
        self.runs += 1
        return obs

    def _check_tally(self, obs: dict, plan: dict[int, int]) -> None:
        want_s = sum(1 for r in plan.values() if r == RESP_SLVERR)
        want_d = sum(1 for r in plan.values() if r == RESP_DECERR)
        assert (obs["slverr_seen"], obs["decerr_seen"]) == (want_s, want_d), (
            f"{obs['label']}: the SYS_OUT monitor counted {obs['slverr_seen']} SLVERR and "
            f"{obs['decerr_seen']} DECERR B beats, the plan injected {want_s} and {want_d}"
        )

    def _burst_range(self, aw: tuple[int, int]) -> tuple[int, int]:
        return aw[0], (aw[1] + 1) * _BEAT_BYTES

    def _check_zeroed(self, obs: dict, errored: set[int]) -> tuple[int, int]:
        """Return (bytes compared in non-errored bursts, nonzero bytes left in errored ones)."""
        compared = 0
        left = 0
        for index, aw in enumerate(self._base_aw):
            addr, length = self._burst_range(aw)
            nonzero = self._nonzero(addr, length)
            if index in errored:
                left += nonzero
            else:
                assert nonzero == 0, (
                    f"{obs['label']}: non-errored burst {index} @ 0x{addr:08x} len {length} still "
                    f"holds {nonzero} non-zero byte(s)"
                )
                compared += length
        return compared, left

    def _check_complete(self, obs: dict) -> None:
        assert obs["status"] == 0 and obs["status2"] == 0, (
            f"{obs['label']}: STATUS reads {obs['status']} then {obs['status2']} after the last "
            f"response"
        )
        assert obs["bursts"] == self._base_bursts, (
            f"{obs['label']}: {obs['bursts']} AW handshakes, baseline {self._base_bursts}"
        )
        assert obs["aw"] == self._base_aw, (
            f"{obs['label']}: AW (addr, len) {obs['aw']} differ from the baseline {self._base_aw}"
        )

    async def _baseline(self, job_bytes: int) -> dict:
        """Program `job_bytes`, run an uninjected job and keep it as the reference."""
        self._job_bytes = job_bytes
        await self.csr_write("ZEROER_SIZE_BASELINE", ZEROER_SIZE, job_bytes, length=8)
        await self.csr_read("ZEROER_SIZE_BASELINE_RB", ZEROER_SIZE, expected=job_bytes, length=8)
        self._base_aw = [(OUTPUT_FABRIC_ADDR, 0)]
        base = await self._run_job(f"BASELINE_{job_bytes}", None)
        self._base_aw = base["aw"]
        self._base_bursts = base["bursts"]
        assert self._base_bursts >= 2, f"baseline issued {self._base_bursts} burst(s)"
        assert base["intp"] == 1, f"baseline raised {base['intp']} interrupt pulse(s), expected 1"
        assert base["status"] == 0 and base["status2"] == 0, "baseline STATUS did not read 0"
        assert base["other_bits"] == ZEROER_CTRL_STATUS_START, (
            f"baseline CTRL_STATUS reads 0x{base['other_bits']:x} outside STATUS"
        )
        covered = sum(self._burst_range(aw)[1] for aw in self._base_aw)
        assert covered == job_bytes, f"baseline bursts cover {covered} of {job_bytes} bytes"
        for aw in self._base_aw:
            assert OUTPUT_FABRIC_ADDR <= aw[0] < OUTPUT_FABRIC_ADDR + job_bytes, (
                f"baseline AW address 0x{aw[0]:x} outside the poisoned region"
            )
        base_cmp, _ = self._check_zeroed(base, set())
        assert base_cmp == job_bytes, f"baseline zeroed {base_cmp} of {job_bytes} bytes"
        return base

    async def body(self) -> None:
        dut = cocotb.top
        for name in (
            "tb_zeroer_awvalid",
            "tb_zeroer_awready",
            "tb_zeroer_awaddr",
            "tb_zeroer_awlen",
            "tb_zeroer_intp",
        ):
            assert hasattr(dut, name), f"{name} missing from the smc_uvm_top port surface"
        self._responder = self.cfg.sys_out_mem
        assert self._responder is not None, "SYS_OUT responder not bound"
        mon = self.env.output_axi_monitor
        mon.allow_slverr = True
        mon.allow_decerr = True

        # S1: setup and baseline.
        await self.program_inbound_pass_all()
        await self.program_outbound_pass_all()
        await self.csr_write("ZEROER_DEST_ADDR", ZEROER_DEST_ADDR, OUTPUT_FABRIC_ADDR, length=8)
        await self.csr_read(
            "ZEROER_DEST_ADDR_RB", ZEROER_DEST_ADDR, expected=OUTPUT_FABRIC_ADDR, length=8
        )
        idle = await self._status()
        assert idle == 0, f"STATUS reads {idle} with the zeroer idle before any job"
        base = await self._baseline(_JOB_BYTES)
        self._stamp("S1")
        n = self._base_bursts

        # S2: SLVERR on the first, the middle and the last burst.
        s2 = []
        for tag, index in (("FIRST", 0), ("MIDDLE", n // 2), ("LAST", n - 1)):
            plan = {index: RESP_SLVERR}
            obs = await self._run_job(f"SLVERR_{tag}", plan)
            self._check_tally(obs, plan)
            self._check_complete(obs)
            assert obs["other_bits"] == ZEROER_CTRL_STATUS_START, (
                f"{obs['label']}: CTRL_STATUS shows 0x{obs['other_bits']:x} besides STATUS, "
                f"expected only INT_EN (0x{ZEROER_CTRL_STATUS_START:x})"
            )
            compared, left = self._check_zeroed(obs, {index})
            s2.append(
                f"{tag}(burst {index}): STATUS {obs['status']}, bursts {obs['bursts']}, "
                f"interrupts {obs['intp']}, {compared} non-errored bytes zero, "
                f"{left} non-zero bytes left in the errored burst"
            )
        self._stamp("S2")
        self._chk(
            "S2",
            "CHK-ZEROER-SLVERR-COMPLETES",
            "SLVERR on one burst of a %d-burst %d-byte job (baseline %d bursts, %d interrupt): "
            "%s; CTRL_STATUS held only INT_EN and STATUS",
            n,
            _JOB_BYTES,
            self._base_bursts,
            base["intp"],
            "; ".join(s2),
        )

        # S3: DECERR on every burst.
        plan = dict.fromkeys(range(n), RESP_DECERR)
        obs = await self._run_job("DECERR_ALL", plan)
        self._check_tally(obs, plan)
        self._check_complete(obs)
        assert obs["intp"] == base["intp"], (
            f"DECERR_ALL: {obs['intp']} interrupt pulse(s), baseline {base['intp']}"
        )
        _compared, left = self._check_zeroed(obs, set(plan))
        self._stamp("S3")
        self._chk(
            "S3",
            "CHK-ZEROER-DECERR-ALL-COMPLETES",
            "DECERR on all %d bursts: STATUS %d, bursts %d (baseline %d), interrupt pulses %d "
            "(baseline %d), %d non-zero bytes left in the errored bursts",
            n,
            obs["status"],
            obs["bursts"],
            self._base_bursts,
            obs["intp"],
            base["intp"],
            left,
        )

        # S4: OKAY, SLVERR and DECERR alternating, on a job large enough for six bursts.
        base4 = await self._baseline(_MIXED_JOB_BYTES)
        n = self._base_bursts
        assert n >= _MIN_MIXED_BURSTS, (
            f"the {_MIXED_JOB_BYTES}-byte baseline job issued {n} burst(s); the mixed-response "
            f"step needs at least {_MIN_MIXED_BURSTS}"
        )
        codes = (RESP_OKAY, RESP_SLVERR, RESP_DECERR)
        mixed = {i: codes[i % 3] for i in range(n)}
        plan = {i: r for i, r in mixed.items() if r != RESP_OKAY}
        obs = await self._run_job("MIXED", plan)
        self._check_tally(obs, plan)
        self._check_complete(obs)
        _compared, left = self._check_zeroed(obs, set(plan))
        again = await self._status()
        assert again == 0, f"MIXED: a further STATUS read reads {again}"
        self._stamp("S4")
        self._chk(
            "S4",
            "CHK-ZEROER-MIXED-RESP",
            "responses %s across %d bursts of a %d-byte job: STATUS %d then %d then %d, bursts %d "
            "(baseline %d), interrupt pulses %d (baseline %d), %d non-zero bytes left in the "
            "errored bursts",
            "/".join(_RESP_NAME[mixed[i]] for i in range(n)),
            n,
            _MIXED_JOB_BYTES,
            obs["status"],
            obs["status2"],
            again,
            obs["bursts"],
            self._base_bursts,
            obs["intp"],
            base4["intp"],
            left,
        )

        await self.csr_write("ZEROER_SIZE_CLEAR", ZEROER_SIZE, 0, length=8)
        await self.csr_write("ZEROER_DEST_ADDR_CLEAR", ZEROER_DEST_ADDR, 0, length=8)
        await self.csr_read("ZEROER_SIZE_CLEAR_RB", ZEROER_SIZE, expected=0, length=8)
        self._nonvac()

    def _nonvac(self) -> None:
        steps = [s for s, _t in self._stamps]
        assert steps == ["S1", "S2", "S3", "S4"], f"step stamps {steps} not in the expected order"
        times = [t for _s, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:], strict=False)), (
            f"step stamps {times} are not strictly increasing"
        )
        ids = [c for c, _s in self._printed]
        assert ids == [
            "CHK-ZEROER-SLVERR-COMPLETES",
            "CHK-ZEROER-DECERR-ALL-COMPLETES",
            "CHK-ZEROER-MIXED-RESP",
        ], f"checker lines {ids} not in step order"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence S1<S2<S3<S4 with checker lines printed in step order "
            "after their own compares; checker lines %s; stamps %s ps",
            ",".join(ids),
            ",".join(str(t) for t in times),
        )
