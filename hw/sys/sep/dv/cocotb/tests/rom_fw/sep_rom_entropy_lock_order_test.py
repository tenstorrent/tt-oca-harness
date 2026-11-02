# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The ROM sets FIPS_LOCK between the health test and the first consumer, then the source lock.

rom.adoc, Entropy Chain Bring-Up, Configuration Locks:

    [SEP-ROM-ENT-030] The ROM shall lock the ESRC configuration (`FIPS_LOCK`) after the startup
    health test passes and *before* any entropy reaches a consumer.

    [SEP-ROM-ENT-040] The ROM shall lock the TRNG source selection (`EXT_TRNG_SRC_SEL_LOCK`) once
    bring-up completes, so later software cannot move the crypto-block entropy stream to a
    different source after BL0's own crypto has run.

    Both locks are one-way until reset and are applied by default. Each has a build-time defer
    switch (`SEP_ENTROPY_DEFER_FIPS_LOCK`, `SEP_ENTROPY_DEFER_SRC_SEL_LOCK`) for builds that
    intend BL1 to own the configuration; a production build shall leave both locks enabled.

rom.adoc, Entropy Chain Bring-Up, Sequence, which defines the two completion points:

    |B — generate |Enable the ESRC ring oscillators, then poll `MAIN_SM_STATUS.BOOT_PHASE_DONE`
    for the startup health test to pass, bounded by a timeout.
    |C — enable |Enable EDN, then issue the CSRNG Instantiate through `SW_CMD_REQ` and wait for
    its acknowledgement.

Bus events are AW, AR and B handshakes on the PR-LSU-XBAR tap, at the RDL register addresses; a
lock "takes effect" at the B of its write. The bring-up window runs from the
SEP_MSG_ENTROPY_INIT_START status word to the hand-off mret. The tap carries no read data, so the
end of each poll stands for the value it waited for. The ESRC whitener input is gated by
BOOT_PHASE_DONE, so after the TRNG reset pulse (trng_gated_rst_n_probe_o) a decorrelator sample
(esrc_decor_valid_o) without a whitener push (esrc_whiten_push_o) before the first push is a
sample taken while the health test had not passed. Entropy reaching a consumer is the first of:
the CSRNG seed acknowledge (drbg_es_ack_o), a beat of an internal DRBG stream
(drbg_int_tvalid_o & drbg_int_tready_o), and a word delivered to a crypto EDN client
(crypto_edn_req_o & crypto_edn_ack_o). A lock write is the locking write when it is the only
write to that register in the run and a debug-module system-bus read after the run shows the
lock bit set (both lock bits are write-one-to-set, reset 0).

* CHK-FIPS-LOCK-AFTER-HEALTH: at least one MAIN_SM_STATUS read in the window and every one of
  them before the first FIPS_LOCK AW; the last gated-out sample after the TRNG reset pulse is
  before that AW.
* CHK-FIPS-LOCK-BEFORE-CONSUMER: the FIPS_LOCK write is the locking write and its B precedes the
  first entropy consumer event.
* CHK-SRC-SEL-LOCK-AFTER-BRINGUP: the first EXT_TRNG_SRC_SEL_LOCK AW in the window follows the
  FIPS_LOCK AW, the SW_CMD_REQ AW, the CSRNG Instantiate command (edn_csrng_cmd_*, acmd 1), the
  CSRNG seed acknowledge and at least one SW_CMD_STS read after SW_CMD_REQ; no SW_CMD_STS read
  follows it in the window; it is the locking write and its B precedes the hand-off mret.

FIPS_LOCK before the EDN enable (the last EDN_CTRL AW before the first SW_CMD_REQ AW) and the
source lock before MANIFEST_VALIDATED are ROM ordering, not spec, so they are OBS-ROM-ORDER only.

Partial coverage. Not graded: the read data of either poll; that BOOT_PHASE_DONE is set before
the lock (the gate places its rise after the last gated-out sample and at or before the first
whitener push, 80 ns apart on the graded run); the CSRNG Instantiate acknowledgement itself,
which no TB probe carries; whether either lock blocks a later write; the production-build
sentence beyond the locking writes on this build; the FIFO close steps before FIPS_LOCK
(OBS-FIFO-CLOSE only); the defer switches; the external-source path; the order of the source
lock against the first OTBN URND reseed delivery (OBS-CONSUMERS only). The leaf runs
`sep_rom_ot_secure_boot_test` and keeps its checks.
"""

from __future__ import annotations

import cocotb
import pyuvm
from env.sep_chk_log import SepChkLog
from env.sep_fabric_tap import SepFabricTap
from env.sep_jtag_dmi import (
    DM_DMCONTROL,
    DMCONTROL_DMACTIVE,
    IR_DMI,
    IR_WIDTH,
    PIN_MAP,
    SepJtagDmi,
)
from env.sep_rom_observer import STORE_LAG_MAX_CYCLES, SepRomObserver
from ocah_jtag_vip import OcahJtagMasterDriver
from rom_fw.sep_rom_ot_secure_boot_test import sep_rom_ot_secure_boot_test as _Base
from sep_reg_meta import ENTROPY_SOURCE, SEP_CPU_CTRL, sym

_FIPS_LOCK = sym("ENTROPY_SOURCE_FIPS_LOCK_REG_ADDR")
_MAIN_SM_STATUS = sym("ENTROPY_SOURCE_MAIN_SM_STATUS_REG_ADDR")
_FIFO_CTRL = sym("ENTROPY_SOURCE_FIFO_CTRL_REG_ADDR")
_FIFO_STATUS = sym("ENTROPY_SOURCE_FIFO_STATUS_REG_ADDR")
_FIFO_RDATA = sym("ENTROPY_SOURCE_FIFO_RDATA_REG_ADDR")
_EDN_CTRL = sym("EDN_CTRL_REG_ADDR")
_EDN_SW_CMD_REQ = sym("EDN_SW_CMD_REQ_REG_ADDR")
_EDN_SW_CMD_STS = sym("EDN_SW_CMD_STS_REG_ADDR")
_SRC_SEL_LOCK = sym("SEP_CPU_CTRL_EXT_TRNG_SRC_SEL_LOCK_REG_ADDR")
_FIPS_LOCK_BM = ENTROPY_SOURCE.fields("FIPS_LOCK")["LOCK"]["bm"]
_SRC_SEL_LOCK_BM = SEP_CPU_CTRL.field_mask("EXT_TRNG_SRC_SEL_LOCK", "lock")

# STATUS_ENCODE(type, 1 = BL0, code); codes from hw/sys/sep/doc/gen/status_values.adoc.
_BL0 = 1 << 16
_ENTROPY_INIT_START = 0x0225
_MANIFEST_VALIDATED = (0x01 << 24) | _BL0 | 0x0053
# CSRNG application command Instantiate; acmd encoding of csrng_pkg (vendor OpenTitan csrng).
_CSRNG_ACMD_INS = 1
_OTBN_URND = 1 << 3
_TCK_CLKS = 4
_TRST_TCK = 4
_SB_BUSY_READS = 1024

_CRYPTO_REQ, _CRYPTO_ACK = "crypto_edn_req_o", "crypto_edn_ack_o"
_ES_ACK, _SEED_VALID = "drbg_es_ack_o", "drbg_seed_valid_o"
_INT_VALID, _INT_READY = "drbg_int_tvalid_o", "drbg_int_tready_o"
_CMD_VALID, _CMD_READY, _CMD_BUS = (
    "edn_csrng_cmd_valid_o",
    "edn_csrng_cmd_ready_o",
    "edn_csrng_cmd_bus_o",
)
_TRNG_RST_N = "trng_gated_rst_n_probe_o"
_DECOR_VALID, _WHITEN_PUSH, _COMPRESS_VLD = (
    "esrc_decor_valid_o",
    "esrc_whiten_push_o",
    "esrc_compress_vld_o",
)
_WATCH = (
    _CRYPTO_REQ,
    _CRYPTO_ACK,
    _ES_ACK,
    _SEED_VALID,
    _INT_VALID,
    _INT_READY,
    _CMD_VALID,
    _CMD_READY,
    _CMD_BUS,
    _TRNG_RST_N,
    _DECOR_VALID,
    _WHITEN_PUSH,
    _COMPRESS_VLD,
)


def _ps(t: int | None) -> int:
    return -1 if t is None else int(t)


def _hex(v: int | None) -> str:
    return "none" if v is None else f"0x{v:08x}"


def _first_when(obs: SepRomObserver, names: tuple[str, ...], pred) -> int | None:
    """First record time at which pred holds on the current values of the watched ports."""
    cur = dict.fromkeys(names, 0)
    by_t: dict[int, list[tuple[str, int]]] = {}
    for n in names:
        for t, v in obs.watched[n]:
            by_t.setdefault(t, []).append((n, v))
    for t in sorted(by_t):
        for n, v in by_t[t]:
            cur[n] = v
        if pred(cur):
            return t
    return None


def _edges(obs: SepRomObserver, name: str, rise: bool) -> list[int]:
    """Times at which a watched port goes from zero to nonzero (rise) or back to zero."""
    out, prev = [], 0
    for t, v in obs.watched[name]:
        if bool(v) != bool(prev) and bool(v) == rise:
            out.append(t)
        prev = v
    return out


def _value_at(obs: SepRomObserver, name: str, t: int) -> int | None:
    return next((v for tv, v in reversed(obs.watched[name]) if tv <= t), None)


def _first(times: list[int]) -> int | None:
    return min(times) if times else None


@pyuvm.test()
class sep_rom_entropy_lock_order_test(_Base):
    required_evidence = (
        "CHK-FIPS-LOCK-AFTER-HEALTH",
        "CHK-FIPS-LOCK-BEFORE-CONSUMER",
        "CHK-SRC-SEL-LOCK-AFTER-BRINGUP",
        "CHK-ROM-PATH",
        "CHK-OTBN-EDN",
    )

    async def run_scenario(self) -> None:
        self.chk = SepChkLog(self, self.get_type_name(), self.random_seed())
        xbar = SepFabricTap("PR-LSU-XBAR").start()
        obs = SepRomObserver(self, keep=lambda _insn: False, tracker=False, watch=_WATCH).start()
        locks: dict = {}
        try:
            await super().run_scenario()
        finally:
            # The tap keeps running through the read, so the write count covers the read time.
            locks = await self._read_locks()
            await obs.stop()
            await xbar.stop()
            self._grade(obs, xbar, locks)
        self.chk.finish()

    async def _read_locks(self) -> dict:
        """Lock registers read by the debug-module system-bus master, not by the ROM."""
        dut = cocotb.top
        out: dict = {"error": "none"}
        tap = OcahJtagMasterDriver(
            dut,
            name="sep_core_tap",
            tck_period_ns=int(round(_TCK_CLKS * self.cfg.sys_clk_period_ns * 1000)),
            ir_width=IR_WIDTH,
            tap_type="dtm",
            signal_map=dict(PIN_MAP),
            time_unit="ps",
        )
        dmi = SepJtagDmi(tap, dut=dut, log=self.logger, busy_bound=_SB_BUSY_READS)
        dut.dmi_core_enable_i.value = 1
        dmi.take_pins()
        try:
            await dmi.trst_pulse(tck_cycles=_TRST_TCK)
            await tap.goto_state("RUN_TEST_IDLE")
            await tap.shift_ir(IR_DMI, IR_WIDTH, back_to_rti=True)
            await dmi.dmi_write(DM_DMCONTROL, DMCONTROL_DMACTIVE)
            for name, addr in (("fips", _FIPS_LOCK), ("sel", _SRC_SEL_LOCK)):
                out[name], out[f"{name}_sberr"] = await dmi.sba_read(addr, size=4)
        # Any failure of the debug path fails the lock-value part instead of skipping it.
        except Exception as exc:
            out["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            dmi.release_pins()
            dut.dmi_core_enable_i.value = 0
        return out

    def _grade(self, obs: SepRomObserver, xbar: SepFabricTap, locks: dict) -> None:
        chk = self.chk
        clk_ps = (
            (obs.first[-1].t_ps - obs.first[0].t_ps) // (obs.first[-1].cycle - obs.first[0].cycle)
            if len(obs.first) > 1
            else 0
        )
        lag_ps = STORE_LAG_MAX_CYCLES * clk_ps
        t_start = next(
            (t for t, w in obs.status if w & 0x00FF_FFFF == _BL0 | _ENTROPY_INIT_START), None
        )
        t_valid = obs.status_t(_MANIFEST_VALIDATED)
        t_mret = obs.pre_mret[-1].t_ps if obs.pre_mret else None
        chk.ctrl(
            "BRINGUP-WINDOW",
            None not in (t_start, t_mret) and clk_ps > 0 and t_start < t_mret,
            entropy_init_start_ps=_ps(t_start),
            handoff_mret_ps=_ps(t_mret),
            clk_ps=clk_ps,
        )
        lo = None if t_start is None else t_start - lag_ps
        hi = t_mret

        def in_win(t: int) -> bool:
            return lo is not None and hi is not None and lo <= t <= hi

        aw = [b for b in xbar.beats if b.ch == "aw"]
        ar = [b for b in xbar.beats if b.ch == "ar"]
        unknown = sum(1 for b in aw + ar if b.addr is None)

        def aws(addr: int) -> list[int]:
            return [b.t_ps for b in aw if b.addr == addr and in_win(b.t_ps)]

        def ars(addr: int) -> list[int]:
            return [b.t_ps for b in ar if b.addr == addr and in_win(b.t_ps)]

        def write_b(addr: int) -> tuple[int | None, int | None]:
            """(time, BRESP) of the first B with the ID of the first AW to addr in the window."""
            beat = next((b for b in aw if b.addr == addr and in_win(b.t_ps)), None)
            if beat is None:
                return None, None
            rsp = next(
                (b for b in xbar.beats if b.ch == "b" and b.t_ps >= beat.t_ps and b.id == beat.id),
                None,
            )
            return (None, None) if rsp is None else (rsp.t_ps, rsp.resp)

        def locking(addr: int, key: str, bm: int) -> tuple[bool, int]:
            """The only write to addr in the run, read back with the lock bit set."""
            writes = sum(1 for b in aw if b.addr == addr)
            val = locks.get(key)
            ok = (
                writes == 1
                and locks.get("error") == "none"
                and locks.get(f"{key}_sberr") == 0
                and val is not None
                and bool(val & bm)
            )
            return ok, writes

        t_fips_b, fips_resp = write_b(_FIPS_LOCK)
        t_sel_b, sel_resp = write_b(_SRC_SEL_LOCK)
        fips_locked, fips_writes = locking(_FIPS_LOCK, "fips", _FIPS_LOCK_BM)
        sel_locked, sel_writes = locking(_SRC_SEL_LOCK, "sel", _SRC_SEL_LOCK_BM)
        t_fips = _first(aws(_FIPS_LOCK))
        t_sel = _first(aws(_SRC_SEL_LOCK))
        chk.ctrl(
            "LOCK-WRITES-SEEN",
            None not in (t_fips, t_sel, t_fips_b, t_sel_b)
            and not unknown
            and fips_resp == 0
            and sel_resp == 0,
            fips_lock_addr=f"0x{_FIPS_LOCK:08x}",
            fips_lock_aw_ps=_ps(t_fips),
            fips_lock_b_ps=_ps(t_fips_b),
            fips_lock_bresp=-1 if fips_resp is None else fips_resp,
            src_sel_lock_addr=f"0x{_SRC_SEL_LOCK:08x}",
            src_sel_lock_aw_ps=_ps(t_sel),
            src_sel_lock_b_ps=_ps(t_sel_b),
            src_sel_lock_bresp=-1 if sel_resp is None else sel_resp,
            xbar_aw=len(aw),
            xbar_ar=len(ar),
            unknown_addr=unknown,
        )
        chk.obs(
            "LOCK-READBACK",
            fips_lock=_hex(locks.get("fips")),
            fips_sberr=locks.get("fips_sberr", -1),
            fips_writes_in_run=fips_writes,
            src_sel_lock=_hex(locks.get("sel")),
            src_sel_sberr=locks.get("sel_sberr", -1),
            src_sel_writes_in_run=sel_writes,
            dmi_error=locks.get("error", "not-run"),
        )

        # Last ESRC reset pulse before the lock, and the samples the boot gate held back after it.
        rst_rise = [t for t in _edges(obs, _TRNG_RST_N, True) if in_win(t)]
        rst_fall = [t for t in _edges(obs, _TRNG_RST_N, False) if in_win(t)]
        t_rel = next((t for t in reversed(rst_rise) if t_fips is not None and t < t_fips), None)
        t_rst = next((t for t in reversed(rst_fall) if t_rel is not None and t < t_rel), None)
        t_push = next(
            (t for t in _edges(obs, _WHITEN_PUSH, True) if t_rel is not None and t > t_rel), None
        )
        held = [
            t
            for t in _edges(obs, _DECOR_VALID, True)
            if None not in (t_rel, t_push) and t_rel < t < t_push
        ]
        chk.ctrl(
            "ESRC-GATE-LIVE",
            None not in (t_rst, t_rel, t_push) and bool(held),
            trng_rst_fall_ps=_ps(t_rst),
            trng_rst_release_ps=_ps(t_rel),
            first_whiten_push_ps=_ps(t_push),
            gated_out_samples=len(held),
        )

        polls = ars(_MAIN_SM_STATUS)
        before = [t for t in polls if t_fips is not None and t < t_fips]
        after = [t for t in polls if t_fips is None or t >= t_fips]
        chk.ok(
            "FIPS-LOCK-AFTER-HEALTH",
            t_fips is not None and bool(before) and not after and bool(held) and held[-1] < t_fips,
            fips_lock_aw_ps=_ps(t_fips),
            main_sm_status_reads=len(polls),
            last_read_before_ps=_ps(before[-1] if before else None),
            reads_after_lock=len(after),
            first_read_after_ps=_ps(after[0] if after else None),
            last_gated_out_sample_ps=_ps(held[-1] if held else None),
            first_whiten_push_ps=_ps(t_push),
        )

        t_req = _first(aws(_EDN_SW_CMD_REQ))
        edn_ctrl = [t for t in aws(_EDN_CTRL) if t_req is not None and t < t_req]
        t_enable = edn_ctrl[-1] if edn_ctrl else None
        t_seed = _first_when(obs, (_ES_ACK,), lambda c: c[_ES_ACK] & 1)
        t_int = _first_when(obs, (_INT_VALID, _INT_READY), lambda c: c[_INT_VALID] & c[_INT_READY])
        t_crypto = _first_when(
            obs, (_CRYPTO_REQ, _CRYPTO_ACK), lambda c: c[_CRYPTO_REQ] & c[_CRYPTO_ACK]
        )
        t_urnd = _first_when(
            obs, (_CRYPTO_REQ, _CRYPTO_ACK), lambda c: c[_CRYPTO_REQ] & c[_CRYPTO_ACK] & _OTBN_URND
        )
        t_ins = _first_when(
            obs,
            (_CMD_VALID, _CMD_READY, _CMD_BUS),
            lambda c: c[_CMD_VALID] & c[_CMD_READY] and c[_CMD_BUS] & 0x7 == _CSRNG_ACMD_INS,
        )
        chk.ctrl(
            "CONSUMER-FIRED",
            None not in (t_seed, t_crypto, t_urnd, t_ins),
            es_ack_ps=_ps(t_seed),
            crypto_edn_delivered_ps=_ps(t_crypto),
            otbn_urnd_delivered_ps=_ps(t_urnd),
            csrng_instantiate_cmd_ps=_ps(t_ins),
            drbg_int_beat_ps=_ps(t_int),
        )
        t_consumer = _first([t for t in (t_seed, t_int, t_crypto) if t is not None])
        chk.ok(
            "FIPS-LOCK-BEFORE-CONSUMER",
            None not in (t_fips_b, t_consumer) and fips_locked and t_fips_b < t_consumer,
            fips_lock_b_ps=_ps(t_fips_b),
            locking_write=int(fips_locked),
            first_consumer_ps=_ps(t_consumer),
            es_ack_ps=_ps(t_seed),
            drbg_int_beat_ps=_ps(t_int),
            crypto_edn_delivered_ps=_ps(t_crypto),
        )

        sts = [t for t in ars(_EDN_SW_CMD_STS) if t_req is not None and t > t_req]
        sts_before = [t for t in sts if t_sel is not None and t < t_sel]
        sts_after = [t for t in sts if t_sel is None or t >= t_sel]
        chk.ok(
            "SRC-SEL-LOCK-AFTER-BRINGUP",
            None not in (t_sel, t_sel_b, t_fips, t_enable, t_req, t_ins, t_seed, t_mret)
            and max(t_fips, t_enable, t_req, t_ins, t_seed) < t_sel
            and bool(sts_before)
            and not sts_after
            and sel_locked
            and t_sel_b < t_mret,
            src_sel_lock_aw_ps=_ps(t_sel),
            src_sel_lock_b_ps=_ps(t_sel_b),
            locking_write=int(sel_locked),
            fips_lock_aw_ps=_ps(t_fips),
            edn_enable_aw_ps=_ps(t_enable),
            sw_cmd_req_aw_ps=_ps(t_req),
            csrng_instantiate_cmd_ps=_ps(t_ins),
            es_ack_ps=_ps(t_seed),
            sw_cmd_sts_reads=len(sts),
            last_sts_read_before_ps=_ps(sts_before[-1] if sts_before else None),
            sts_reads_after_lock=len(sts_after),
            handoff_mret_ps=_ps(t_mret),
        )

        chk.obs(
            "ROM-ORDER",
            fips_lock_b_before_edn_enable=-1
            if None in (t_fips_b, t_enable)
            else int(t_fips_b < t_enable),
            fips_lock_b_ps=_ps(t_fips_b),
            edn_enable_aw_ps=_ps(t_enable),
            src_sel_lock_b_before_manifest_validated=-1
            if None in (t_sel_b, t_valid)
            else int(t_sel_b < t_valid - lag_ps),
            src_sel_lock_b_ps=_ps(t_sel_b),
            manifest_validated_ps=_ps(t_valid),
        )
        fifo_ctrl = [t for t in aws(_FIFO_CTRL) if t_fips is not None and t < t_fips]
        t_close = fifo_ctrl[-1] if fifo_ctrl else None
        chk.obs(
            "FIFO-CLOSE",
            fifo_ctrl_aw_before_lock=len(fifo_ctrl),
            last_fifo_ctrl_aw_ps=_ps(t_close),
            fifo_status_reads=sum(
                1 for t in ars(_FIFO_STATUS) if t_close is not None and t_close < t < t_fips
            ),
            fifo_rdata_reads=sum(
                1 for t in ars(_FIFO_RDATA) if t_close is not None and t_close < t < t_fips
            ),
            fips_lock_aw_ps=_ps(t_fips),
        )
        sv_rise = _edges(obs, _SEED_VALID, True)
        sv_after = next((t for t in sv_rise if t_rel is not None and t > t_rel), None)
        sv_low = (
            None
            if None in (t_rst, t_rel)
            else int(
                _value_at(obs, _SEED_VALID, t_rst) == 0
                or any(v == 0 for t, v in obs.watched[_SEED_VALID] if t_rst <= t <= t_rel)
            )
        )
        t_compress = next(
            (t for t in _edges(obs, _COMPRESS_VLD, True) if t_rel is not None and t > t_rel), None
        )
        chk.obs(
            "CONSUMERS",
            seed_valid_first_ps=_ps(sv_rise[0] if sv_rise else None),
            seed_valid_low_in_trng_reset=-1 if sv_low is None else sv_low,
            seed_valid_first_after_release_ps=_ps(sv_after),
            seed_valid_after_release_before_fips_lock=-1
            if None in (sv_after, t_fips)
            else int(sv_after < t_fips),
            first_compress_vld_after_release_ps=_ps(t_compress),
            trng_rst_pulses_in_run=len(_edges(obs, _TRNG_RST_N, False)),
            trng_rst_after_fips_lock=sum(
                1 for t in _edges(obs, _TRNG_RST_N, False) if t_fips is not None and t > t_fips
            ),
            src_sel_lock_before_otbn_urnd_reseed=-1
            if None in (t_sel, t_urnd)
            else int(t_sel < t_urnd),
            otbn_urnd_delivered_ps=_ps(t_urnd),
            first_retire_ps=_ps(obs.first[0].t_ps if obs.first else None),
        )
        chk.obs(
            "CONSOLE-ORDER",
            entropy_ok_ps=_ps(obs.line_t("ENTROPY_OK")),
            manifest_ok_ps=_ps(obs.line_t("MANIFEST_OK")),
        )
