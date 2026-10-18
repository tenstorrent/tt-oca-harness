# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""KM DRBG sampler: timeouts, counters, prefetch, write refusals, TRNG reset and stream errors.

no_cpu (``lsu_stub_all_live``) / ``+skip_fuse_sense`` / ``+esrc_noise_force`` /
``+km_rom_hex=km_rom_poke.parhex``. RAND-REP: the drawn timeout T, the order of
the timeout legs, the COUNT_GOOD saturation leg (one seed in three) and the
delay before the idle withdrawal.

Vehicle. The POKE KM image (``tests/km_fw/km_rom_poke.S``) runs the KM bus
operations that the host posts and reports what the DUT returned in KM SRAM
words 0 to 97 (``km_sram_probe_o``). Each reporting operation clears
IRQ_STATUS.AXI_SLVERR and AXI_DECERR before its access and reports them after
it as ``slv`` and ``dec``. Every value a check compares is a POKE readback of
the DUT or a sample of the KM entropy stream taps (``km_entropy_tvalid_o``,
``km_entropy_tready_o``). The stream is stalled (the entropy chain held at its
reset) until the TRNG reset leg and live after it. The withdrawals of the
stream-error leg come from the error inject ``HK-STRM`` at the sampler sink
(``km_strm_wd_*``, ``docs/SEP_TB_ARCH.adoc``).

Specification. ``hw/ip/key_manager/doc/architecture.adoc``, sections "DRBG
Sampler", "Reads, prefetch and register access", "Errors and reset" and table
"Key Manager DRBG sampler states"; ``hw/ip/key_manager/regs/gen/adoc/km_drbg_sampler.adoc``,
sections "DRBG Sampler", "CFG", "STATUS", "PREFETCH_DATA";
``hw/sys/sep/doc/reset_controller.adoc``, section "Resetting the TRNG". Field
masks and resets come from the generated RDL headers
(``sep_km_drbg_sampler_rand_plan.py``).

Checkers:
  CHK-SMP-TO      a stalled active DATA read at T = 1, 2, 3 and 65535 ends in a
                  timeout: SLVERR, data 0, TIMEOUT_ERR 1, STREAM_ERR 0,
                  COUNT_BAD + 1, DRBG_ERR 1, DRBG_READY 0; the CFG readback is
                  the written value; a write of 0 keeps TIMEOUT_ERR and a write
                  of 1 clears it. The drawn T and T = 256 are controls. Control:
                  the fed reads at T = 0 and 65535 complete OKAY with COUNT_GOOD
                  + 1 each.
  CHK-SMP-CNT     COUNT_BAD saturates at 0xFF and COUNT_GOOD at 0xFFFF (when the
                  seed draws the loop) and stay there after two more reads; a
                  write of 0 keeps a counter, a non-zero write clears it from a
                  low value and from saturation. Control: each counter is
                  non-zero before each clear.
  CHK-SMP-PRE     with a stalled stream and PREFETCH 1 no word is held and no
                  timeout sets over 1024 clocks; with the live stream a word is
                  held, PREFETCH_DATA reads it three times, DATA returns it
                  without a COUNT_GOOD count, and a handshake refills it;
                  PREFETCH 0 clears PREFETCHED and PREFETCH_DATA
                  (architecture.adoc:812-816). Controls: a stalled active read
                  at timeout 8 times out; each fed read pair takes a handshake;
                  DRBG_READY reads 1 while the held word blocks the stream.
  CHK-SMP-WR      writes to DATA and PREFETCH_DATA answer SLVERR and leave STATUS
                  and PREFETCH_DATA unchanged, on the stalled stream and again
                  with a prefetched word held (a known PREFETCH_DATA value).
                  Control: AXI_SLVERR reads 0 after each clear before the write.
  CHK-SMP-TRNG    the first DATA read after a TRNG reset with the KM held in
                  software reset completes OKAY with STREAM_ERR 0, COUNT_BAD 0
                  and DRBG_ERR 0. The pulse is seen on the reset-sequencer
                  probes: the TRNG gated reset is low for at least one clock,
                  every such clock has the three TRNG host paths isolated and
                  the KM warm reset low (reset_controller.adoc:190-194, 211-212),
                  and it is high before and after the pulse. Control: before the
                  pulse the producer offers a beat (TVALID 1) that the held
                  sampler does not take (TREADY 0).
  CHK-SMP-STRM    a withdrawal sets STREAM_ERR and DRBG_ERR with no read active
                  (COUNT_BAD + 1) and in the first active cycle of a read at
                  timeout 256, 1 and 2 (SLVERR, data 0, COUNT_BAD + 1 or more);
                  a write of 0 keeps STREAM_ERR and a write of 1 clears it.
                  Control: the stalled timeouts and the first read after the
                  TRNG reset leave STREAM_ERR 0.
  CHK-NONVAC      at least one true withdrawal was graded and every control of a
                  "no effect" check above was seen.

Blocked (``HK-STRM-PAT`` is not in the bench): CHK-SMP-PACK, CHK-SMP-TO-ASM and
CHK-SMP-STRM-CTRL log ``OBS-BLOCKED`` and grade nothing.

Log only: ``OBS-SMP-TO-CYCLES`` (the TREADY-high clocks of each timeout leg),
``OBS-SMP-STRM`` (TIMEOUT_ERR and the exact COUNT_BAD delta of a withdrawal in
the first active cycle), ``OBS-RACE-MISSED`` (a first-active-cycle pulse that
met TREADY high is a handshake and is not graded), ``OBS-SMP-NEXT-HELD``
(whether the refilled word differs), ``OBS-SMP-LOOP`` (the read-loop data
summary).
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge
from env import sep_km_poke as kp
from env.sep_axi_agent import SepAxiItem, SepAxiOp
from env.sep_chk_log import SepChkLog
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_reg_meta import EDN, ENTROPY_SOURCE, sym
from env.sep_seeded_rng import SepSeededRng
from km import sep_km_drbg_sampler_rand_plan as pl
from pyuvm import uvm_sequence
from sep_base_test import sep_base_test
from seq_lib.sep_esrc_bringup_seq import (
    SepEntropyCfg,
    SepEsrcConfigSeq,
    SepEsrcEnableGeneratorsSeq,
)
from seq_lib.sep_km_drbg_sampler_seq import SepKmTreadyMonitor
from seq_lib.sep_km_poke_seq import SepKmPoke
from seq_lib.sep_sw_reset_seq import SW_RESET_N_BIT, SepSwReset

TEST = "sep_km_drbg_sampler_rand_test"

# Bounds (clk_i cycles or KM loads). A timeout of a bound fails the leaf; it is
# not a verdict about the contract.
_SEP_RESET_BOUND = 20_000
_TVALID_BOUND = 400_000
_FIRE_BOUND = 2_000
_PREFETCH_POLL_LOADS = 4096
_BAD_LOOP_CYCLES = 4_000_000
_GOOD_LOOP_CYCLES = 60_000_000
_STALLED_LIST_CYCLES = 2_000_000

_KM_BIT = 1 << SW_RESET_N_BIT["km"]
# trng_axi_isolated_probe_o: the EDN, CSRNG and entropy-source host paths.
_TRNG_ISO_ALL = 0b111
_TRNG_RELEASE_BOUND = 2_000
_SW_ALL = sum(1 << b for b in SW_RESET_N_BIT.values())

# Stimulus words of the write-refusal leg.
_DATA_WR_WORD = 0xA5A5_5A5A
_PDATA_WR_WORD = 0x5A5A_A5A5

# EDN in auto request mode only (BOOT_REQ_MODE false). Boot mode takes
# precedence when both modes are set and serves one boot Generate, 4095 blocks of
# 128 bits, and the COUNT_GOOD saturation loop reads more words than that. In auto
# mode EDN sends GENERATE_CMD again after each Generate and a Reseed after
# MAX_NUM_REQS_BETWEEN_RESEEDS Generates, once software sends the first
# instantiate through SW_CMD_REQ (edn.adoc, AUTO_REQ_MODE). Each Generate is
# 4095 blocks, so the legs other than the saturation loop read inside the first one.
_EDN_GLEN = 4095
_EDN_RESEED_EVERY = 1
_EDN_CMD_BOUND = 20_000
_EDN_CTRL = sym("EDN_CTRL_REG_ADDR")
_EDN_SW_CMD_REQ = sym("EDN_SW_CMD_REQ_REG_ADDR")
_EDN_SW_CMD_STS = sym("EDN_SW_CMD_STS_REG_ADDR")
_ESRC_FIPS_LOCK = sym("ENTROPY_SOURCE_FIPS_LOCK_REG_ADDR")
_EDN_STS = EDN.fields("SW_CMD_STS")
_EDN_RDY = _EDN_STS["CMD_REG_RDY"]["bm"] | _EDN_STS["CMD_RDY"]["bm"]
_EDN_ACK = _EDN_STS["CMD_ACK"]["bm"]
_EDN_CMD_STS = _EDN_STS["CMD_STS"]
_MUBI4_FALSE = EDN.fields("CTRL")["EDN_ENABLE"]["reset"]
_MUBI4_TRUE = (~_MUBI4_FALSE) & ((1 << EDN.fields("CTRL")["EDN_ENABLE"]["bw"]) - 1)
_EDN_CTRL_AUTO_ONLY = EDN.value(
    "CTRL",
    EDN_ENABLE=_MUBI4_TRUE,
    BOOT_REQ_MODE=_MUBI4_FALSE,
    AUTO_REQ_MODE=_MUBI4_TRUE,
    CMD_FIFO_RST=_MUBI4_FALSE,
)
_CMD_INSTANTIATE = EDN.reset("BOOT_INS_CMD")


class _EdnAutoOnlySeq(uvm_sequence):
    """Lock ESRC, enable EDN in auto request mode only and send the instantiate."""

    async def _access(self, op: SepAxiOp, addr: int, data: int = 0) -> int:
        item = SepAxiItem(f"edn_auto_0x{addr:08x}")
        item.op = op
        item.addr = addr
        item.length = 4
        item.wdata = data
        await self.start_item(item)
        await self.finish_item(item)
        return item.rdata if op == SepAxiOp.READ else 0

    async def _poll(self, mask: int, what: str) -> int:
        for _ in range(_EDN_CMD_BOUND):
            sts = await self._access(SepAxiOp.READ, _EDN_SW_CMD_STS)
            if sts & mask == mask:
                return sts
        raise AssertionError(f"EDN SW_CMD_STS showed no {what} within {_EDN_CMD_BOUND} reads")

    async def body(self) -> None:
        await self._access(
            SepAxiOp.WRITE, _ESRC_FIPS_LOCK, ENTROPY_SOURCE.value("FIPS_LOCK", LOCK=1)
        )
        await self._access(SepAxiOp.WRITE, _EDN_CTRL, _EDN_CTRL_AUTO_ONLY)
        await self._poll(_EDN_RDY, "CMD_REG_RDY and CMD_RDY")
        await self._access(SepAxiOp.WRITE, _EDN_SW_CMD_REQ, _CMD_INSTANTIATE)
        sts = await self._poll(_EDN_ACK, "CMD_ACK")
        code = (sts & _EDN_CMD_STS["bm"]) >> _EDN_CMD_STS["bp"]
        if code:
            raise AssertionError(f"EDN instantiate acknowledged with CMD_STS={code}")


_REQUIRED = (
    "CHK-SMP-TO",
    "CHK-SMP-CNT",
    "CHK-SMP-PRE",
    "CHK-SMP-WR",
    "CHK-SMP-TRNG",
    "CHK-SMP-STRM",
    "CHK-NONVAC",
)


def _h(v: int) -> str:
    return f"0x{v:08x}"


def _clear_ops() -> list[kp.PokeOp]:
    """Write 1 to the sticky STATUS bits and to IRQ_STATUS.DRBG_ERR (counters untouched)."""
    return [kp.wr(pl.A_STATUS, pl.ST_STICKY), kp.wr(pl.A_IRQ_STATUS, pl.IRQ_DRBG_ERR)]


@pyuvm.test()
class sep_km_drbg_sampler_rand_test(sep_base_test):
    """DRBG sampler timeouts, counters, prefetch, write refusals, TRNG reset and withdrawals."""

    required_evidence = _REQUIRED

    # --- transport ---------------------------------------------------------------

    async def _run(self, ops, *, x_ok=(), **kw) -> list[kp.PokeResult]:
        """Run ``ops``. An unknown bit fails the leaf, except in the op indices ``x_ok``."""
        res = await self.poke.run(ops, allow_unknown=True, **kw)
        bad = [r for r in res if not r.known and r.index not in x_ok]
        if bad:
            raise AssertionError(
                "POKE result with an unknown bit: "
                + ", ".join(f"op {r.index} ({r.op.name})" for r in bad)
            )
        return res

    @staticmethod
    def _acc(res: list[kp.PokeResult], err: set[int] = frozenset()) -> list[str]:
        """Response faults: an op in ``err`` must answer SLVERR (slv 1, dec 0); every
        other reporting op OKAY (slv 0, dec 0). Each needs a clean clear before it."""
        out = []
        for r in res:
            if not r.op.reports:
                continue
            want = 1 if r.index in err else 0
            if r.slv != want or r.dec or not r.clean:
                out.append(f"op{r.index}:{r.op.name}:slv={r.slv},dec={r.dec},clean={int(r.clean)}")
        return out

    def _status(self, v: int) -> int:
        self.rsvd["STATUS"] |= v & ~pl.STATUS_FIELDS & pl.WORD_MASK
        return v & pl.STATUS_FIELDS

    def _irq(self, v: int) -> int:
        self.rsvd["IRQ_STATUS"] |= v & ~pl.IRQ_FIELDS & pl.WORD_MASK
        return v & pl.IRQ_FIELDS

    def _gate(self, on: bool) -> None:
        if on:
            open_graded_window(TEST, self.logger)
        else:
            close_graded_window(self.logger)

    def _hs_between(self, c0: int, c1: int) -> int:
        """Handshakes in the TREADY runs that start after cycle ``c0`` and by ``c1``."""
        return sum(hs for start, _, hs in self.mon.runs if c0 < start <= c1)

    async def _mark(self, _k: int) -> None:
        """A sync op: keep the TREADY monitor cycle."""
        self.marks.append(self.mon.cycle)
        return None

    async def _wait_sep_reset_n(self) -> None:
        for _ in range(_SEP_RESET_BOUND):
            await RisingEdge(cocotb.top.clk_i)
            if self.rd(cocotb.top.dbg_sep_reset_n_o, allow_unknown=True):
                return
        raise AssertionError(f"dbg_sep_reset_n_o did not read 1 within {_SEP_RESET_BOUND} clocks")

    async def _wait_tvalid(self, bound: int = _TVALID_BOUND) -> tuple[int, int] | None:
        """Wait (bounded) for ``km_entropy_tvalid_o`` = 1; return (tvalid, tready) of that clock."""
        dut = cocotb.top
        for _ in range(bound):
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            if self.rd(dut.km_entropy_tvalid_o, allow_unknown=True):
                return 1, self.rd(dut.km_entropy_tready_o, allow_unknown=True)
        return None

    async def _entropy_init(self, *, reset_trng: bool, what: str) -> None:
        """The entropy initialization: ESRC, CSRNG and EDN programming, the bounded
        startup poll for the first seed, then EDN enable."""
        await self.assert_noise_force_active()
        cfg = self.entropy_cfg
        await self.start_seq(
            SepEsrcConfigSeq(f"esrc_config_{what}", cfg=cfg, reset_trng=reset_trng)
        )
        await self.start_seq(SepEsrcEnableGeneratorsSeq(f"esrc_gens_{what}"))
        if not await self.wait_seed_ready():
            await self.report_entropy_stall()
            raise AssertionError(f"ESRC produced no seed in the {what} entropy initialization")
        await self.start_seq(_EdnAutoOnlySeq(f"edn_enable_{what}"))

    async def _watch_trng_reset(self) -> None:
        """Count the clocks with the TRNG gated reset low until ``self._trng_watch_stop``.

        In each such clock the three TRNG host paths must read isolated and the
        KM warm reset low. An X or Z probe raises.
        """
        dut = cocotb.top
        w = self.trng_watch
        while not self._trng_watch_stop:
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            if self.rd(dut.trng_gated_rst_n_probe_o) == 0:
                w["rst_clks"] += 1
                if self.rd(dut.trng_axi_isolated_probe_o) != _TRNG_ISO_ALL:
                    w["not_isolated"] += 1
                if self.rd(dut.km_gated_rst_n_probe_o) != 0:
                    w["km_not_held"] += 1

    # --- HK-STRM ------------------------------------------------------------------

    def _strm(self, arm: int, mode: int = 0) -> None:
        dut = cocotb.top
        dut.km_strm_wd_mode_i.value = mode
        dut.km_strm_wd_arm_i.value = arm

    async def _strm_idle_pulse(self) -> tuple[int, int]:
        """Case a: one withdrawal with no read active. Returns (fired, tready)."""
        dut = cocotb.top
        tready_first = self.rd(dut.km_entropy_tready_o, allow_unknown=True)
        await ClockCycles(dut.clk_i, self.plan.pulse_delay + 1)
        self._strm(1, 0)
        fired = 0
        for _ in range(_FIRE_BOUND):
            await RisingEdge(dut.clk_i)
            if self.rd(dut.km_strm_wd_fired_o, allow_unknown=True):
                fired = 1
                break
        await ClockCycles(dut.clk_i, 4)
        tready = self.rd(dut.km_strm_wd_tready_o, allow_unknown=True)
        self._strm(0)
        await ClockCycles(dut.clk_i, 2)
        self.logger.info(
            "LOG HK-STRM case=a tready_first=%d delay=%d fired=%d tready_at_pulse=%d",
            tready_first,
            self.plan.pulse_delay,
            fired,
            tready,
        )
        return fired, tready

    # --- scenario ----------------------------------------------------------------

    async def run_scenario(self) -> None:
        seed = self.random_seed()
        self.logger.info("SEED seed=%d", seed)
        self.rng = SepSeededRng(seed)
        self.plan = pl.draw_plan(self.rng, seed)
        for name, value in self.plan.draws:
            self.logger.info("DRAW %s=%s", name, value)
        self.chk = SepChkLog(self, TEST, seed)
        self.rsvd = {"STATUS": 0, "IRQ_STATUS": 0}
        self.controls: dict[str, bool] = {}
        self.marks: list[int] = []
        self.true_withdrawals = 0
        self.noise = None
        self.entropy_cfg = SepEntropyCfg(glen=_EDN_GLEN, reseed_interval=_EDN_RESEED_EVERY)

        # Step 1: cold reset, stalled stream (no entropy initialization), KM boot.
        self._gate(False)
        await self.bring_up_no_cpu()
        await self._wait_sep_reset_n()
        self.swrst = SepSwReset(self)
        self.poke = SepKmPoke(self)
        self.mon = SepKmTreadyMonitor(self)
        self.mon.start()
        await self.swrst.release("km")
        await self.poke.wait_boot()
        self._gate(True)

        await self._step_reset_values()
        await self._step_timeouts()
        await self._step_writes()
        await self._step_stalled_prefetch()
        await self._step_bad_counter()
        await self._step_trng_reset()
        await self._step_first_read()
        await self._step_fed_twin()
        await self._step_good_clear()
        await self._step_live_prefetch()
        await self._step_good_saturation()
        self.chk.blocked("SMP-PACK", "HK-STRM-PAT")
        self.chk.blocked("SMP-TO-ASM", "HK-STRM-PAT")
        await self._step_stream_errors()
        self.chk.blocked("SMP-STRM-CTRL", "HK-STRM-PAT")
        await self._step_end()
        self.chk.finish()

    # Step 2.
    async def _step_reset_values(self) -> None:
        res = await self._run([kp.rd(pl.A_CFG), kp.rd(pl.A_STATUS), kp.rd(pl.A_IRQ_STATUS)])
        st = self._status(res[1].value)
        self.chk.ctrl(
            "SMP-RESET-VALUES",
            res[0].value == pl.CFG_RESET and st == pl.STATUS_RESET and not self._acc(res),
            cfg=_h(res[0].value),
            cfg_reset=_h(pl.CFG_RESET),
            status=_h(st),
            status_reset=_h(pl.STATUS_RESET),
        )
        self.logger.info("LOG reset irq_status=%s", _h(self._irq(res[2].value)))

    # Step 3.
    async def _step_timeouts(self) -> None:
        self.stalled_stream_err = []
        self.stalled_bad_delta = []
        for t in self.plan.t_order:
            ops = [
                kp.wr(pl.A_CFG, pl.cfg(t, 0)),
                kp.rd(pl.A_CFG),
                kp.wr(pl.A_IRQ_STATUS, pl.IRQ_DRBG_ERR),
                kp.wr(pl.A_STATUS, pl.ST_TIMEOUT_ERR),
                kp.rd(pl.A_IRQ_STATUS),
                kp.rd(pl.A_STATUS),
                kp.rd(pl.A_DATA),
                kp.rd(pl.A_STATUS),
                kp.rd(pl.A_IRQ_STATUS),
                kp.wr(pl.A_STATUS, 0),
                kp.rd(pl.A_STATUS),
                kp.wr(pl.A_STATUS, pl.ST_TIMEOUT_ERR),
                kp.rd(pl.A_STATUS),
                kp.wr(pl.A_IRQ_STATUS, pl.IRQ_DRBG_ERR),
            ]
            n0 = len(self.mon.runs)
            res = await self._run(ops, timeout_cycles=_STALLED_LIST_CYCLES)
            runs = self.mon.runs[n0:]
            irq_pre, st_pre = self._irq(res[4].value), self._status(res[5].value)
            st, irq = self._status(res[7].value), self._irq(res[8].value)
            st_w0, st_w1 = self._status(res[10].value), self._status(res[12].value)
            self.chk.ctrl(
                "SMP-TO-CLEAR",
                not irq_pre & pl.IRQ_DRBG_ERR and not st_pre & pl.ST_TIMEOUT_ERR,
                t=t,
                drbg_err=int(bool(irq_pre & pl.IRQ_DRBG_ERR)),
                timeout_err=pl.st(st_pre, "TIMEOUT_ERR"),
            )
            delta = pl.st(st, "COUNT_BAD") - pl.st(st_pre, "COUNT_BAD")
            self.stalled_stream_err.append(pl.st(st, "STREAM_ERR"))
            self.stalled_bad_delta.append(delta)
            acc = self._acc(res, {6})
            fields = dict(
                t=t,
                cfg_rd=_h(res[1].value),
                slv=res[6].slv,
                dec=res[6].dec,
                data=_h(res[6].value),
                status_lo4=f"0x{st & pl.ST_FLAGS:x}",
                count_bad_delta=delta,
                drbg_err=int(bool(irq & pl.IRQ_DRBG_ERR)),
                drbg_ready=pl.st(st, "DRBG_READY"),
                timeout_err_w0=pl.st(st_w0, "TIMEOUT_ERR"),
                timeout_err_w1c=pl.st(st_w1, "TIMEOUT_ERR"),
                bad_responses=",".join(acc) or "none",
            )
            cond = (
                res[1].value == pl.cfg(t, 0)
                and res[6].value == 0
                and st & pl.ST_FLAGS == pl.ST_TIMEOUT_ERR
                and delta == 1
                and irq & pl.IRQ_DRBG_ERR
                and pl.st(st_w0, "TIMEOUT_ERR") == 1
                and pl.st(st_w1, "TIMEOUT_ERR") == 0
                and not acc
            )
            if t in pl.GRADED_STALLED_T:
                self.chk.ok("SMP-TO", cond, **fields)
            else:
                self.chk.ctrl("SMP-TO-OPEN", cond, control=1, **fields)
            self.chk.obs(
                "SMP-TO-CYCLES",
                t=t,
                tready_runs=len(runs),
                tready_clks=[r[1] for r in runs],
                handshakes=sum(r[2] for r in runs),
            )

    # Step 4.
    async def _step_writes(self) -> None:
        ops = [
            kp.wr(pl.A_IRQ_STATUS, pl.IRQ_SLVERR, raw=True),
            kp.rd(pl.A_IRQ_STATUS, raw=True),
            kp.rd(pl.A_STATUS),
            kp.rd(pl.A_PDATA),
            kp.wr(pl.A_DATA, _DATA_WR_WORD),
            kp.rd(pl.A_IRQ_STATUS, raw=True),
            kp.rd(pl.A_STATUS),
            kp.wr(pl.A_IRQ_STATUS, pl.IRQ_SLVERR, raw=True),
            kp.rd(pl.A_IRQ_STATUS, raw=True),
            kp.wr(pl.A_PDATA, _PDATA_WR_WORD),
            kp.rd(pl.A_IRQ_STATUS, raw=True),
            kp.rd(pl.A_PDATA),
            kp.rd(pl.A_STATUS),
            kp.wr(pl.A_IRQ_STATUS, pl.IRQ_SLVERR, raw=True),
        ]
        res = await self._run(ops, x_ok={3, 11})
        clear = [int(bool(self._irq(res[i].value) & pl.IRQ_SLVERR)) for i in (1, 8)]
        after = [int(bool(self._irq(res[i].value) & pl.IRQ_SLVERR)) for i in (5, 10)]
        sts = [self._status(res[i].value) for i in (2, 6, 12)]
        # PREFETCH_DATA has no reset value. Both reads unknown: no compare here
        # (the held-word leg grades the same claim on a known value). One
        # unknown and one known, or two different known values: not kept.
        pdata_known = res[3].known and res[11].known
        pdata_kept = (
            res[3].value == res[11].value
            if pdata_known
            else (not res[3].known and not res[11].known)
        )
        self.chk.ctrl("SMP-WR-CLEAR", clear == [0, 0], clear_before=clear)
        acc = self._acc(res, {4, 9})
        self.chk.ok(
            "SMP-WR",
            res[4].slv == 1
            and res[9].slv == 1
            and after == [1, 1]
            and sts[0] == sts[1] == sts[2]
            and pdata_kept
            and not acc,
            data_wr_slv=res[4].slv,
            pdata_wr_slv=res[9].slv,
            axi_slverr=after,
            clear_before=clear,
            status=[_h(s) for s in sts],
            pdata=[_h(res[3].value), _h(res[11].value)],
            pdata_known=[int(res[3].known), int(res[11].known)],
            point="stalled",
            bad_responses=",".join(acc) or "none",
        )
        self.status_kept_after_wr = sts[0] == sts[2]

    # Step 5.
    async def _step_stalled_prefetch(self) -> None:
        t = pl.PREFETCH_T
        ops = [
            kp.wr(pl.A_CFG, pl.cfg(t, 0)),
            *_clear_ops(),
            kp.rd(pl.A_DATA),
            kp.rd(pl.A_STATUS),
            kp.rd(pl.A_IRQ_STATUS),
            kp.wr(pl.A_STATUS, pl.ST_TIMEOUT_ERR),
            kp.wr(pl.A_IRQ_STATUS, pl.IRQ_DRBG_ERR),
            kp.rd(pl.A_STATUS),
            kp.rd(pl.A_IRQ_STATUS),
            kp.wr(pl.A_CFG, pl.cfg(t, 1)),
            kp.rd(pl.A_STATUS),
            kp.sync(),
            kp.rd(pl.A_STATUS),
            kp.wr(pl.A_CFG, pl.cfg(t, 0)),
        ]

        async def window(_k: int) -> None:
            c0 = self.mon.cycle
            await ClockCycles(cocotb.top.clk_i, pl.PREFETCH_WINDOW_CLKS)
            self.window_cycles = self.mon.cycle - c0
            return None

        n0 = len(self.mon.runs)
        res = await self._run(ops, on_sync=window)
        st_to, irq_to = self._status(res[4].value), self._irq(res[5].value)
        st_clr, irq_clr = self._status(res[8].value), self._irq(res[9].value)
        acc = self._acc(res, {3})
        ctrl_ok = (
            res[3].value == 0
            and pl.st(st_to, "TIMEOUT_ERR") == 1
            and irq_to & pl.IRQ_DRBG_ERR
            and pl.st(st_clr, "TIMEOUT_ERR") == 0
            and not irq_clr & pl.IRQ_DRBG_ERR
            and not acc
        )
        self.controls["pre_active_timeout"] = bool(ctrl_ok)
        self.chk.ctrl(
            "SMP-PRE-ACTIVE-TIMEOUT",
            ctrl_ok,
            t=t,
            slv=res[3].slv,
            data=_h(res[3].value),
            timeout_err=pl.st(st_to, "TIMEOUT_ERR"),
            cleared=int(pl.st(st_clr, "TIMEOUT_ERR") == 0 and not irq_clr & pl.IRQ_DRBG_ERR),
        )
        before, after = self._status(res[11].value), self._status(res[13].value)
        self.pre_stalled = {
            "ok": pl.st(after, "PREFETCHED") == 0
            and pl.st(after, "TIMEOUT_ERR") == 0
            and pl.st(before, "TIMEOUT_ERR") == 0
            and pl.st(after, "COUNT_BAD") == pl.st(before, "COUNT_BAD"),
            "window": self.window_cycles,
            "prefetched": pl.st(after, "PREFETCHED"),
            "timeout_err": pl.st(after, "TIMEOUT_ERR"),
            "bad_before": pl.st(before, "COUNT_BAD"),
            "bad_after": pl.st(after, "COUNT_BAD"),
            "acc": acc,
        }
        runs = self.mon.runs[n0:]
        self.logger.info(
            "LOG stalled prefetch window=%d status_before=%s status_after=%s tready_runs=%s",
            self.window_cycles,
            pl.status_text(before),
            pl.status_text(after),
            [r[1] for r in runs],
        )

    # Step 6.
    async def _step_bad_counter(self) -> None:
        ops = [
            kp.rd(pl.A_STATUS),
            kp.wr(pl.A_STATUS, pl.CLR_BAD_LOW),
            kp.rd(pl.A_STATUS),
            kp.wr(pl.A_CFG, pl.cfg(1, 0)),
            kp.wr(pl.A_STATUS, pl.ST_STICKY),
            kp.rd(pl.A_STATUS),
            kp.rdloop(pl.A_DATA, pl.BAD_LOOP_READS, stride=0),
            kp.rd(pl.A_STATUS),
            kp.rdloop(pl.A_DATA, pl.EXTRA_READS, stride=0),
            kp.rd(pl.A_STATUS),
            kp.wr(pl.A_STATUS, 0),
            kp.rd(pl.A_STATUS),
            kp.wr(pl.A_STATUS, pl.CLR_BAD_FULL),
            kp.rd(pl.A_STATUS),
            *_clear_ops(),
        ]
        res = await self._run(ops, timeout_cycles=_BAD_LOOP_CYCLES)
        b = [pl.st(self._status(res[i].value), "COUNT_BAD") for i in (0, 2, 5, 7, 9, 11, 13)]
        self.bad = {
            "low_before": b[0],
            "clear_low": b[1],
            "start": b[2],
            "sat": b[3],
            "extra": b[4],
            "zero_write": b[5],
            "clear_full": b[6],
            "acc": self._acc(res, {6, 8}),
        }
        self.chk.ctrl(
            "SMP-CNT-BAD-NONZERO",
            0 < b[0] < pl.COUNT_BAD_MAX and b[5] != 0,
            bad_low_before=b[0],
            bad_before_full_clear=b[5],
        )
        self.chk.obs(
            "SMP-LOOP",
            side="bad",
            reads=pl.BAD_LOOP_READS,
            nonzero_loads=res[6].data[0],
            or_loads=_h(res[6].data[1]),
            loop_slv=res[6].slv,
        )

    # Step 7.
    async def _step_trng_reset(self) -> None:
        dut = cocotb.top
        self._gate(False)
        await self.poke.prepare_reset()
        # The inbound FIFO keeps its words across a KM reset and the POKE boot
        # does not flush it, so a leftover word would read as a list header.
        await self.poke.mbox.flush()
        self.swrst.value = _SW_ALL
        await self.swrst.park("km")
        self.noise = self.start_esrc_noise_driver()
        await self._entropy_init(reset_trng=True, what="first")
        sample = await self._wait_tvalid()
        if sample is None:
            raise AssertionError(f"the entropy chain offered no beat within {_TVALID_BOUND} clocks")
        await RisingEdge(dut.clk_i)
        tvalid_before, tready_before = sample
        self.trng_pre = (tvalid_before, tready_before)
        self.controls["trng_offer_held"] = tvalid_before == 1 and tready_before == 0
        self.chk.ctrl(
            "SMP-TRNG-OFFER",
            self.controls["trng_offer_held"],
            tvalid_before=tvalid_before,
            tready_before=tready_before,
        )
        await ReadOnly()
        rst_before = self.rd(dut.trng_gated_rst_n_probe_o)
        await RisingEdge(dut.clk_i)
        self.trng_watch = {"rst_clks": 0, "not_isolated": 0, "km_not_held": 0}
        self._trng_watch_stop = False
        watch = cocotb.start_soon(self._watch_trng_reset())
        self._gate(True)
        await self.swrst.park("trng")
        await self.swrst.release("trng")
        rst_after = 0
        for _ in range(_TRNG_RELEASE_BOUND):
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            rst_after = self.rd(dut.trng_gated_rst_n_probe_o)
            if rst_after and self.trng_watch["rst_clks"]:
                break
        await RisingEdge(dut.clk_i)
        self._trng_watch_stop = True
        await ClockCycles(dut.clk_i, 2)
        watch.kill()
        self._gate(False)
        self.trng_watch.update(rst_before=rst_before, rst_after=rst_after)
        self.logger.info("LOG trng reset probes %s", self.trng_watch)
        swrst = await self.swrst.read_back()
        self.logger.info("LOG trng reset pulse done sw_reset_n=%s", _h(swrst))
        await self._entropy_init(reset_trng=False, what="after_trng_reset")
        if await self._wait_tvalid() is None:
            raise AssertionError(
                f"the entropy chain offered no beat within {_TVALID_BOUND} clocks after the "
                "TRNG reset"
            )
        await RisingEdge(dut.clk_i)
        await self.swrst.release("km")
        await self.poke.wait_boot()
        self._gate(True)

    # Step 8.
    async def _step_first_read(self) -> None:
        ops = [
            *_clear_ops(),
            kp.rd(pl.A_CFG),
            kp.rd(pl.A_STATUS),
            kp.rd(pl.A_DATA),
            kp.rd(pl.A_STATUS),
            kp.rd(pl.A_IRQ_STATUS),
        ]
        res = await self._run(ops)
        st, irq = self._status(res[5].value), self._irq(res[6].value)
        acc = self._acc(res)
        self.first_read_stream_err = pl.st(st, "STREAM_ERR")
        tw = self.trng_watch
        self.chk.ok(
            "SMP-TRNG",
            self.controls["trng_offer_held"]
            and tw["rst_before"] == 1
            and tw["rst_clks"] >= 1
            and tw["not_isolated"] == 0
            and tw["km_not_held"] == 0
            and tw["rst_after"] == 1
            and res[4].slv == 0
            and pl.st(st, "STREAM_ERR") == 0
            and pl.st(st, "COUNT_BAD") == 0
            and not irq & pl.IRQ_DRBG_ERR
            and not acc,
            tvalid_before=self.trng_pre[0],
            tready_before=self.trng_pre[1],
            trng_rst_before=tw["rst_before"],
            trng_rst_clks=tw["rst_clks"],
            trng_rst_not_isolated=tw["not_isolated"],
            trng_rst_km_not_held=tw["km_not_held"],
            trng_rst_after=tw["rst_after"],
            first_read_ok=int(res[4].slv == 0 and res[4].dec == 0),
            stream_err=pl.st(st, "STREAM_ERR"),
            count_bad=pl.st(st, "COUNT_BAD"),
            drbg_err=int(bool(irq & pl.IRQ_DRBG_ERR)),
            cfg=_h(res[2].value),
            status_before=_h(self._status(res[3].value)),
            data=_h(res[4].value),
            bad_responses=",".join(acc) or "none",
        )

    # Step 9.
    async def _step_fed_twin(self) -> None:
        self.fed_hs: list[int] = []
        fed_ok = []
        for t in pl.FED_T:
            ops = [
                kp.wr(pl.A_CFG, pl.cfg(t, 0)),
                kp.rd(pl.A_CFG),
                kp.rd(pl.A_STATUS),
                kp.rd(pl.A_DATA),
                kp.sync(),
                kp.rd(pl.A_DATA),
                kp.sync(),
                kp.rd(pl.A_STATUS),
                kp.rd(pl.A_IRQ_STATUS),
            ]
            self.marks = []
            res = await self._run(ops, on_sync=self._mark)
            hs = self._hs_between(self.marks[0], self.marks[1])
            self.fed_hs.append(hs)
            before, st = self._status(res[2].value), self._status(res[7].value)
            irq = self._irq(res[8].value)
            dgood = pl.st(st, "COUNT_GOOD") - pl.st(before, "COUNT_GOOD")
            acc = self._acc(res)
            ok = (
                res[1].value == pl.cfg(t, 0)
                and res[3].slv == 0
                and res[5].slv == 0
                and dgood == 2
                and pl.st(st, "STREAM_ERR") == 0
                and pl.st(st, "TIMEOUT_ERR") == 0
                and pl.st(st, "COUNT_BAD") == 0
                and not irq & pl.IRQ_DRBG_ERR
                and not acc
            )
            fed_ok.append(ok)
            self.chk.ctrl(
                "SMP-FED-TWIN",
                ok,
                t=t,
                slv=[res[3].slv, res[5].slv],
                count_good_delta=dgood,
                drbg_ready=pl.st(st, "DRBG_READY"),
                stream_err=pl.st(st, "STREAM_ERR"),
                count_bad=pl.st(st, "COUNT_BAD"),
                drbg_err=int(bool(irq & pl.IRQ_DRBG_ERR)),
                data=[_h(res[3].value), _h(res[5].value)],
                handshakes=hs,
                bad_responses=",".join(acc) or "none",
            )
        self.controls["fed_twin"] = all(fed_ok)

    # Step 10.
    async def _step_good_clear(self) -> None:
        ops = [
            kp.rd(pl.A_STATUS),
            kp.wr(pl.A_STATUS, 0),
            kp.rd(pl.A_STATUS),
            kp.wr(pl.A_STATUS, pl.CLR_GOOD_LOW),
            kp.rd(pl.A_STATUS),
        ]
        res = await self._run(ops)
        g = [pl.st(self._status(res[i].value), "COUNT_GOOD") for i in (0, 2, 4)]
        self.good_low = {"before": g[0], "zero_write": g[1], "clear": g[2], "acc": self._acc(res)}
        self.chk.ctrl("SMP-CNT-GOOD-NONZERO", 0 < g[0] < pl.COUNT_GOOD_MAX, good_low_before=g[0])

    # Step 11.
    async def _step_live_prefetch(self) -> None:
        ops = [
            kp.wr(pl.A_CFG, pl.cfg(pl.RESET_T, 1)),
            kp.poll(pl.A_STATUS, pl.ST_PREFETCHED, pl.ST_PREFETCHED, _PREFETCH_POLL_LOADS),
            kp.rdblk(pl.A_PDATA, pl.PDATA_READS, stride=0),
            kp.wr(pl.A_PDATA, _PDATA_WR_WORD),
            kp.wr(pl.A_DATA, _DATA_WR_WORD),
            kp.rd(pl.A_PDATA),
            kp.rd(pl.A_STATUS),
            kp.sync(),
            kp.rd(pl.A_STATUS),
            kp.sync(),
            kp.rd(pl.A_DATA),
            kp.rd(pl.A_STATUS),
            kp.poll(pl.A_STATUS, pl.ST_PREFETCHED, pl.ST_PREFETCHED, _PREFETCH_POLL_LOADS),
            kp.sync(),
            kp.rd(pl.A_PDATA),
            kp.wr(pl.A_CFG, pl.cfg(pl.RESET_T, 0)),
            kp.rd(pl.A_STATUS),
            kp.rd(pl.A_PDATA),
        ]
        self.marks = []
        tvalid_seen: list[int] = []

        async def on_sync(k: int) -> None:
            if k == 0:
                tvalid_seen.append(0 if await self._wait_tvalid() is None else 1)
                await RisingEdge(cocotb.top.clk_i)
            else:
                self.marks.append(self.mon.cycle)
            return None

        res = await self._run(ops, on_sync=on_sync)
        # Ops 3 to 6 are the held-word write refusals; the PREFETCH legs follow.
        wr_res, res = res[3:7], res[:3] + res[7:]
        held_wr_acc = self._acc(wr_res, {wr_res[0].index, wr_res[1].index})
        st_wr = self._status(wr_res[3].value)
        held = res[2].data[0]
        self.chk.ok(
            "SMP-WR",
            wr_res[0].slv == 1
            and wr_res[1].slv == 1
            and wr_res[2].value == held
            and pl.st(st_wr, "PREFETCHED") == 1
            and not held_wr_acc,
            point="held_word",
            pdata_wr_slv=wr_res[0].slv,
            data_wr_slv=wr_res[1].slv,
            pdata=[_h(held), _h(wr_res[2].value)],
            prefetched_after=pl.st(st_wr, "PREFETCHED"),
            bad_responses=",".join(held_wr_acc) or "none",
        )
        prefetched = pl.st(res[1].data[0], "PREFETCHED")
        pd = [res[2].data[i] for i in range(pl.PDATA_READS)]
        pd_flags = res[2].flags
        pd_acc = [f"pdata{i}" for i, f in enumerate(pd_flags) if f.slv or f.dec or not f.clean]
        st_held = self._status(res[4].value)
        st_after = self._status(res[7].value)
        refill = pl.st(res[8].data[0], "PREFETCHED")
        hs = self._hs_between(self.marks[0], self.marks[1])
        st_off = self._status(res[12].value)
        acc = self._acc(res) + pd_acc
        good_delta = pl.st(st_after, "COUNT_GOOD") - pl.st(st_held, "COUNT_GOOD")
        held_ready = int(bool(tvalid_seen and tvalid_seen[0]) and pl.st(st_held, "DRBG_READY") == 1)
        self.controls["held_drbg_ready"] = bool(held_ready)
        self.chk.ctrl(
            "SMP-PRE-HELD-READY",
            held_ready,
            tvalid_seen=tvalid_seen[0] if tvalid_seen else 0,
            drbg_ready=pl.st(st_held, "DRBG_READY"),
        )
        fed_ok = all(h >= 1 for h in self.fed_hs)
        self.controls["fed_handshakes"] = fed_ok
        self.chk.ctrl("SMP-PRE-FED-HANDSHAKE", fed_ok, fed_handshakes=self.fed_hs)
        ps = self.pre_stalled
        next_differs = int(res[10].value != res[6].value)
        self.chk.obs("SMP-NEXT-HELD", next_held_differs=next_differs)
        self.chk.ok(
            "SMP-PRE",
            ps["ok"]
            and not ps["acc"]
            and prefetched == 1
            and pd[0] == pd[1] == pd[2]
            and pl.st(st_held, "PREFETCHED") == 1
            and res[6].slv == 0
            and res[6].value == pd[0]
            and good_delta == 0
            and hs >= 1
            and refill == 1
            and pl.st(st_off, "PREFETCHED") == 0
            and res[13].value == 0
            and not acc,
            control_active_timeout_err=int(self.controls["pre_active_timeout"]),
            stalled_window_clks=ps["window"],
            stalled_prefetched=ps["prefetched"],
            stalled_timeout_err=ps["timeout_err"],
            stalled_bad=[ps["bad_before"], ps["bad_after"]],
            prefetched=prefetched,
            pdata_reads=pl.PDATA_READS,
            pdata_stable=int(pd[0] == pd[1] == pd[2]),
            data_eq_held=int(res[6].value == pd[0]),
            good_delta=good_delta,
            refill_handshakes=hs,
            refill_prefetched=refill,
            next_held_differs=next_differs,
            disable_prefetched=pl.st(st_off, "PREFETCHED"),
            disable_pdata=_h(res[13].value),
            fed_handshakes=self.fed_hs,
            held_drbg_ready=held_ready,
            bad_responses=",".join(ps["acc"] + acc) or "none",
        )
        self.controls["pdata_live"] = pl.st(st_held, "PREFETCHED") == 1 and res[6].value == pd[0]

    # Step 12 and the CHK-SMP-CNT grade.
    async def _step_good_saturation(self) -> None:
        bd = self.bad
        good = None
        if self.plan.good_sat:
            ops = [
                kp.wr(pl.A_CFG, pl.cfg(0, 0)),
                kp.wr(pl.A_STATUS, pl.CLR_GOOD_LOW),
                kp.rd(pl.A_STATUS),
                kp.rdloop(pl.A_DATA, pl.GOOD_LOOP_READS, stride=0),
                kp.rd(pl.A_STATUS),
                kp.rdloop(pl.A_DATA, pl.EXTRA_READS, stride=0),
                kp.rd(pl.A_STATUS),
                kp.wr(pl.A_STATUS, 0),
                kp.rd(pl.A_STATUS),
                kp.wr(pl.A_STATUS, pl.CLR_GOOD_FULL),
                kp.rd(pl.A_STATUS),
                kp.wr(pl.A_CFG, pl.cfg(pl.RESET_T, 0)),
            ]
            res = await self._run(ops, timeout_cycles=_GOOD_LOOP_CYCLES)
            g = [pl.st(self._status(res[i].value), "COUNT_GOOD") for i in (2, 4, 6, 8, 10)]
            good = {
                "start": g[0],
                "sat": g[1],
                "extra": g[2],
                "zero_write": g[3],
                "clear": g[4],
                "acc": self._acc(res),
            }
            self.chk.obs(
                "SMP-LOOP",
                side="good",
                reads=pl.GOOD_LOOP_READS,
                nonzero_loads=res[3].data[0],
                or_loads=_h(res[3].data[1]),
                loop_slv=res[3].slv,
            )
        gl = self.good_low
        bad_ok = (
            bd["clear_low"] == 0
            and bd["start"] == 0
            and bd["sat"] == pl.COUNT_BAD_MAX
            and bd["extra"] == pl.COUNT_BAD_MAX
            and bd["zero_write"] == pl.COUNT_BAD_MAX
            and bd["clear_full"] == 0
            and not bd["acc"]
        )
        good_low_ok = gl["zero_write"] == gl["before"] and gl["clear"] == 0 and not gl["acc"]
        good_ok = good is None or (
            good["start"] == 0
            and good["sat"] == pl.COUNT_GOOD_MAX
            and good["extra"] == pl.COUNT_GOOD_MAX
            and good["zero_write"] == pl.COUNT_GOOD_MAX
            and good["clear"] == 0
            and not good["acc"]
        )
        loops = [pl.BAD_LOOP_READS] + ([pl.GOOD_LOOP_READS] if good else [])
        self.chk.ok(
            "SMP-CNT",
            bad_ok and good_low_ok and good_ok,
            bad_sat=f"0x{bd['sat']:x}",
            bad_after_extra=f"0x{bd['extra']:x}",
            good_sat=f"0x{good['sat']:x}" if good else "skipped",
            good_after_extra=f"0x{good['extra']:x}" if good else "skipped",
            zero_write="kept"
            if bd["zero_write"] == pl.COUNT_BAD_MAX
            and gl["zero_write"] == gl["before"]
            and (good is None or good["zero_write"] == pl.COUNT_GOOD_MAX)
            else "changed",
            nonzero_write_clear=max(
                bd["clear_full"], gl["clear"], good["clear"] if good else 0, bd["clear_low"]
            ),
            bad_clear_low=bd["clear_low"],
            bad_low_before=bd["low_before"],
            good_low_before=gl["before"],
            good_low_zero_write=gl["zero_write"],
            loop_reads=loops,
            bad_responses=",".join(bd["acc"] + gl["acc"] + (good["acc"] if good else [])) or "none",
        )

    # Step 15.
    async def _step_stream_errors(self) -> None:
        cases = [("a", None), *pl.STRM_CASES]
        graded = 0
        for case, t in cases:
            idle = t is None
            head = [kp.wr(pl.A_CFG, pl.cfg(pl.RESET_T if idle else t, 0))]
            head += [] if idle else [kp.rd(pl.A_CFG)]
            pre = [*_clear_ops(), kp.rd(pl.A_STATUS), kp.rd(pl.A_IRQ_STATUS)]
            body = [kp.sync()] if idle else [kp.sync(), kp.rd(pl.A_DATA), kp.sync()]
            tail = [
                kp.rd(pl.A_STATUS),
                kp.rd(pl.A_IRQ_STATUS),
                kp.wr(pl.A_STATUS, 0),
                kp.rd(pl.A_STATUS),
                kp.wr(pl.A_STATUS, pl.ST_STREAM_ERR),
                kp.rd(pl.A_STATUS),
                kp.wr(pl.A_STATUS, pl.ST_TIMEOUT_ERR),
                kp.wr(pl.A_IRQ_STATUS, pl.IRQ_DRBG_ERR | pl.IRQ_SLVERR),
            ]
            ops = head + pre + body + tail
            i_pre = len(head) + 2
            i_data = None if idle else len(head) + len(pre) + 1
            i_post = len(head) + len(pre) + len(body)
            hook: dict[str, int] = {}

            async def on_sync(k: int, idle=idle, hook=hook) -> None:
                if idle:
                    hook["fired"], hook["tready"] = await self._strm_idle_pulse()
                elif k == 0:
                    hook["tready_first"] = self.rd(
                        cocotb.top.km_entropy_tready_o, allow_unknown=True
                    )
                    self._strm(1, 1)
                else:
                    dut = cocotb.top
                    hook["fired"] = self.rd(dut.km_strm_wd_fired_o, allow_unknown=True)
                    hook["tready"] = self.rd(dut.km_strm_wd_tready_o, allow_unknown=True)
                    self._strm(0)
                    await ClockCycles(dut.clk_i, 2)
                return None

            res = await self._run(ops, on_sync=on_sync)
            if not hook.get("fired"):
                raise AssertionError(f"HK-STRM case {case}: the withdrawal inject did not fire")
            st_pre = self._status(res[i_pre].value)
            st = self._status(res[i_post].value)
            irq = self._irq(res[i_post + 1].value)
            st_w0 = self._status(res[i_post + 3].value)
            st_w1 = self._status(res[i_post + 5].value)
            delta = pl.st(st, "COUNT_BAD") - pl.st(st_pre, "COUNT_BAD")
            acc = self._acc(res, set() if idle else {i_data})
            if hook["tready"]:
                self.chk.obs("RACE-MISSED", case=case, tready=1, status=_h(st))
                continue
            self.true_withdrawals += 1
            graded += 1
            fields = dict(
                case=case if idle else f"first_active_t{t}",
                stream_err=pl.st(st, "STREAM_ERR"),
                drbg_err=int(bool(irq & pl.IRQ_DRBG_ERR)),
            )
            cond = (
                pl.st(st_pre, "STREAM_ERR") == 0
                and pl.st(st, "STREAM_ERR") == 1
                and irq & pl.IRQ_DRBG_ERR
                and pl.st(st_w0, "STREAM_ERR") == 1
                and pl.st(st_w1, "STREAM_ERR") == 0
                and not acc
            )
            if idle:
                cond = cond and delta == 1
            else:
                r = res[i_data]
                cond = cond and r.value == 0 and delta >= 1
                fields.update(slv=r.slv, data=_h(r.value))
            fields.update(
                count_bad_delta=delta,
                timeout_err_logged=pl.st(st, "TIMEOUT_ERR"),
                stream_err_w0=pl.st(st_w0, "STREAM_ERR"),
                stream_err_w1c=pl.st(st_w1, "STREAM_ERR"),
                tready_at_pulse=hook["tready"],
                bad_responses=",".join(acc) or "none",
            )
            self.chk.ok("SMP-STRM", cond, **fields)
            if not idle:
                self.chk.obs(
                    "SMP-STRM",
                    case=case,
                    timeout=t,
                    timeout_err=pl.st(st, "TIMEOUT_ERR"),
                    count_bad_delta=delta,
                )
        self.logger.info("LOG stream errors graded=%d of %d", graded, len(cases))

    # End of the leaf.
    async def _step_end(self) -> None:
        self._gate(False)
        self._strm(0)
        swrst = await self.swrst.read_back()
        if not swrst & _KM_BIT:
            self.swrst.value = swrst
            await self.swrst.release("km")
        no_err = all(e == 0 for e in self.stalled_stream_err) and self.first_read_stream_err == 0
        self.controls["strm_no_error_without_withdrawal"] = no_err
        self.chk.ctrl(
            "SMP-STRM-NOERR",
            no_err,
            stalled_stream_err=self.stalled_stream_err,
            first_read_stream_err=self.first_read_stream_err,
        )
        self.controls["wr_status_changes_on_read"] = all(d >= 1 for d in self.stalled_bad_delta)
        self.chk.ctrl(
            "SMP-WR-LIVE",
            self.controls["wr_status_changes_on_read"] and self.controls.get("pdata_live", False),
            stalled_bad_delta=self.stalled_bad_delta,
            pdata_live=int(self.controls.get("pdata_live", False)),
        )
        for reg, seen in self.rsvd.items():
            mask = ~(pl.STATUS_FIELDS if reg == "STATUS" else pl.IRQ_FIELDS) & pl.WORD_MASK
            self.logger.info("LOG RSVD reg=%s masked=%s seen_or=%s", reg, _h(mask), _h(seen))
        self.logger.info("LOG tready_monitor xz_cycles=%d runs=%d", self.mon.xz, len(self.mon.runs))
        self.mon.stop()
        if self.noise is not None:
            self.noise.kill()
            self.noise = None
        self.chk.ok(
            "NONVAC",
            self.true_withdrawals >= 1 and all(self.controls.values()),
            true_withdrawals=self.true_withdrawals,
            controls=sorted(k for k, v in self.controls.items() if v),
            missing=sorted(k for k, v in self.controls.items() if not v) or "none",
        )
