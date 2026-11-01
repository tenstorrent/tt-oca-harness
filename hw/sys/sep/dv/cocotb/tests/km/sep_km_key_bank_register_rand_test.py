# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""KM-bus view of the key registers of the five engine wrappers.

no_cpu / lsu_stub_all_live / +skip_fuse_sense / +esrc_noise_force /
+km_rom_hex=km_rom_poke.parhex, Adams Bridge present. Seeded (``SepSeededRng``):
every draw is logged as ``DRAW``.

The KM CPU runs the POKE image (``tests/km_fw/km_rom_poke.S``), a legal master
of the KM bus that executes the op lists the host posts and stores what the DUT
returned in KM SRAM words 0 to 97 (``km_sram_probe_o``). The image grades
nothing. The register map and field masks come from the generated KM register
headers (``sep_km_key_bank_register_rand_plan.py``); the expected values come
from the register text: ``hw/ip/key_manager/doc/architecture.adoc`` ("Key
Delivery", "Adams Bridge Key Sideload Interfaces", "Key Manager CPU Interrupt
Processing"), ``hw/ip/key_manager/regs/gen/adoc/aes_wrapper_key.adoc`` and
``abr_wrapper_key.adoc``.

The host (LSU master) writes the engine ``SW_RESET_N`` bits and runs three
ML-KEM encapsulations on Adams Bridge. Each encapsulation takes its message
from the KV message lane (the image stages the two MLKEM_MSG shares and sets
their key_valid) and posts its shared key to the KM through the KV shared-key
write lane. The encapsulation key and the message are the published ML-KEM-1024
encapsulation vector (``env/sep_abr_kem_nist.py``), so the delivery is the same
on every seed and the shared key that reaches the KM is not all zero.

The last leg is the single-share delivery to AES
(``hw/sys/sep/doc/crypto.adoc:192-196``: both shares are always consumed, a
single written share delivers V because the unwritten share reads as zero, and
a Key Manager wipe clears KEY_VALID and both shares;
``hw/ip/key_manager/doc/architecture.adoc:503-509``: the wipe pulse clears both
shares and KEY_VALID of every sideload block). It brings up the
entropy stack so AES can run, then for share 0 and share 1 (order drawn): the
image writes both AES shares non-zero and sets KEY_VALID, the host pulses
``SEP_CPU_CTRL.KM_WIPE_CTRL.wipe_state``, the image writes only the drawn share
with K and sets KEY_VALID, and the host encrypts one block with AES-256 ECB
from the sideload key.

Checks (each anchored on a POKE readback or the POKE handler count):
  CHK-BANK-SHARES  all 136 share words read 0 after a non-zero write, key_valid 0
  CHK-BANK-VALID   KEY_CTRL.key_valid resets to 0, a write of 1 sets it (twice),
                   a write of 0 clears it, and no other bank moves
  CHK-BANK-SK      the encapsulation delivers the shared key: KEY_CTRL.key_valid 1,
                   IRQ_STATUS.key_valid sticky, kept by a write of 0, W1C
  CHK-BANK-SK-CONSUME  a write of 0 clears key_valid; a software write of 1
                   afterwards leaves it 0; both writes are accepted
  CHK-BANK-SK-SW   the 8 KEY words read 0 after the consume and after the
                   refused set
  CHK-BANK-SK-IRQ  with the enable 0 the handler count does not rise and the
                   status stays 1; with the enable 1 it rises; after the W1C it
                   stops and the status reads 0
  CHK-SINGLE-SHARE after the wipe and a write of one share with K, the sideload
                   ciphertext equals the AES-256 golden of K (whole 128 bits);
                   in the same line KEY_VALID reads 1 before the wipe, 0 after
                   it and 1 after the share write, and every write is accepted

Controls: the non-zero, accepted write of each share word before its read; the
vector 0 after the share reads; the status and key_valid 0 before each delivery;
key_valid 1 and live words before the consume; the normal-bank set next to the
refused shared-key set; the enabled window of the same length as the masked
and cleared windows; the two-share delivery with share0 XOR share1 = K gives
the AES-256 golden of K (``CTRL-SS-BOTH-SHARES``, the engine consumes both
shares).

Open-value leg (logged, not graded; each control fails the leaf), after the
single-share instances. The host writes the AES share0 with a key K and share1
with 0, write-locks KM SRAM region 1, sets ``SRAM_EXEC_MODE.enable`` and posts
a POKE JUMP into a snippet staged in that region. The snippet stores one drawn
byte (``sb``) and one drawn halfword (``sh``) at byte offset 0 of two drawn
share0 words, sets KEY_VALID, saves KMCSR IRQ_STATUS, KEY_CTRL and a marker
to KM SRAM words 95 to 97 and spins: the first fetch from locked SRAM engages
the ROM lockout, so the snippet cannot return to the POKE image. The host then
encrypts one block from the sideload key. The draws come from their own
``SepSeededRng`` stream (the run seed XOR a leg salt), so the plan draws keep
their seed mapping.
  CTRL-BANK-SUBWORD  per size (byte, half): the KM AXI-adapter write capture
                   (``km_axi_wr_addr_o``, ``km_axi_wr_strb_o``) shows a write
                   to the share word with strobe 0x1 (byte) or 0x3 (half), and
                   the snippet marker reads back.
  OBS-BANK-SUBWORD the ciphertext against the AES-256 goldens of each
                   per-word outcome: ``merged`` (only the strobed lanes take the
                   value), ``whole`` (the word takes the bus data, the value
                   repeated across the lanes), ``ignored`` (K stays); with
                   IRQ_STATUS, KEY_CTRL and the sub-word count. Neither
                   ``architecture.adoc`` ("Key Delivery") nor
                   ``aes_wrapper_key.rdl`` states a strobe rule for the share
                   words.

Shards (``env/sep_shard.py``): without ``+sep_shard`` the leaf runs every leg.
``+sep_shard=1`` runs steps 2 to 7. ``+sep_shard=2`` runs steps 2 to 7 and
the single-share leg; its step 6 grades CHK-BANK-SK-CONSUME and logs the KEY
words (``OBS-SK-WORDS``) without CHK-BANK-SK-SW.

Logged only: the share-read responses and reserved KEY_CTRL bits; the 8
shared-key words (``OBS-SK-WORDS``; the leaf has no graded golden for them);
the bank state after each engine ``SW_RESET_N`` reset (``OBS-BANK-RST``; no
sentence states that the engine reset clears the KM-side key registers); the
bank state after a KM PARK (``OBS-KM-PARK``; not stated).
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge
from env import sep_km_poke as kp
from env.sep_abr_kem_nist import NIST_KEM_ENC_C, NIST_KEM_ENC_EK, NIST_KEM_ENC_K
from env.sep_aes_golden import aes256_ecb_encrypt_words
from env.sep_axi_agent import SepAxiOp
from env.sep_chk_log import SepChkLog
from env.sep_fcov_gate import (
    KM_SK_PASS_CONSUME,
    KM_SK_PASS_IRQ,
    KM_SK_PASS_WORDS,
    close_graded_window,
    open_graded_window,
    set_km_sk_pass,
    set_km_ss_pass,
    set_open_value_leg_pass,
)
from env.sep_reg_meta import SEP_CPU_CTRL
from env.sep_rv32_asm import Asm, lw, store, sw
from env.sep_seeded_rng import SepSeededRng
from env.sep_shard import sep_shard
from km import sep_km_key_bank_register_rand_plan as pl
from sep_base_test import sep_base_test
from seq_lib.sep_abr_mlkem_seq import (
    KEM_CMD_ENCAPS,
    KEM_CTRL_ZEROIZE,
    KEM_ST_ERROR,
    KEM_ST_READY,
    KEM_ST_VALID,
    KV_READ_EN,
    KV_WRITE_EN,
    MLKEM_CIPHERTEXT,
    MLKEM_CTRL,
    MLKEM_ENCAPS_KEY,
    MLKEM_KV_MSG_RD_CTRL,
    MLKEM_KV_MSG_RD_STATUS,
    MLKEM_KV_SK_WR_CTRL,
    MLKEM_STATUS,
    SepAbrMlkem,
)
from seq_lib.sep_aes_seq import SepAes
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_km_poke_seq import SepKmPoke
from seq_lib.sep_sw_reset_seq import SW_RESET_N_BIT, SepSwReset

TEST = "sep_km_key_bank_register_rand_test"

_SEP_RESET_BOUND = 20_000  # clocks for dbg_sep_reset_n_o to read 1
_SK_POLL_LOADS = 4_000  # loads of the bounded wait for the shared-key key_valid
_QUIET_OPS = 4  # quiet window of the interrupt gate: delay(_QUIET_OPS)
_ISO_BOUND = 20_000  # clocks for a KM-ISO probe to read isolated
_HOLD_CLKS = 200  # hold of an AES or OTBN reset (no KM-ISO probe)
_ISO_EXTRA_CLKS = 20  # hold after a KM-ISO probe reads isolated, for the reset to assert
_SETTLE_CLKS = 20  # clocks after the release of an engine reset
_PARK_HOLD_CLKS = 200  # hold of the KM PARK
_KEM_POLL_ITERS = 20_000
_KEM_POLL_GAP = 200
_CT_PREFIX = 4  # ciphertext words logged against the vector
_WIPE_HOLD_CLKS = 16  # clocks KM_WIPE_CTRL.wipe_state is held at 1
_LABEL_CLKS = 2  # clocks after a pass-label write, so the sampler sees its rise

# Sub-word leg: snippet region, result words, marker, bounds and leg salt.
_SUBWORD_REGION = 1
_SUBWORD_REGION_BYTES = 0x400  # km_csr.adoc, SRAM_LOCK: one bit per 1 KB region
_W_SUBWORD = 95  # 95 IRQ_STATUS, 96 KEY_CTRL, 97 marker
_SUBWORD_MARK = 0x5357_0001  # host-chosen; never a DUT value
_SUBWORD_BOUND = 20_000  # clocks for the snippet marker
_SUBWORD_SALT = 0x5342_5744
_SUBWORD_SIZES = (("byte", 1, 0x1, 0xFF, 0x0101_0101), ("half", 2, 0x3, 0xFFFF, 0x0001_0001))
_KMCSR_IRQ_STATUS = pl.KM.KMCSR_IRQ_STATUS_REG_ADDR
_KMCSR_SRAM_LOCK = pl.KM.KMCSR_SRAM_LOCK_REG_ADDR
_KMCSR_SRAM_EXEC_MODE = pl.KM.KMCSR_SRAM_EXEC_MODE_REG_ADDR
_SRAM_EXEC_ENABLE = 0x1  # km_csr.adoc, SRAM_EXEC_MODE.enable

_KM_WIPE_CTRL = SEP_CPU_CTRL.addr("KM_WIPE_CTRL")
_KM_WIPE_BIT = SEP_CPU_CTRL.field_mask("KM_WIPE_CTRL", "wipe_state")

_STEPS_EVIDENCE = (
    "CHK-BANK-SHARES",
    "CHK-BANK-VALID",
    "CHK-BANK-SK",
    "CHK-BANK-SK-CONSUME",
    "CHK-BANK-SK-SW",
    "CHK-BANK-SK-IRQ",
)
_SHARD_EVIDENCE = {
    1: _STEPS_EVIDENCE,
    2: (
        "CHK-BANK-SHARES",
        "CHK-BANK-VALID",
        "CHK-BANK-SK",
        "CHK-BANK-SK-CONSUME",
        "CHK-BANK-SK-IRQ",
        "CHK-SINGLE-SHARE",
    ),
}

_ALL_SW = sum(1 << b for b in SW_RESET_N_BIT.values())


def _h(v: int) -> str:
    return f"0x{v:08x}"


def _v(v: int) -> str:
    return f"0x{v:02x}"


def _flags_ok(f: kp.SlotFlags | None) -> bool:
    return f is not None and f.clean and f.slv == 0 and f.dec == 0


def _ok(r: kp.PokeResult) -> bool:
    """Every reporting slot of ``r`` was clean before and answered with no error."""
    flags = [f for f in r.flags if f is not None]
    return bool(flags) and all(_flags_ok(f) for f in flags)


def _ctrl_ops() -> list[kp.PokeOp]:
    return [kp.rd(b.ctrl) for b in pl.BANKS]


def _set_all_ops() -> list[kp.PokeOp]:
    return [kp.wr(b.ctrl, b.valid_mask) for b in pl.BANKS]


def _state_ops(words: bool) -> list[kp.PokeOp]:
    """The eight KEY_CTRL, the shared-key KEY_CTRL and IRQ_STATUS (and KEY[0..7])."""
    ops = _ctrl_ops() + [kp.rd(pl.SK_CTRL), kp.rd(pl.SK_IRQ_STATUS)]
    if words:
        ops.append(kp.rdblk(pl.SK_KEY[0], len(pl.SK_KEY)))
    return ops


def _decode_state(res: list[kp.PokeResult]) -> dict:
    vals = {b.bit: res[i].value for i, b in enumerate(pl.BANKS)}
    n = pl.N_BANKS
    out = {
        "vec": pl.vector(vals),
        "rsvd": pl.rsvd_bits(vals),
        "sk_valid": int(bool(res[n].value & pl.SK_VALID)),
        "sk_irq": int(bool(res[n + 1].value & pl.SK_IRQ)),
        "ok": all(_ok(r) for r in res),
    }
    if len(res) > n + 2:
        out["sk_words"] = tuple(res[n + 2].data)
    return out


def _stage_msg_ops(plan: pl.Plan) -> list[kp.PokeOp]:
    s0, s1 = plan.msg_stage()
    m = pl.MSG_BANK
    return [kp.wrblk(m.share0[0], s0), kp.wrblk(m.share1[0], s1), kp.wr(m.ctrl, m.valid_mask)]


@pyuvm.test()
class sep_km_key_bank_register_rand_test(sep_base_test):
    """KM-bus view of the wrapper key registers and the ML-KEM shared-key block."""

    required_evidence = (*_STEPS_EVIDENCE, "CHK-SINGLE-SHARE")

    # ------------------------------------------------------------------ main

    async def run_scenario(self) -> None:
        seed = self.random_seed()
        self.logger.info("SEED seed=%d", seed)
        shard = sep_shard(self, _SHARD_EVIDENCE)
        self.chk = SepChkLog(self, TEST, seed)
        self.failed = False
        self.plan = pl.draw_plan(seed)
        for line in pl.draw_lines(self.plan):
            self.logger.info(line)
        self.chk.info(
            "RSVD-MASKS",
            key_valid=[_h(b.valid_mask) for b in pl.BANKS],
            sk_valid=_h(pl.SK_VALID),
            sk_irq=_h(pl.SK_IRQ),
            sk_irq_en=_h(pl.SK_IRQ_EN),
        )
        self.dut = cocotb.top

        # Step 1: bring-up with fuse sense skipped, KM release, start marker.
        await self.bring_up_no_cpu()
        self.kem = SepAbrMlkem(self)
        self.swrst = SepSwReset(self)
        self.poke = SepKmPoke(self)
        await self._wait_sep_reset_n()
        await self.poke.release()
        await self.poke.wait_boot()
        sw = await self.swrst.read_back()
        if sw & _ALL_SW != _ALL_SW:
            raise AssertionError(
                f"SW_RESET_N reads {_h(sw)} after the KM release; every engine and the KM "
                f"must be out of reset (bits {_h(_ALL_SW)})"
            )
        self.swrst.value = sw
        self.logger.info("LOG sw_reset_n=%s after the KM release", _h(sw))

        self._open()
        await self._reset_vector()
        await self._shares()
        await self._valid_walk()
        await self._encaps1()
        await self._consume(grade_words=shard != 2)
        await self._irq_gate()
        close_graded_window(self.logger)

        if shard is None:
            await self._all_set()
            await self._engine_resets()
            await self._park()
        if shard != 1:
            await self._single_share()

        if not (self.swrst.value >> SW_RESET_N_BIT["km"]) & 1:
            await self.swrst.release("km")
        self.chk.finish()

    # ------------------------------------------------------------ plumbing

    def _open(self) -> None:
        """Open the coverage window, unless a check or control already failed."""
        if not self.failed:
            open_graded_window(TEST, self.logger)

    def _grade(self, name: str, cond: bool, **fields) -> bool:
        """``chk.ok`` that closes the coverage window on the first FAIL."""
        res = self.chk.ok(name, cond, **fields)
        if not cond:
            self.failed = True
            close_graded_window(self.logger)
        return res

    def _control(self, name: str, cond: bool, **fields) -> bool:
        """``chk.ctrl`` that closes the coverage window on the first miss."""
        res = self.chk.ctrl(name, cond, **fields)
        if not cond:
            self.failed = True
            close_graded_window(self.logger)
        return res

    async def _wait_sep_reset_n(self) -> None:
        for _ in range(_SEP_RESET_BOUND):
            await RisingEdge(self.dut.clk_i)
            if self.rd(self.dut.dbg_sep_reset_n_o, allow_unknown=True):
                return
        raise AssertionError(f"dbg_sep_reset_n_o did not read 1 within {_SEP_RESET_BOUND} clocks")

    async def _run(self, ops, *, on_sync=None) -> list[kp.PokeResult]:
        return await self.poke.run(ops, on_sync=on_sync)

    async def _run_items(self, items) -> None:
        """Pack (ops, handler) items into lists that fit the POKE buffer and run them."""
        batch: list = []
        words = slots = 0

        async def flush() -> None:
            nonlocal batch, words, slots
            if not batch:
                return
            res = await self._run([op for ops, _ in batch for op in ops])
            pos = 0
            for ops, fn in batch:
                fn(res[pos : pos + len(ops)])
                pos += len(ops)
            batch, words, slots = [], 0, 0

        for ops, fn in items:
            w, s = kp.list_words(ops), kp.list_slots(ops)
            if batch and (words + w > kp.BUF_WORDS or slots + s > kp.N_SLOTS):
                await flush()
            batch.append((ops, fn))
            words += w
            slots += s
        await flush()

    @staticmethod
    def _poll_sk() -> kp.PokeOp:
        return kp.poll(pl.SK_CTRL, pl.SK_VALID, pl.SK_VALID, _SK_POLL_LOADS)

    def _need_delivery(self, r: kp.PokeResult, what: str) -> None:
        """A bounded wait that ran out fails the leaf; it is not a contract verdict."""
        if not r.data[0] & pl.SK_VALID:
            raise AssertionError(
                f"{what}: MLKEM_SHARED_KEY.KEY_CTRL.key_valid did not read 1 within "
                f"{r.data[1]} loads after the encapsulation (last {_h(r.data[0])})"
            )

    # -------------------------------------------- ML-KEM encapsulation (host)

    async def _kem_wait(self, mask: int, expect: int, what: str) -> int:
        for _ in range(_KEM_POLL_ITERS):
            st = await self.kem.rd32(MLKEM_STATUS)
            if (st & mask) == expect:
                return st
            if st & KEM_ST_ERROR:
                raise AssertionError(f"{what}: MLKEM_STATUS.ERROR set ({_h(st)})")
            await ClockCycles(self.dut.clk_i, _KEM_POLL_GAP)
        raise AssertionError(f"{what}: MLKEM_STATUS & 0x{mask:x} never 0x{expect:x}")

    async def _encaps(self, n: int) -> None:
        """One ENCAPS with the message from the KV lane and the shared key to the KM."""
        what = f"encapsulation {n}"
        await self.kem.wr32(MLKEM_CTRL, KEM_CTRL_ZEROIZE)
        await self._kem_wait(KEM_ST_VALID, 0, f"{what} zeroize VALID clear")
        await self._kem_wait(KEM_ST_READY, KEM_ST_READY, f"{what} zeroize READY")
        await self.kem.wr32(MLKEM_KV_MSG_RD_CTRL, KV_READ_EN)
        await self.kem.wr32(MLKEM_KV_SK_WR_CTRL, KV_WRITE_EN)
        await self.kem.write_words(MLKEM_ENCAPS_KEY, list(NIST_KEM_ENC_EK))
        await self.kem.wr32(MLKEM_CTRL, KEM_CMD_ENCAPS)
        st = await self._kem_wait(KEM_ST_VALID, KEM_ST_VALID, f"{what} VALID")
        if st & KEM_ST_ERROR:
            raise AssertionError(f"{what}: VALID with ERROR ({_h(st)})")
        ct = await self.kem.read_words(MLKEM_CIPHERTEXT, _CT_PREFIX)
        kv_st = await self.kem.rd32(MLKEM_KV_MSG_RD_STATUS)
        self.logger.info(
            "LOG encaps=%d ct_prefix_match_vector=%d kv_msg_rd_status=%s",
            n,
            int(list(ct) == list(NIST_KEM_ENC_C[:_CT_PREFIX])),
            _h(kv_st),
        )

    # ------------------------------------------------- step 2: reset values

    async def _reset_vector(self) -> None:
        res = await self._run(_ctrl_ops())
        vals = {b.bit: res[i].value for i, b in enumerate(pl.BANKS)}
        self.reset_vec = pl.vector(vals)
        self.reset_ok = all(_ok(r) for r in res)
        self.logger.info(
            "LOG reset_vector=%s rsvd=%s resp_ok=%d",
            _v(self.reset_vec),
            _h(pl.rsvd_bits(vals)),
            self.reset_ok,
        )

    # ------------------------------------------------- step 3: share words

    async def _shares(self) -> None:
        plan = self.plan
        wr_ok: dict[tuple[int, int], bool] = {}
        reads: dict[tuple[int, int], tuple[tuple[int, ...], tuple]] = {}

        def on_wr(key):
            def fn(res):
                wr_ok[key] = _ok(res[0])

            return fn

        def on_rd(key):
            def fn(res):
                reads[key] = (tuple(res[0].data), tuple(res[0].flags))

            return fn

        wr_items, rd_items = [], []
        for bit in plan.bank_order:
            b = pl.BANKS[bit]
            for s, base in enumerate((b.share0[0], b.share1[0])):
                wr_items.append(([kp.wrblk(base, plan.shares[bit][s])], on_wr((bit, s))))
                rd_items.append(([kp.rdblk(base, b.words)], on_rd((bit, s))))
        await self._run_items(wr_items)
        await self._run_items(rd_items)
        post = _decode_state(await self._run(_state_ops(words=False)))

        written = sum(
            sum(1 for w in plan.shares[bit][s] if w) for (bit, s), ok in wr_ok.items() if ok
        )
        zero = nonzero = resp_err = resp_slv = resp_dec = 0
        bad: list[str] = []
        for (bit, s), (data, flags) in sorted(reads.items()):
            for i, (d, f) in enumerate(zip(data, flags, strict=True)):
                if d == 0:
                    zero += 1
                else:
                    nonzero += 1
                    if len(bad) < 4:
                        bad.append(f"{pl.BANKS[bit].name}.s{s}[{i}]={_h(d)}")
                if not _flags_ok(f):
                    resp_err += 1
                if f is not None:
                    resp_slv += f.slv
                    resp_dec += f.dec
        # The specification states the read data of a share word (0) and not its
        # response, so the response is logged and not graded.
        self.chk.obs(
            "SHARE-READ-RESP",
            reads=zero + nonzero,
            resp_flagged=resp_err,
            slv=resp_slv,
            dec=resp_dec,
        )
        self._control(
            "SHARE-WRITES",
            written == pl.N_SHARE_WORDS and all(wr_ok.values()),
            nonzero_written=written,
            write_ops=len(wr_ok),
        )
        self._control("SHARES-VALID-0", post["vec"] == 0 and post["ok"], vector=_v(post["vec"]))
        self._grade(
            "BANK-SHARES",
            zero == pl.N_SHARE_WORDS and zero + nonzero == pl.N_SHARE_WORDS,
            words=zero + nonzero,
            nonzero_written=written,
            reads_zero=zero,
            first_nonzero=bad or "none",
        )

    # ------------------------------------------------- step 4: key_valid walk

    async def _valid_walk(self) -> None:
        set_ok = twice_ok = clear_ok = isolated = resp = True
        trail: list[str] = []
        for bit in self.plan.bank_order:
            b = pl.BANKS[bit]
            ops = (
                [kp.wr(b.ctrl, b.valid_mask)]
                + _ctrl_ops()
                + [kp.wr(b.ctrl, b.valid_mask)]
                + _ctrl_ops()
                + [kp.wr(b.ctrl, 0)]
                + _ctrl_ops()
            )
            res = await self._run(ops)
            n = pl.N_BANKS + 1
            vecs = []
            for k in range(3):
                part = res[k * n : (k + 1) * n]
                vecs.append(pl.vector({x.bit: part[1 + i].value for i, x in enumerate(pl.BANKS)}))
                resp &= all(_ok(r) for r in part)
            own = 1 << bit
            set_ok &= bool(vecs[0] & own)
            twice_ok &= bool(vecs[1] & own)
            clear_ok &= not vecs[2] & own
            isolated &= all(v & ~own == 0 for v in vecs)
            trail.append(f"{b.name}:{_v(vecs[0])}/{_v(vecs[1])}/{_v(vecs[2])}")
        self.walk_set_ok = set_ok
        self.logger.info("LOG valid_walk %s", " ".join(trail))
        self._grade(
            "BANK-VALID",
            self.reset_vec == 0
            and self.reset_ok
            and set_ok
            and twice_ok
            and clear_ok
            and isolated
            and resp,
            banks=pl.N_BANKS,
            reset=_v(self.reset_vec),
            set=set_ok,
            set_twice=twice_ok,
            clear=int(clear_ok),
            isolated=isolated,
            resp_ok=int(resp and self.reset_ok),
        )

    # ------------------------------------------------- step 5: encapsulation 1

    async def _encaps1(self) -> None:
        ops = [
            kp.wr(pl.SK_IRQ_STATUS, pl.SK_IRQ),  # 0
            kp.rd(pl.SK_IRQ_STATUS),  # 1 control: 0
            kp.wr(pl.SK_IRQ_ENABLE, 0),  # 2
            kp.rd(pl.SK_CTRL),  # 3 control: no key pending
            *_stage_msg_ops(self.plan),  # 4, 5, 6
            kp.sync(),  # 7
            self._poll_sk(),  # 8
            kp.rd(pl.SK_CTRL),  # 9
            kp.rdblk(pl.SK_KEY[0], len(pl.SK_KEY)),  # 10
            kp.rd(pl.SK_IRQ_STATUS),  # 11
            kp.rd(pl.SK_IRQ_STATUS),  # 12
            kp.wr(pl.SK_IRQ_STATUS, 0),  # 13
            kp.rd(pl.SK_IRQ_STATUS),  # 14
            kp.wr(pl.SK_IRQ_STATUS, pl.SK_IRQ),  # 15
            kp.rd(pl.SK_IRQ_STATUS),  # 16
        ]

        async def on_sync(_k: int) -> None:
            await self._encaps(1)

        r = await self._run(ops, on_sync=on_sync)
        self._need_delivery(r[8], "encapsulation 1")
        pre_irq = r[1].value & pl.SK_IRQ
        pre_valid = r[3].value & pl.SK_VALID
        stage_ok = all(_ok(x) for x in r[0:7])
        self._control(
            "SK-PRE1",
            pre_irq == 0 and pre_valid == 0 and stage_ok,
            irq_status=_h(r[1].value),
            key_ctrl=_h(r[3].value),
            stage_ok=stage_ok,
        )
        words = tuple(r[10].data)
        self.chk.obs(
            "SK-WORDS",
            phase="delivery1",
            words=[_h(w) for w in words],
            match_vector=list(words) == list(NIST_KEM_ENC_K),
        )
        valid = r[9].value & pl.SK_VALID
        irq1, irq2 = r[11].value & pl.SK_IRQ, r[12].value & pl.SK_IRQ
        kept = r[14].value & pl.SK_IRQ
        w1c = r[16].value & pl.SK_IRQ
        resp = all(_ok(x) for x in r[9:17])
        self._grade(
            "BANK-SK",
            bool(valid) and bool(irq1) and bool(irq2) and bool(kept) and not w1c and resp,
            valid=int(bool(valid)),
            irq_sticky=int(bool(irq1 and irq2)),
            zero_write="kept" if kept else "cleared",
            w1c=int(bool(w1c)),
            resp_ok=resp,
        )

    # ------------------------------------------------- step 6: consume

    async def _consume(self, *, grade_words: bool) -> None:
        """Consume the shared key and try a software set of key_valid.

        CHK-BANK-SK-CONSUME grades key_valid and the responses; its pass releases
        ``cp_sk_write_dir``. CHK-BANK-SK-SW grades the KEY words; shard 2 logs them.
        """
        n = len(pl.SK_KEY)
        set_km_sk_pass(0, self.logger)
        ops = [
            kp.rd(pl.SK_CTRL),  # 0 control: 1
            kp.rdblk(pl.SK_KEY[0], n),  # 1 control: live words
            kp.wr(pl.SK_CTRL, 0),  # 2 consume
            kp.rd(pl.SK_CTRL),  # 3
            kp.rdblk(pl.SK_KEY[0], n),  # 4
            kp.wr(pl.SK_CTRL, pl.SK_VALID),  # 5 software set of a hardware-owned bit
            kp.rd(pl.SK_CTRL),  # 6
            kp.rdblk(pl.SK_KEY[0], n),  # 7
        ]
        r = await self._run(ops)
        pre = tuple(r[1].data)
        self.chk.obs("SK-WORDS", phase="before_consume", words=[_h(w) for w in pre])
        self._control(
            "SK-PRE-CONSUME",
            bool(r[0].value & pl.SK_VALID) and any(pre) and _ok(r[0]) and _ok(r[1]),
            key_ctrl=_h(r[0].value),
            words_nonzero=sum(1 for w in pre if w),
        )
        self._control("SK-SW-TWIN", self.walk_set_ok, normal_bank_set=self.walk_set_ok)
        consume_zero = not r[3].value & pl.SK_VALID
        sw_ignored = not r[6].value & pl.SK_VALID
        resp = all(_ok(x) for x in r[2:8])
        passed = self._grade(
            "BANK-SK-CONSUME",
            consume_zero and sw_ignored and resp,
            consume_zero=consume_zero,
            sw_set_ignored=sw_ignored,
            key_ctrl_after_consume=_h(r[3].value),
            key_ctrl_after_set=_h(r[6].value),
            resp_ok=resp,
        )
        label = 0
        if passed:
            # Pass label: the sampler holds both cp_sk_write_dir cells from the
            # KEY_CTRL writes above and samples them on this rise.
            label = KM_SK_PASS_CONSUME
            set_km_sk_pass(label, self.logger)
            await ClockCycles(self.dut.clk_i, _LABEL_CLKS)
        if not grade_words:
            self.chk.obs("SK-WORDS", phase="after_consume", words=[_h(w) for w in r[4].data])
            self.chk.obs("SK-WORDS", phase="after_set", words=[_h(w) for w in r[7].data])
            return
        # Zeroize: the words read 0 after the consume and stay 0 after the
        # refused set.
        words_zero = not any(r[4].data) and not any(r[7].data)
        if self._grade(
            "BANK-SK-SW",
            words_zero,
            words_zero=words_zero,
            words_after_consume=[_h(w) for w in r[4].data],
            words_after_set=[_h(w) for w in r[7].data],
        ):
            # Pass label: releases cp_sk_delivery_state[firmware_consumes].
            set_km_sk_pass(label | KM_SK_PASS_WORDS, self.logger)
            await ClockCycles(self.dut.clk_i, _LABEL_CLKS)

    # ------------------------------------------------- step 7: interrupt gate

    async def _irq_gate(self) -> None:
        line = kp.IRQ_LINE_ABR_SK
        idle = self.plan.idle_ops
        # A change of the label drops the held cp_sk_interrupt line cells, so
        # only line events of this step can release on CHK-BANK-SK-IRQ.
        set_km_sk_pass(0, self.logger)
        ops = [
            kp.wr(pl.SK_IRQ_ENABLE, 0),  # 0
            kp.rd(pl.SK_IRQ_STATUS),  # 1 control: 0 (cleared in step 5)
            kp.rd(pl.SK_CTRL),  # 2 control: 0 (consumed in step 6)
            kp.arm([line]),  # 3
            *_stage_msg_ops(self.plan),  # 4, 5, 6
            kp.sync(),  # 7
            self._poll_sk(),  # 8
            kp.rd(pl.SK_IRQ_STATUS),  # 9 set while masked
            kp.cnt(line),  # 10
            kp.delay(_QUIET_OPS),  # 11
            kp.cnt(line),  # 12
            kp.rd(pl.SK_IRQ_STATUS),  # 13 still set after the masked window
            *[kp.nop() for _ in range(idle)],
            kp.wr(pl.SK_IRQ_ENABLE, pl.SK_IRQ_EN),
            kp.cnt(line),
            kp.delay(_QUIET_OPS),
            kp.cnt(line),
            kp.wr(pl.SK_IRQ_STATUS, pl.SK_IRQ),
            kp.cnt(line),
            kp.delay(_QUIET_OPS),
            kp.cnt(line),
            kp.rd(pl.SK_IRQ_STATUS),
            # Cleanup, not graded by a key_valid read: the window closes at this
            # sync, so the KEY_CTRL write of 0 below samples no shared-key point.
            kp.sync(),
            kp.wr(pl.SK_CTRL, 0),
            kp.wr(pl.SK_IRQ_ENABLE, 0),
            kp.disarm(),
        ]

        async def on_sync(k: int) -> None:
            if k == 0:
                await self._encaps(2)
            else:
                close_graded_window(self.logger)

        r = await self._run(ops, on_sync=on_sync)
        self._need_delivery(r[8], "encapsulation 2")
        e = 14 + idle  # index of the enable write
        self._control(
            "SK-PRE2",
            not r[1].value & pl.SK_IRQ
            and not r[2].value & pl.SK_VALID
            and all(_ok(x) for x in (r[0], r[1], r[2], r[4], r[5], r[6])),
            irq_status=_h(r[1].value),
            key_ctrl=_h(r[2].value),
        )
        set_masked = bool(r[9].value & pl.SK_IRQ) and bool(r[13].value & pl.SK_IRQ)
        en0 = r[12].value - r[10].value
        en1 = r[e + 3].value - r[e + 1].value
        after = r[e + 7].value - r[e + 5].value
        cleared = not r[e + 8].value & pl.SK_IRQ
        resp = all(_ok(x) for x in (r[9], r[13], r[e], r[e + 4], r[e + 8], r[e + 10], r[e + 11]))
        self._control("IRQ-WINDOW-LIVE", en1 >= 1, en1_entries_rise=en1, window_ops=_QUIET_OPS)
        self.logger.info(
            "LOG irq_gate counts en0=%d->%d en1=%d->%d w1c=%d->%d status_after_w1c=%s",
            r[10].value,
            r[12].value,
            r[e + 1].value,
            r[e + 3].value,
            r[e + 5].value,
            r[e + 7].value,
            _h(r[e + 8].value),
        )
        if (
            self._grade(
                "BANK-SK-IRQ",
                en0 == 0 and en1 >= 1 and after == 0 and set_masked and cleared and resp,
                en0_entries_rise=en0,
                en1_entries_rise=en1,
                status_set_masked=set_masked,
                w1c_stops=after == 0,
                status_cleared=cleared,
                idle_ops=idle,
                resp_ok=resp,
            )
            and not self.failed
        ):
            # Pass label: releases the cp_sk_interrupt line cells of this step.
            set_km_sk_pass(KM_SK_PASS_IRQ, self.logger)
            await ClockCycles(self.dut.clk_i, _LABEL_CLKS)

    # ------------------------------------------- step 11: single-share leg

    async def _wipe_ctrl(self, value: int) -> None:
        seq = SepAxiAccessSeq(
            "km_wipe_ctrl", op=SepAxiOp.WRITE, addr=_KM_WIPE_CTRL, wdata=value, size=2
        )
        await self.start_seq(seq)
        if not seq.resp_ok:
            raise AssertionError(f"KM_WIPE_CTRL write {_h(value)} not OKAY")

    async def _km_wipe(self) -> None:
        """One rising edge of KM_WIPE_CTRL.wipe_state: one wipe pulse."""
        await self._wipe_ctrl(_KM_WIPE_BIT)
        await ClockCycles(self.dut.clk_i, _WIPE_HOLD_CLKS)
        await self._wipe_ctrl(0)

    async def _aes_block(self, pt: tuple[int, ...]) -> list[int]:
        """One AES-256 ECB encryption from the sideload key."""
        await self.aes.configure_ecb_enc_256(sideload=True)
        await self.aes.trigger_prng_reseed()
        return await self.aes.run_ecb_block(list(pt))

    async def _single_share(self) -> None:
        """Single-share AES delivery after a Key Manager wipe, share 0 and share 1."""
        a = pl.AES_BANK
        # Entropy for the AES masking PRNG (no graded step here).
        await self.bring_up_entropy(strict=True, score_km=False)
        if not await self.wait_genbits():
            raise AssertionError("CSRNG CTR_DRBG never produced genbits")
        self.start_fifo_drain()
        self.aes = SepAes(self)
        await self.aes.wait_idle("post-entropy")

        # Control: both shares written, share0 XOR share1 = K, give the golden of K.
        b = self.plan.both_shares
        r = await self._run(
            [kp.wrblk(a.share0[0], b.s0), kp.wrblk(a.share1[0], b.s1)]
            + [kp.wr(a.ctrl, a.valid_mask), kp.rd(a.ctrl)]
        )
        ct = await self._aes_block(b.pt)
        golden = aes256_ecb_encrypt_words(list(b.key), list(b.pt))
        self._control(
            "SS-BOTH-SHARES",
            ct == golden and bool(r[3].value & a.valid_mask) and all(_ok(x) for x in r),
            key_ctrl=_h(r[3].value),
            ct=[_h(w) for w in ct],
            golden=[_h(w) for w in golden],
        )

        self._open()
        for leg in self.plan.single_share:
            await self._single_share_leg(leg)
        await self._subword()
        close_graded_window(self.logger)
        await self.stop_fifo_drain()
        if not self.drbg_sb.report():
            raise AssertionError("entropy scoreboard report failed")

    async def _single_share_leg(self, leg: pl.SingleShare) -> None:
        a = pl.AES_BANK
        mask = a.valid_mask
        own = (a.share0, a.share1)[leg.share]
        set_km_ss_pass(False, self.logger)
        pre = await self._run(
            [kp.wrblk(a.share0[0], leg.pre[0]), kp.wrblk(a.share1[0], leg.pre[1])]
            + [kp.wr(a.ctrl, mask), kp.rd(a.ctrl)]
        )
        await self._km_wipe()
        post = await self._run(
            [kp.rd(a.ctrl), kp.wrblk(own[0], leg.key), kp.wr(a.ctrl, mask), kp.rd(a.ctrl)]
        )
        ct = await self._aes_block(leg.pt)
        golden = aes256_ecb_encrypt_words(list(leg.key), list(leg.pt))
        v_pre = int(bool(pre[3].value & mask))
        v_wipe = int(bool(post[0].value & mask))
        v_post = int(bool(post[3].value & mask))
        resp = all(_ok(x) for x in pre + post)
        # KEY_CTRL is graded on key_valid only; the whole words are logged.
        self.chk.obs(
            "SS-KEY-CTRL",
            share=leg.share,
            before_wipe=_h(pre[3].value),
            after_wipe=_h(post[0].value),
            after_write=_h(post[3].value),
        )
        passed = self._grade(
            "SINGLE-SHARE",
            ct == golden and v_pre == 1 and v_wipe == 0 and v_post == 1 and resp,
            share=leg.share,
            key=[_h(w) for w in leg.key],
            pt=[_h(w) for w in leg.pt],
            ct=[_h(w) for w in ct],
            golden=[_h(w) for w in golden],
            valid_before_wipe=v_pre,
            valid_after_wipe=v_wipe,
            valid_after_write=v_post,
            resp_ok=resp,
        )
        if passed:
            # Pass label: the sampler holds the single-share point of this
            # instance from the KEY_VALID rise and samples it on this rise.
            set_km_ss_pass(True, self.logger)
            await ClockCycles(self.dut.clk_i, _LABEL_CLKS)

    def _subword_draws(self) -> tuple:
        """K, PT, and (share0 word, value) per size with three distinct outcomes."""
        rng = SepSeededRng(self.plan.seed ^ _SUBWORD_SALT)
        key = [rng.getrandbits(32) | 1 for _ in range(pl.AES_BANK.words)]
        pt = [rng.getrandbits(32) for _ in range(pl.AES_PT_WORDS)]
        words = rng.sample(range(pl.AES_BANK.words), len(_SUBWORD_SIZES))
        stores = []
        for (size, _, _, lanes, rep), j in zip(_SUBWORD_SIZES, words):
            while True:
                v = rng.getrandbits(lanes.bit_length())
                outcomes = {key[j], (key[j] & ~lanes & pl.WORD) | v, v * rep}
                if len(outcomes) == 3:
                    break
            stores.append((size, j, v))
        return key, pt, stores

    @staticmethod
    def _subword_snippet(base: int, stores: list, addr: list[int]) -> list[int]:
        """Sub-word stores, KEY_VALID set, results to KM SRAM words 95-97, then spin."""
        a = pl.AES_BANK
        asm = Asm(base)
        for (_, nbytes, *_), (_, _, v), at in zip(_SUBWORD_SIZES, stores, addr):
            asm.li(5, at).li(6, v).op(store(nbytes, 6, 5, 0))
        asm.li(5, a.ctrl).li(6, a.valid_mask).op(sw(6, 5, 0))
        asm.li(7, kp.sram_addr(_W_SUBWORD))
        asm.li(5, _KMCSR_IRQ_STATUS).op(lw(6, 5, 0), sw(6, 7, 0))
        asm.li(5, a.ctrl).op(lw(6, 5, 0), sw(6, 7, 4))
        asm.li(6, _SUBWORD_MARK).op(sw(6, 7, 8))
        asm.label("spin").j("spin")
        return asm.words()

    async def _subword(self) -> None:
        """Byte and halfword KM CPU stores to AES share0 words, then one AES block."""
        a = pl.AES_BANK
        key, pt, stores = self._subword_draws()
        addr = [a.share0[j] for _, j, _ in stores]
        self.logger.info(
            "DRAW subword key_words=%d pt=%s stores=%s",
            len(key),
            [_h(w) for w in pt],
            [(size, j) for size, j, _ in stores],
        )
        base = kp.KM_SRAM_BASE + _SUBWORD_REGION * _SUBWORD_REGION_BYTES
        snippet = self._subword_snippet(base, stores, addr)
        pre = await self._run(
            [
                kp.wrblk(a.share0[0], key),
                kp.fill(a.share1[0], 0, a.words),
                kp.wrblk(base, snippet),
                kp.fill(kp.sram_addr(_W_SUBWORD), 0, 3),
                kp.wr(_KMCSR_SRAM_LOCK, 1 << _SUBWORD_REGION),
                kp.wr(_KMCSR_SRAM_EXEC_MODE, _SRAM_EXEC_ENABLE),
            ]
        )
        sub0 = self.rd(self.dut.km_axi_subword_wr_count_o)
        last: dict[int, int] = {}

        async def watch() -> None:
            while True:
                await RisingEdge(self.dut.clk_i)
                await ReadOnly()
                wa = self.rd(self.dut.km_axi_wr_addr_o)
                if wa in addr:
                    last[wa] = self.rd(self.dut.km_axi_wr_strb_o)

        task = cocotb.start_soon(watch())
        await self.poke.post([kp.disarm(), kp.jump(base)])
        marker = 0
        for _ in range(0, _SUBWORD_BOUND, 16):
            marker = self.poke.word(_W_SUBWORD + 2, allow_unknown=True)
            if marker == _SUBWORD_MARK:
                break
            await ClockCycles(self.dut.clk_i, 16)
        await ClockCycles(self.dut.clk_i, 2)
        task.cancel()
        sub = self.rd(self.dut.km_axi_subword_wr_count_o) - sub0
        reached = True
        for (size, _, expect, _, _), at in zip(_SUBWORD_SIZES, addr):
            ok = self._control(
                "BANK-SUBWORD",
                last.get(at) == expect and marker == _SUBWORD_MARK and all(_ok(x) for x in pre),
                size=size,
                addr=_h(at),
                wstrb=f"0x{last.get(at, 0):x}",
                expect=f"0x{expect:x}",
                marker=_h(marker),
            )
            reached = reached and ok
            if ok:
                set_open_value_leg_pass(f"km_bank_subword_{size}", self.logger)
                await ClockCycles(self.dut.clk_i, _LABEL_CLKS)
                set_open_value_leg_pass(None, self.logger)
                await ClockCycles(self.dut.clk_i, _LABEL_CLKS)
        if not reached:
            return
        ct = await self._aes_block(tuple(pt))
        outcomes = []
        for (_, _, _, lanes, rep), (_, j, v) in zip(_SUBWORD_SIZES, stores):
            merged = (key[j] & ~lanes & pl.WORD) | v
            outcomes.append({"merged": merged, "whole": v * rep, "ignored": key[j]})
        match = "none"
        for b_name, b_word in outcomes[0].items():
            for h_name, h_word in outcomes[1].items():
                k = list(key)
                k[stores[0][1]], k[stores[1][1]] = b_word, h_word
                if aes256_ecb_encrypt_words(k, list(pt)) == ct:
                    match = f"byte:{b_name},half:{h_name}"
        self.chk.obs(
            "BANK-SUBWORD",
            ct=[_h(w) for w in ct],
            match=match,
            irq_status=_h(self.poke.word(_W_SUBWORD)),
            key_ctrl=_h(self.poke.word(_W_SUBWORD + 1)),
            subword_writes=sub,
        )

    # ------------------------------------------------- step 8: all set

    async def _all_set(self) -> None:
        ops = [*_stage_msg_ops(self.plan), kp.sync(), self._poll_sk()]
        ops += _set_all_ops() + _state_ops(words=True)

        async def on_sync(_k: int) -> None:
            await self._encaps(3)

        r = await self._run(ops, on_sync=on_sync)
        self._need_delivery(r[4], "encapsulation 3")
        st = _decode_state(r[5 + pl.N_BANKS :])
        if st["vec"] != pl.ALL_BANKS or not st["sk_valid"] or not st["sk_irq"]:
            raise AssertionError(
                f"engine-reset setup: vector={_v(st['vec'])} sk_valid={st['sk_valid']} "
                f"sk_irq={st['sk_irq']}; the reset leg needs 0xff, 1 and 1"
            )
        self.state = st
        self.logger.info(
            "LOG reset_setup vector=%s sk_valid=1 sk_irq=1 sk_words_nonzero=%d",
            _v(st["vec"]),
            sum(1 for w in st["sk_words"] if w),
        )

    # ------------------------------------------------- step 9: engine resets

    async def _hold_reset(self, eng: str) -> str:
        probe = pl.ISO_PROBE.get(eng)
        if probe is None:
            await ClockCycles(self.dut.clk_i, _HOLD_CLKS)
            return f"hold={_HOLD_CLKS}"
        sig = getattr(self.dut, probe)
        for k in range(_ISO_BOUND):
            await RisingEdge(self.dut.clk_i)
            if self.rd(sig, allow_unknown=True) == 1:
                await ClockCycles(self.dut.clk_i, _ISO_EXTRA_CLKS)
                return f"isolated_after={k + 1}"
        raise AssertionError(f"{probe} did not read isolated within {_ISO_BOUND} clocks")

    async def _engine_resets(self) -> None:
        for eng in self.plan.engine_order:
            before = self.state
            await self.poke.prepare_reset()
            await self.swrst.park(eng)
            how = await self._hold_reset(eng)
            await self.swrst.release(eng)
            await ClockCycles(self.dut.clk_i, _SETTLE_CLKS)
            after = _decode_state(await self._run(_state_ops(words=True)))
            own = pl.ENGINE_BANKS[eng]
            fields = {
                "eng": eng,
                "sw_reset_n_bit": SW_RESET_N_BIT[eng],
                "before": _v(before["vec"]),
                "after": _v(after["vec"]),
                "own_cleared": (after["vec"] & own) == 0,
                "others_kept": (after["vec"] & ~own) == (before["vec"] & ~own),
                "sk_valid": after["sk_valid"],
                "sk_irq": after["sk_irq"],
                "sk_words_zero": not any(after["sk_words"]),
                "resp_ok": after["ok"],
                "how": how,
            }
            self.chk.obs("BANK-RST", **fields)
            self.state = after

    # ------------------------------------------------- step 10: KM PARK

    async def _park(self) -> None:
        r = await self._run(_set_all_ops() + _ctrl_ops())
        before = pl.vector({b.bit: r[pl.N_BANKS + i].value for i, b in enumerate(pl.BANKS)})
        await self.poke.prepare_reset()
        # The SEP mailbox FIFO keeps its words across a warm reset and the
        # image reads a leftover word as a list header: start the reset empty.
        await self.poke.mbox.flush()
        await self.swrst.park("km")
        await ClockCycles(self.dut.clk_i, _PARK_HOLD_CLKS)
        await self.swrst.release("km")
        await self.poke.wait_boot()
        after = _decode_state(await self._run(_state_ops(words=False)))
        self.logger.info(
            "OBS-KM-PARK seed=%d before=%s after=%s sk_valid=%d sk_irq=%d resp_ok=%d",
            self.plan.seed,
            _v(before),
            _v(after["vec"]),
            after["sk_valid"],
            after["sk_irq"],
            after["ok"],
        )
