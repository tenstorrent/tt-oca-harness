# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Lifecycle integrity error: FEAT_CTRL fails closed, SEC_DIS wins, the JTAG filter refuses.

RAND-REP. Run mode no_cpu (``lsu_stub_all_live``), real fuse sense. The seed draws
the nibble n of the t=0 image (``{~n, n}`` in ``LC_STATE``) from the seven
open-profile nibbles (0000 weight 2, 0001, 0010, 0011, 0110, 0111, 1000 weight 1)
and a filter-legal disable-vector pair; ``dv_sim_prestage.py`` stages the image
from ``env/sep_efuse_plan.py`` and the leaf builds the same plan. A leaf that draws
0000 (TEST_DEV) also draws leg C: the JTAG shadow word, the control bit and the
drawn bit of ``SIP_DIS`` (two bits the staged ``SIP_DIS`` lacks), the counts c1
and c2, and the word order of the token write.

Contract (``hw/sys/sep/doc/lifecycle_controller.adoc``, sections Lifecycle States,
Demotion, Overrides and Final Gates (SEC_DIS), Per-LC-state Feature Control Profile,
Debug and Test Port Path Gating, row SEP OTP JTAG2AXIL path;
``hw/sys/sep/doc/security_disable.adoc``, sections Token Activation, Implementation
Requirements; ``doc/integrator/src/smu-sep.adoc``, ``dbg_disable_o`` polarity):

  CHK-BIND          the SHA-256 of 32 zero bytes equals the SEC_DIS digest that the
                    bench binds, read through the simulator handle of
                    ``SecDisTbDigest`` (``tb/tb_top.sv``).
  CHK-SIGINT        leg A, one line per inject epoch. The leaf walks the 30 pairs
                    (pair mask 1 to 15, bad rail value 0 or 1) in seeded order with
                    no demotion, sets the drawn demotion, and walks the 30 pairs
                    again in a second seeded order. An epoch raises
                    ``lc_sigint_inject_i`` with ``lc_sigint_pair_mask_i`` and
                    ``lc_sigint_bad_value_i``: each selected pair of the byte at the
                    lifecycle decoder input has both rails at the bad value. On
                    every clock from the first clock ``sep_ras_o.lc_sigint_err``
                    (``lcc_sigint_err_probe_o``) reads 1 until the inject falls,
                    ``sep_ras_o.lc_sigint_err`` = 1 and ``lcc_feat_ctrl_probe_o`` = 0,
                    and one ``FEAT_CTRL`` register read inside the epoch is 0.
                    Control: the epoch before the walk reads the non-zero profile row
                    with ``sep_ras_o.lc_sigint_err`` = 0. Nibble 0111 is logged
                    ``role=control``.
  CTRL-SIGINT-EPOCHS the number of epochs whose stimulus reached the lifecycle
                    decoder input (``u_lc_state_dec.data_i`` shows exactly the pairs
                    of the epoch's mask broken, both rails at its bad value) equals
                    the number of epochs of the two walks (60).
  CHK-SIGINT-PAIRS  in each epoch, on every clock, each demote pair
                    (``lcc_demote_state_1_probe_o``, ``lcc_demote_state_2_probe_o``)
                    equals its own level read before the walk. Control of the demoted
                    walk: the pair of a demoted register differs from its level after
                    the cold reset and the pair of the other register does not. The
                    levels are logged (``OBS-DEMOTE-PAIR-LEVEL``) and not graded.
  CHK-SIGINT-DEMOTE-REG in the last epoch of the demoted walk, the 64-bit
                    ``DEMOTE_1`` and ``DEMOTE_2`` readbacks equal the value written
                    before the walk: the drawn demote bit and one drawn ``rsvd``
                    marker bit (``sep_lifecycle_ctrl.rdl``, ``rsvd`` is ``woset``), lock
                    0. The same readback before the walk shows the write landed.
  CHK-DBG-DISABLE   in each epoch, every ``dbg_disable_<name>_o`` port of a gated
                    path (Case 1, 2 or 3 of the path table) reads 1. Control: under
                    the leg B ``TOKEN_ZERO`` match every gated port reads 0.
  CHK-FUSE-DFT-CLASS ``sep_fuse_dft_disable_o`` and ``smc_fuse_dft_disable_o`` read
                    their closed control in every epoch. Controls from the same leaf:
                    closed is the value at the first clock after the bring-up
                    ``rst_ni`` release with fuse sense running, SEC_DIS 0 and the
                    port at 0 or 1; open is the
                    value under the leg B ``TOKEN_ZERO`` match; the two differ. The
                    levels are logged (``OBS-DTP-PORT-LEVEL``) and not graded.
  CHK-SIGINT-SECDIS with the inject raised again on every pair (both rails 0, the
                    drawn demotion still set), a ``TOKEN_ZERO`` SEC_DIS match
                    gives an all-ones ``FEAT_CTRL`` with ``sep_ras_o.lc_sigint_err`` = 1, and
                    a ``TOKEN_OTHER`` mismatch returns it to 0. Control:
                    ``security_disable_o`` rises on the match (else ``CHK-HOOK FAIL``).
  CHK-JTAG-SIGINT   leg C (n = 0000): while ``jtag_filter_lc_sigint_err_probe_o`` = 1
                    under ``jtag_filter_lc_sigint_inject_i``, a JTAG read of a shadow
                    word and of ``EFUSE_PROGRAM_CTRL``, a JTAG write to ``SIP_DIS`` and
                    a JTAG write to ``EFUSE_READ_REQ_TIMEOUT`` answer a response that is
                    not OKAY and change nothing at the frontdoor; the token word
                    writes, the token word read, the go and the match read answer
                    OKAY. Control: the epoch without the inject answers OKAY to the two
                    reads and to a JTAG write of the control bit and of c1, and the
                    frontdoor shows both writes landed. A probe that stays 0 under the
                    inject fails the leaf with ``CHK-HOOK FAIL``. A leaf with another
                    nibble logs ``CHK-JTAG-SIGINT N/A``.

Nothing is graded after an inject input falls: the specification states no release
of ``sep_ras_o.lc_sigint_err``. After the first epoch of the walk the leaf logs
``sep_ras_o.lc_sigint_err``, ``FEAT_CTRL`` and ``lcc_feat_ctrl_probe_o``
(``OBS-LC-SIGINT-RELEASE``). The value of ``lc_state_o`` in each epoch is logged
(``OBS-LC-PORT-SIGINT``): no text states the port under the error.
``sep_ras_o.lc_sigint_err`` under the filter-side inject is logged
(``OBS-LC-SIGINT-FILTER``) and not graded.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge
from env.sep_chk_log import SepChkLog
from env.sep_efuse_plan import (
    CH_SIP,
    CODE_MATCH,
    CODE_MISMATCH,
    GO_MASK,
    MATCH_ADDR,
    MATCH_STATUS_MASK,
    PROGRAM_CTRL_ADDR,
    SHADOW_BASE,
    TOKEN_ARRAY_ADDR,
    TOKEN_EOP_ADDR,
    TOKEN_OTHER,
    TOKEN_ZERO,
    feat_ctrl_profile,
    plan,
    shadow_addr,
    token_words,
)
from env.sep_efuse_test_lib import (
    SepEfuseFd,
    bit,
    chk_bind,
    hook_fail,
    sec_dis_go,
    wait_bit,
)
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_lcc_golden import DBG_DISABLE_FIELDS, dbg_disable_expected
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import EFUSE_INTERFACE_CTRL, SEP_LIFECYCLE_CTRL

TEST = "sep_lcc_state_codeword_rand_test"

FEAT_CTRL = SEP_LIFECYCLE_CTRL.addr("FEAT_CTRL")
READ_TIMEOUT = EFUSE_INTERFACE_CTRL.addr("EFUSE_READ_REQ_TIMEOUT")
READ_TIMEOUT_FIELDS = EFUSE_INTERFACE_CTRL.field_mask(
    "EFUSE_READ_REQ_TIMEOUT", "read_req_timeout_cycles"
) | EFUSE_INTERFACE_CTRL.field_mask("EFUSE_READ_REQ_TIMEOUT", "read_req_timout_enable")
DEMOTE_ADDR = {1: SEP_LIFECYCLE_CTRL.addr("DEMOTE_1"), 2: SEP_LIFECYCLE_CTRL.addr("DEMOTE_2")}
DEMOTE_BIT = SEP_LIFECYCLE_CTRL.field_mask("DEMOTE_1", "demote")
RSVD_MASK = SEP_LIFECYCLE_CTRL.field_mask("DEMOTE_1", "rsvd")
RSVD_BITS = tuple(b for b in range(64) if (RSVD_MASK >> b) & 1)
ALL_ONES = (1 << 64) - 1
# Bad rail values of an inject epoch: both rails 0, both rails 1.
BAD_VALUES = (0, 1)
# Demotion set between the two walks: (DEMOTE_1, DEMOTE_2).
DEMOTE_SETS = ((1, 0), (0, 1), (1, 1))
# Clocks an epoch holds before its register reads; the FCOV gate-port point
# samples a condition once it has held 8 clocks.
EPOCH_HOLD = 16
# dbg_disable ports of a gated path: the ones that FEAT_CTRL = 0 closes.
GATED_DBG = tuple(k for k, v in dbg_disable_expected(0).items() if v == 1)
FUSE_PORTS = {"sep": "sep_fuse_dft_disable_o", "smc": "smc_fuse_dft_disable_o"}
_WALK_SALT = 0x5349_4749_4E54_5741
NIBBLE_CONTROL = 0b0111
OKAY = 0
# Bounds (clocks or reads). A timeout fails the check the wait feeds.
SIGINT_BOUND = 200
SDIS_BOUND = 200
MATCH_READS = 400
SENSE_BOUND = 20_000


@pyuvm.test()
class sep_lcc_state_codeword_rand_test(sep_base_test):
    """Integrity error forces FEAT_CTRL to 0, SEC_DIS overrides it, the JTAG filter refuses."""

    required_evidence = (
        "CHK-BIND",
        "CHK-SIGINT",
        "CHK-SIGINT-PAIRS",
        "CHK-SIGINT-DEMOTE-REG",
        "CHK-DBG-DISABLE",
        "CHK-FUSE-DFT-CLASS",
        "CHK-SIGINT-SECDIS",
    )

    # -- samples -------------------------------------------------------------

    async def _feat(self) -> tuple[int, int]:
        """64-bit frontdoor read of FEAT_CTRL and the probe right after it."""
        reg = await self.fd.rd64(FEAT_CTRL)
        return reg, self.rd_known(cocotb.top.lcc_feat_ctrl_probe_o)

    async def _cold_reset(self) -> None:
        await RisingEdge(cocotb.top.clk_i)
        await self.resense(max_cycles=SENSE_BOUND)

    def _pairs(self) -> tuple[int, int]:
        return tuple(
            self.rd_known(getattr(cocotb.top, f"lcc_demote_state_{r}_probe_o")) & 0x3
            for r in (1, 2)
        )

    @staticmethod
    def _port(name: str) -> int | None:
        """Bit 0 of a top-level port; None when it is X or Z."""
        v = getattr(cocotb.top, name).value
        return int(v) & 1 if v.is_resolvable else None

    def _fuse_ports(self) -> dict[str, int | None]:
        return {k: self._port(sig) for k, sig in FUSE_PORTS.items()}

    async def _presense_sample(self) -> dict:
        """Gate ports before sense: the first clock after the bring-up ``rst_ni``
        release with sense running, SEC_DIS 0 and both fuse DFT ports known."""
        dut = cocotb.top
        seen_low = False
        clk = 0
        while True:
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            rst = dut.rst_ni.value
            if not rst.is_resolvable or int(rst) == 0:
                seen_low = True
                continue
            if not seen_low:
                continue
            got = {
                **self._fuse_ports(),
                "sense_done": self._port("sep_fuse_sense_done_o"),
                "sdis": self._port("lcc_security_disable_probe_o"),
                "clk": clk,
            }
            clk += 1
            known = got["sep"] is not None and got["smc"] is not None
            if got["sense_done"] != 0 or (got["sdis"] == 0 and known) or clk > SENSE_BOUND:
                return got

    # -- checks --------------------------------------------------------------

    async def _epoch_watch(self, st: dict) -> None:
        """Every clock until ``st["stop"]``: the error, FEAT_CTRL and the demote pairs."""
        dut = cocotb.top
        while True:
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            if st["stop"]:
                return
            self._epoch_sample(st)

    def _epoch_sample(self, st: dict) -> None:
        clk = st["clocks"]
        st["clocks"] += 1
        sig = self._port("lcc_sigint_err_probe_o")
        v = cocotb.top.lcc_feat_ctrl_probe_o.value
        feat = int(v) if v.is_resolvable else None
        if st["bad"] is None and (sig != 1 or feat != 0):
            st["bad"] = f"clk{clk}:sigint={sig},feat={'x' if feat is None else hex(feat)}"
        pairs = tuple(
            int(p.value) & 0x3 if p.value.is_resolvable else None
            for p in (cocotb.top.lcc_demote_state_1_probe_o, cocotb.top.lcc_demote_state_2_probe_o)
        )
        if st["pair_bad"] is None and pairs != st["exp_pairs"]:
            st["pair_bad"] = f"clk{clk}:" + ",".join(
                "x" if p is None else f"0b{p:02b}" for p in pairs
            )

    async def _epoch(self, mask: int, value: int, walk: dict) -> None:
        """One inject epoch: raise the error on the pairs of ``mask`` at ``value``."""
        dut = cocotb.top
        n, sip, sys_ = walk["n"], walk["sip"], walk["sys"]
        await RisingEdge(dut.clk_i)
        await ReadOnly()
        pre_sigint = self._port("lcc_sigint_err_probe_o")
        v = dut.lcc_feat_ctrl_probe_o.value
        pre_feat = int(v) if v.is_resolvable else None
        await RisingEdge(dut.clk_i)
        self._set_pin(dut, "lc_sigint_pair_mask_i", mask)
        self._set_pin(dut, "lc_sigint_bad_value_i", value)
        self._set_pin(dut, "lc_sigint_inject_i", 1)
        applied, waited = None, None
        for k in range(SIGINT_BOUND + 1):
            await ReadOnly()
            if applied is None and self._dec_broken() == (mask, value):
                applied = k
            if waited is None and self._port("lcc_sigint_err_probe_o") == 1:
                waited = k
            if applied is not None and waited is not None:
                break
            await RisingEdge(dut.clk_i)
        st = {"stop": False, "clocks": 0, "bad": None, "pair_bad": None}
        st["exp_pairs"] = walk["exp_pairs"]
        task = None
        if waited is not None:
            self._epoch_sample(st)
            task = cocotb.start_soon(self._epoch_watch(st))
        await ClockCycles(dut.clk_i, EPOCH_HOLD)
        feat, probe = await self._feat()
        last = walk["last"] and (mask, value) == walk["final"]
        if last:
            dem_rb = {r: await self.fd.rd64(DEMOTE_ADDR[r]) for r in (1, 2)}
        await RisingEdge(dut.clk_i)
        await ReadOnly()
        dbg = {k: self._port(f"dbg_disable_{k}_o") for k in DBG_DISABLE_FIELDS}
        fuse = self._fuse_ports()
        pv = dut.lc_state_probe_o.value
        port = f"0x{int(pv):02x}" if pv.is_resolvable else str(pv)
        await RisingEdge(dut.clk_i)
        st["stop"] = True
        self._set_pin(dut, "lc_sigint_inject_i", 0)
        if task is not None:
            await task
        await RisingEdge(dut.clk_i)
        released = await wait_bit(self, "lcc_sigint_err_probe_o", 0, SIGINT_BOUND)

        self.walk_count += 1
        if applied is not None:
            self.applied += 1
        fail_row = feat_ctrl_profile(n, sip, sys_, sigint_err=1)
        cell = dict(
            n=f"0x{n:x}",
            mask=f"0x{mask:x}",
            value=value,
            demoted=walk["dem_label"],
        )
        self.chk.ok(
            "SIGINT",
            walk["ctl_ok"]
            and waited is not None
            and st["clocks"] > 0
            and st["bad"] is None
            and feat == fail_row.value
            and probe == fail_row.value,
            **cell,
            role=walk["role"],
            clocks=st["clocks"],
            first_bad=st["bad"] or "none",
            exp_feat=f"0x{fail_row.value:x}",
            got_feat=f"0x{feat:x}",
            got_probe=f"0x{probe:x}",
            sigint_wait_clks=waited if waited is not None else "timeout",
            applied_clks=applied if applied is not None else "none",
            pre_sigint=pre_sigint,
            pre_feat="x" if pre_feat is None else f"0x{pre_feat:016x}",
            ctl=walk["ctl"],
            src=fail_row.source,
        )
        self.chk.ok(
            "SIGINT-PAIRS",
            walk["pair_ctl_ok"] and st["clocks"] > 0 and st["pair_bad"] is None,
            **cell,
            clocks=st["clocks"],
            exp=",".join(f"0b{p:02b}" for p in walk["exp_pairs"]),
            first_bad=st["pair_bad"] or "none",
            ctl=walk["pair_ctl"],
        )
        self.chk.obs("LC-PORT-SIGINT", **cell, port=port, legal=f"0x{(~n & 0xF) << 4 | n:02x}")
        tag = f"{mask:x}/{value}/{walk['dem_label']}"
        self.epoch_fuse.append((tag, fuse))
        self.epoch_dbg.append((tag, dbg))
        if last:
            exp = walk["dem_written"]
            before = walk["dem_before"]
            self.chk.ok(
                "SIGINT-DEMOTE-REG",
                all(dem_rb[r] == exp[r] and before[r] == exp[r] for r in (1, 2)),
                **cell,
                exp_1=f"0x{exp[1]:016x}",
                got_1=f"0x{dem_rb[1]:016x}",
                before_1=f"0x{before[1]:016x}",
                exp_2=f"0x{exp[2]:016x}",
                got_2=f"0x{dem_rb[2]:016x}",
                before_2=f"0x{before[2]:016x}",
                wr_resp=",".join(str(walk["dem_resp"][r]) for r in (1, 2)),
            )
        if not self.release_logged:
            self.release_logged = True
            await RisingEdge(dut.clk_i)
            rel_feat, rel_probe = await self._feat()
            self.chk.obs(
                "LC-SIGINT-RELEASE",
                **cell,
                release_clks=released if released is not None else "none",
                sigint=self._port("lcc_sigint_err_probe_o"),
                feat=f"0x{rel_feat:016x}",
                probe=f"0x{rel_probe:016x}",
            )

    def _dec_broken(self) -> tuple[int, int | str] | None:
        """Broken pairs at the lifecycle decoder input: (pair mask, rail value).

        Pair i is ``{data_i[pairs + i], data_i[i]}``; a broken pair has equal rails.
        The value is ``mixed`` when broken pairs differ in rail value.
        """
        v = self.dec_in.value
        if not v.is_resolvable:
            return None
        pairs = len(self.dec_in) // 2
        d = int(v)
        lo, hi = d & ((1 << pairs) - 1), d >> pairs
        broken = ~(lo ^ hi) & ((1 << pairs) - 1)
        rails = {(lo >> i) & 1 for i in range(pairs) if (broken >> i) & 1}
        return broken, (rails.pop() if len(rails) == 1 else "mixed")

    async def _walk(self, walk: dict) -> None:
        pairs = len(cocotb.top.lc_state_probe_o) // 2
        order = [(m, v) for m in range(1, 1 << pairs) for v in BAD_VALUES]
        self.epochs_exp += len(order)
        self.rng.shuffle(order)
        walk["final"] = order[-1]
        self.chk.info(
            "SIGINT-WALK",
            demoted=walk["dem_label"],
            order=",".join(f"{m:x}/{v}" for m, v in order),
        )
        for mask, value in order:
            await self._epoch(mask, value, walk)

    async def _set_demotion(self) -> dict:
        """Write the drawn demotion with one ``rsvd`` marker bit in each register."""
        await RisingEdge(cocotb.top.clk_i)
        dsel = self.rng.choice(DEMOTE_SETS)
        written = {
            r: (DEMOTE_BIT if dsel[r - 1] else 0) | (1 << self.rng.choice(RSVD_BITS))
            for r in (1, 2)
        }
        resp = {
            r: await self.fd.wr_graded_by_readback(DEMOTE_ADDR[r], written[r], length=8)
            for r in (1, 2)
        }
        before = {r: await self.fd.rd64(DEMOTE_ADDR[r]) for r in (1, 2)}
        await RisingEdge(cocotb.top.clk_i)
        await ReadOnly()
        pairs = self._pairs()
        await RisingEdge(cocotb.top.clk_i)
        label = {(1, 0): "d1", (0, 1): "d2", (1, 1): "d1d2"}[dsel]
        return {
            "dsel": dsel,
            "label": label,
            "written": written,
            "resp": resp,
            "before": before,
            "pairs": pairs,
        }

    async def _legs_a_b(self, n: int, sip: int, sys_: int) -> None:
        dut = cocotb.top
        role = "control" if n == NIBBLE_CONTROL else "new"
        ctl_row = feat_ctrl_profile(n, sip, sys_)
        self.logger.info("GOLDEN ctl n=0x%x %s value=0x%016x", n, ctl_row.log(), ctl_row.value)
        ctl_feat, ctl_probe = await self._feat()
        ctl_sigint = bit(self, "lcc_sigint_err_probe_o")
        ref_pairs = self._pairs()
        ctl_ok = (
            ctl_row.value != 0
            and ctl_feat == ctl_row.value
            and ctl_probe == ctl_row.value
            and ctl_sigint == 0
        )
        ctl = (
            f"feat=0x{ctl_feat:016x},probe=0x{ctl_probe:016x},"
            f"exp=0x{ctl_row.value:016x},sigint={ctl_sigint},row={ctl_row.row}"
        )

        # Leg A, inject walks. The 0111 cell of leg A is a control and is not
        # credited, so its window opens at leg B.
        if role == "new":
            open_graded_window(TEST, self.logger)
        self.walk_count = 0
        self.applied = 0
        self.epochs_exp = 0
        self.dec_in = dut.u_dut.u_sep.u_sep_crypto.u_sep_lifecycle_ctrl.u_lc_state_dec.data_i
        self.epoch_fuse: list[tuple[str, dict]] = []
        self.epoch_dbg: list[tuple[str, dict]] = []
        self.release_logged = False
        walk = {
            "n": n,
            "sip": sip,
            "sys": sys_,
            "role": role,
            "ctl_ok": ctl_ok,
            "ctl": ctl,
            "dem_label": "none",
            "exp_pairs": ref_pairs,
            "pair_ctl_ok": True,
            "pair_ctl": "undemoted",
            "last": False,
        }
        await self._walk(walk)

        d = await self._set_demotion()
        pair_ctl_ok = all(
            (d["pairs"][r - 1] != ref_pairs[r - 1]) == bool(d["dsel"][r - 1]) for r in (1, 2)
        )
        self.chk.obs(
            "DEMOTE-PAIR-LEVEL",
            demoted=d["label"],
            undemoted_1=f"0b{ref_pairs[0]:02b}",
            undemoted_2=f"0b{ref_pairs[1]:02b}",
            level_1=f"0b{d['pairs'][0]:02b}",
            level_2=f"0b{d['pairs'][1]:02b}",
        )
        walk.update(
            dem_label=d["label"],
            exp_pairs=d["pairs"],
            pair_ctl_ok=pair_ctl_ok,
            pair_ctl=(
                f"ref={ref_pairs[0]:02b}{ref_pairs[1]:02b},"
                f"demoted={d['pairs'][0]:02b}{d['pairs'][1]:02b},sel={d['label']}"
            ),
            dem_written=d["written"],
            dem_before=d["before"],
            dem_resp=d["resp"],
            last=True,
        )
        await self._walk(walk)
        self.chk.ctrl(
            "SIGINT-EPOCHS",
            self.applied == self.epochs_exp,
            count=self.applied,
            exp=self.epochs_exp,
            epochs=self.walk_count,
        )

        # Leg B: SEC_DIS over the integrity error on every pair, then a mismatch.
        open_graded_window(TEST, self.logger)
        await RisingEdge(dut.clk_i)
        self._set_pin(dut, "lc_sigint_pair_mask_i", 0)
        self._set_pin(dut, "lc_sigint_bad_value_i", 0)
        self._set_pin(dut, "lc_sigint_inject_i", 1)
        if await wait_bit(self, "lcc_sigint_err_probe_o", 1, SIGINT_BOUND) is None:
            hook_fail(
                self.chk,
                n=f"0x{n:x}",
                reason="lcc_sigint_err_probe_o stayed 0 under the leg B inject",
                bound=SIGINT_BOUND,
            )
        await RisingEdge(dut.clk_i)
        code_m, reads_m = await sec_dis_go(self.fd, TOKEN_ZERO, CODE_MATCH, max_reads=MATCH_READS)
        rose = await wait_bit(self, "lcc_security_disable_probe_o", 1, SDIS_BOUND)
        if code_m != CODE_MATCH or rose is None:
            hook_fail(
                self.chk,
                n=f"0x{n:x}",
                reason="security_disable_o did not rise on the TOKEN_ZERO match",
                code=f"0x{(code_m or 0):02x}",
                reads=reads_m,
            )
        await RisingEdge(dut.clk_i)
        on_feat, _on_probe = await self._feat()
        on_sigint = bit(self, "lcc_sigint_err_probe_o")
        on_sdis = bit(self, "lcc_security_disable_probe_o")
        opened = self._fuse_ports()
        opened_dbg = {k: self._port(f"dbg_disable_{k}_o") for k in DBG_DISABLE_FIELDS}
        on_row = feat_ctrl_profile(n, sip, sys_, sec_dis=1, sigint_err=1)
        code_mm, reads_mm = await sec_dis_go(
            self.fd, TOKEN_OTHER, CODE_MISMATCH, max_reads=MATCH_READS
        )
        off_feat, _off_probe = await self._feat()
        off_sigint = bit(self, "lcc_sigint_err_probe_o")
        off_row = feat_ctrl_profile(n, sip, sys_, sec_dis=0, sigint_err=1)
        self.chk.ok(
            "SIGINT-SECDIS",
            on_row.value == ALL_ONES
            and on_feat == on_row.value
            and on_sigint == 1
            and on_sdis == 1
            and code_mm == CODE_MISMATCH
            and off_feat == off_row.value
            and off_sigint == 1,
            n=f"0x{n:x}",
            demoted=d["label"],
            got_feat=f"0x{on_feat:016x}",
            sigint=on_sigint,
            sdis=on_sdis,
            after_mismatch=f"0x{off_feat:x}",
            after_mismatch_sigint=off_sigint,
            code_match=f"0x{code_m:02x}",
            code_mismatch=f"0x{(code_mm or 0):02x}",
            mismatch_reads=reads_mm,
            src=on_row.source,
        )
        self._dbg_class(opened_dbg, on_sdis)
        self._fuse_class(opened, on_sdis)
        close_graded_window(self.logger)
        self._set_pin(dut, "lc_sigint_inject_i", 0)
        await RisingEdge(dut.clk_i)
        self._set_pin(dut, "lc_sigint_pair_mask_i", 0)
        await self._cold_reset()

    def _dbg_class(self, opened: dict, open_sdis: int) -> None:
        """Gated ``dbg_disable`` ports: 1 in every epoch, 0 under the leg B match."""
        bad = [
            f"{tag}:" + ",".join(f"{k}={d[k]}" for k in GATED_DBG if d[k] != 1)
            for tag, d in self.epoch_dbg
            if any(d[k] != 1 for k in GATED_DBG)
        ]
        open_bad = [f"{k}={opened[k]}" for k in GATED_DBG if opened[k] != 0]
        self.chk.ok(
            "DBG-DISABLE",
            open_sdis == 1 and not open_bad and len(self.epoch_dbg) == self.epochs_exp and not bad,
            stage="sigint",
            gated=len(GATED_DBG),
            epochs=len(self.epoch_dbg),
            mismatches=len(bad),
            first_bad=bad[0] if bad else "none",
            open_ctl_bad=",".join(open_bad) or "none",
        )

    def _fuse_class(self, opened: dict, open_sdis: int) -> None:
        """Each fuse DFT port under the error against its same-leaf controls."""
        closed = self.closed_ctl
        presense_ok = closed["sense_done"] == 0 and closed["sdis"] == 0 and open_sdis == 1
        self.chk.obs(
            "DTP-PORT-LEVEL",
            stage="sigint",
            sep_open=opened["sep"],
            sep_closed=closed["sep"],
            smc_open=opened["smc"],
            smc_closed=closed["smc"],
        )
        for k in FUSE_PORTS:
            bad = [tag for tag, f in self.epoch_fuse if f[k] is None or f[k] != closed[k]]
            self.chk.ok(
                "FUSE-DFT-CLASS",
                presense_ok
                and closed[k] is not None
                and opened[k] is not None
                and closed[k] != opened[k]
                and len(self.epoch_fuse) == self.epochs_exp
                and not bad,
                stage="sigint",
                port=FUSE_PORTS[k],
                closed=closed[k],
                open=opened[k],
                epochs=len(self.epoch_fuse),
                mismatches=len(bad),
                first_bad=bad[0] if bad else "none",
                closed_sense_done=closed["sense_done"],
                closed_sdis=closed["sdis"],
                closed_clk=closed["clk"],
            )

    # -- leg C ---------------------------------------------------------------

    async def _jtag(self, *, write: bool, addr: int, wdata: int = 0) -> tuple[int, int]:
        return await self.jtag_axil_op(write=write, addr=addr, wdata=wdata)

    async def _leg_c(self, leg: dict, sip_staged: int) -> None:
        dut = cocotb.top
        word = leg["jtag_shadow_word"]
        shadow = SHADOW_BASE + 4 * word
        ctl_bit, drawn_bit = leg["ctl_bit"], leg["drawn_bit"]
        c1, c2 = leg["c1"], leg["c2"]
        sip_addr = shadow_addr("SIP_DIS")

        # Control epoch, no inject.
        probe0 = bit(self, "jtag_filter_lc_sigint_err_probe_o")
        r_sh, _ = await self._jtag(write=False, addr=shadow)
        r_pg, _ = await self._jtag(write=False, addr=PROGRAM_CTRL_ADDR)
        r_wr, _ = await self._jtag(
            write=True, addr=shadow_addr("SIP_DIS", ctl_bit // 32), wdata=1 << (ctl_bit % 32)
        )
        sip_ctl = await self.fd.rd64(sip_addr)
        r_cw, _ = await self._jtag(write=True, addr=READ_TIMEOUT, wdata=c1)
        cw = await self.fd.rd(READ_TIMEOUT)
        ctl_bit_set = (sip_ctl >> ctl_bit) & 1 == 1 and (sip_ctl >> drawn_bit) & 1 == 0
        ctl_cw_landed = cw & READ_TIMEOUT_FIELDS == c1
        ctl_ok = self.chk.ctrl(
            "JTAG-SIGINT-CONTROL",
            probe0 == 0
            and (r_sh, r_pg, r_wr, r_cw) == (OKAY, OKAY, OKAY, OKAY)
            and ctl_bit_set
            and ctl_cw_landed
            and sip_ctl == sip_staged | (1 << ctl_bit),
            filter_err=probe0,
            shadow_word=word,
            resp_shadow=r_sh,
            resp_program_ctrl=r_pg,
            resp_sip_wr=r_wr,
            resp_cw=r_cw,
            sip_dis=f"0x{sip_ctl:016x}",
            ctl_bit=ctl_bit,
            drawn_bit=drawn_bit,
            cw=f"0x{cw:08x}",
            c1=f"0x{c1:07x}",
        )
        ctl = {
            "ctl_resp": "OKAY" if (r_sh, r_pg) == (OKAY, OKAY) else "ERR",
            "ctl_wr_resp": "OKAY" if r_wr == OKAY else "ERR",
            "ctl_bit_set": ctl_bit_set,
            "ctl_cw_resp": "OKAY" if r_cw == OKAY else "ERR",
            "ctl_cw_landed": ctl_cw_landed,
        }

        # Injection epoch.
        open_graded_window(TEST, self.logger)
        self._set_pin(dut, "jtag_filter_lc_sigint_inject_i", 1)
        waited = await wait_bit(self, "jtag_filter_lc_sigint_err_probe_o", 1, SIGINT_BOUND)
        if waited is None:
            close_graded_window(self.logger)
            hook_fail(
                self.chk,
                reason="jtag_filter_lc_sigint_err_probe_o stayed 0 under the inject",
                bound=SIGINT_BOUND,
            )
        self.chk.obs("LC-SIGINT-FILTER", lc_sigint_err=bit(self, "lcc_sigint_err_probe_o"))
        sip_before = await self.fd.rd64(sip_addr)

        def line(tgt: str, op: str, exp: str, resp: int, ok: bool, sip_now: int, **extra) -> None:
            err = bit(self, "jtag_filter_lc_sigint_err_probe_o")
            good = resp == OKAY if exp == "allow" else resp != OKAY
            self.chk.ok(
                "JTAG-SIGINT",
                ctl_ok and err == 1 and good and ok,
                filter_err=err,
                tgt=tgt,
                op=op,
                exp=exp,
                resp=resp,
                sip_dis_before=f"0x{sip_ctl:016x}",
                sip_dis_after=f"0x{sip_now:016x}",
                **extra,
                **ctl,
            )

        resp, _ = await self._jtag(write=False, addr=shadow)
        line("shadow", "rd", "deny", resp, True, sip_before, addr=f"0x{shadow:08x}")
        resp, _ = await self._jtag(write=False, addr=PROGRAM_CTRL_ADDR)
        line("ifctl", "rd", "deny", resp, True, sip_before, addr=f"0x{PROGRAM_CTRL_ADDR:08x}")

        resp, _ = await self._jtag(
            write=True, addr=shadow_addr("SIP_DIS", drawn_bit // 32), wdata=1 << (drawn_bit % 32)
        )
        sip_after = await self.fd.rd64(sip_addr)
        line(
            "shadow",
            "wr",
            "deny",
            resp,
            sip_after == sip_ctl and sip_before == sip_ctl and (sip_after >> drawn_bit) & 1 == 0,
            sip_after,
            addr=f"0x{sip_addr:08x}",
            drawn_bit=drawn_bit,
        )

        resp, _ = await self._jtag(write=True, addr=READ_TIMEOUT, wdata=c2)
        cw_after = await self.fd.rd(READ_TIMEOUT)
        line(
            "ifctl",
            "wr",
            "deny",
            resp,
            cw_after & READ_TIMEOUT_FIELDS == c1,
            sip_after,
            addr=f"0x{READ_TIMEOUT:08x}",
            reg=f"0x{cw_after & READ_TIMEOUT_FIELDS:08x}",
            exp_reg=f"0x{c1:08x}",
        )

        words = token_words(TOKEN_OTHER)
        order = leg["token_order"]
        for k in order:
            addr = TOKEN_ARRAY_ADDR[CH_SIP][k]
            resp, _ = await self._jtag(write=True, addr=addr, wdata=words[k])
            line("token_word", "wr", "allow", resp, True, sip_after, addr=f"0x{addr:08x}", index=k)
        first = TOKEN_ARRAY_ADDR[CH_SIP][order[0]]
        resp, data = await self._jtag(write=False, addr=first)
        line(
            "token_word",
            "rd",
            "allow",
            resp,
            True,
            sip_after,
            addr=f"0x{first:08x}",
            data=f"0x{data:08x}",
        )
        resp, _ = await self._jtag(write=True, addr=TOKEN_EOP_ADDR, wdata=GO_MASK[CH_SIP])
        line("eop", "wr", "allow", resp, True, sip_after, addr=f"0x{TOKEN_EOP_ADDR:08x}")
        await ClockCycles(dut.clk_i, 4)
        resp, data = await self._jtag(write=False, addr=MATCH_ADDR[CH_SIP])
        line(
            "match",
            "rd",
            "allow",
            resp,
            True,
            sip_after,
            addr=f"0x{MATCH_ADDR[CH_SIP]:08x}",
            data=f"0x{data & MATCH_STATUS_MASK:02x}",
        )

        close_graded_window(self.logger)
        self._set_pin(dut, "jtag_filter_lc_sigint_inject_i", 0)
        await self._cold_reset()

    # -- scenario ------------------------------------------------------------

    async def run_scenario(self) -> None:
        seed = self.random_seed()
        p = plan(TEST, seed)
        n = p.lc_raw
        for line in p.log_lines(n=f"0b{n:04b}"):
            self.logger.info("%s", line)
        self.chk = SepChkLog(self, TEST, seed)
        if p.setup_fail:
            raise AssertionError(f"SETUP FAIL seed={seed} reason={p.setup_fail}")
        leg_c = bool(p.leg["leg_c"])
        if leg_c:
            self.required_evidence = (*self.required_evidence, "CHK-JTAG-SIGINT")
        self.logger.info(
            "INFO-EVIDENCE-PLAN seed=%d required=%s", seed, ",".join(self.required_evidence)
        )
        close_graded_window(self.logger)
        self.fd = SepEfuseFd(self)
        self.rng = SepSeededRng(seed ^ _WALK_SALT)

        await chk_bind(self.chk)
        self.write_efuse_image(p.image)
        presense = cocotb.start_soon(self._presense_sample())
        await self.bring_up_no_cpu(max_cycles=SENSE_BOUND)
        self.closed_ctl = await presense
        await self._legs_a_b(n, p.sip_dis, p.sys_dis)

        if leg_c:
            await self._leg_c(p.leg, p.sip_dis)
        else:
            self.logger.info("CHK-JTAG-SIGINT N/A seed=%d n=0x%x", seed, n)
        self.chk.finish(f" n=0x{n:x}")
