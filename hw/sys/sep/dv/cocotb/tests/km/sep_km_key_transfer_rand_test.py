# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Key transfer: longer keys, multi-engine masks, whole-request refusal and subset shred.

no_cpu / lsu_stub_all_live / real fuse sense / +esrc_noise_force /
+km_rom_hex=rom_main.rom.parhex (vehicle HOST). Two random classes:
RANDCFG for the delivery leg, RAND-REP for the policy leg. ``SepSeededRng``
draws every value from the leaf seed (``sep_km_key_transfer_rand_plan.py``),
and the leaf logs each draw as a ``DRAW`` line.

The testbench LSU master is the SEP host. It reaches the KM only through
``km_mailbox_sep``. Every frame is well formed (``SepKmMailbox``), so a
refusal is a verdict on the arguments. The response frame is the evidence of
a command result. An engine output checked against an independent golden is
the evidence that a key arrived:

* AES witness: ECB-256 with ``sideload`` = 1 on one fixed block. ``key`` when
  the output equals the AES-256 golden of the delivered words 0 to 7
  (``env/sep_aes_golden.py``). Any other output, or no output within the
  window W, is ``other``. The output of an AES without a key is not stated, so
  an ``other`` result is logged as ``OBS-AES-NOKEY`` and never counts as the
  pass of a refusal or a shred. W is 8 times the duration of the first AES
  output of the leaf, which always has a key. After ``other`` the leaf resets
  the AES through ``SW_RESET_N`` bit 2, because an AES that waits for a key
  stays waiting.
* HMAC witness: keyed HMAC-SHA256 of one fixed message with a fixed software
  key in the KEY registers. ``key`` when the digest equals the golden of the
  delivered words 0 to 7, ``nokey`` when it equals the golden of the software
  key (``hw/sys/sep/doc/hmac.adoc``: the delivered key is used only while
  KEY_VALID is set). Any other digest fails the check of the step.

KMAC, OTBN and the ABR seeds have no witness. The taps ``KM-VALID``
(``km_engine_key_valid_o``, KEY_CTRL.key_valid of the eight banks in DEST_VALID
bit order) and ``KM-BUS`` (``km_key_aw_{valid,ready,addr}_o``, the AW
handshakes on the five key-path ports) are read only.

Checks:
  CHK-GOLD          above 16 words (17, 128 and one drawn size in [18, 127]),
                    the AES block and the HMAC digest equal the golden of the
                    leading 8 words; the trailing words differ from the
                    leading words. The 8, 9 and 16 word rounds run as controls.
  CHK-POLICY        a transfer returns success with the handle and the mask
                    echoed (every delivery round, every engine), and the
                    permitted multi-engine transfer of K1 to M gives each
                    witness in M the key of K1 and sets key_valid = M.
  CHK-REFUSE        the mixed mask X returns -1 with no argument, and the HMAC
                    witness (in the permitted part of X) reads ``nokey``.
  CHK-SHRED-SUBSET  CMD_ENGINE_SHRED of a proper subset S of V echoes S; the
                    HMAC witness (in S) goes from ``key`` to ``nokey``; the AES
                    witness (outside S) keeps ``key``.
  CHK-BANKS         key_valid equals the expected vector after every transfer
                    and shred of the leaf: no bystander bank rises, a refused
                    mask raises no bank, a shred clears exactly its banks, and
                    the all-bank pass reads 0xFF and then 0x00.
  CHK-ENG-ORDER     in the transfer of K1 to M and of K3 to 0xFF, the writes of
                    each selected bank form one run, the runs come in DEST_VALID
                    bit order, and each selected bank shows a write.

The rounds below the share width, the short-key repeat, the four repeated
transfers, the share-write records of a single-engine transfer and shred, and
the revoke leg serve only planned checks and do not run.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge
from cocotb.utils import get_sim_time
from env.sep_aes_golden import aes256_ecb_encrypt_words
from env.sep_chk_log import SepChkLog
from env.sep_efuse_image import LC_PROD
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_hmac_golden import hmac_sha256_words
from km import sep_km_key_transfer_rand_plan as pl
from sep_base_test import sep_base_test
from seq_lib.sep_aes_seq import AES_STATUS, AES_STATUS_OUTPUT_VALID, SepAes
from seq_lib.sep_hmac_seq import SepHmac
from seq_lib.sep_km_mailbox_seq import (
    KM_CMD_ENGINE_SHRED,
    KM_CMD_KEY_TRANSFER,
    KM_RC_FAILURE,
    KM_RC_SUCCESS,
    KM_RESP_CMD,
    SepKmMailbox,
)
from seq_lib.sep_kmac_seq import SepKmac
from seq_lib.sep_otbn_seq import SepOtbn
from seq_lib.sep_sw_reset_seq import SW_RESET_N_BIT, SepSwReset

TEST = "sep_km_key_transfer_rand_test"

# Fixed witness stimulus. The software key differs from the leading words of
# every delivered key (asserted at plan time), so ``key`` and ``nokey`` differ.
AES_PT = (0x03020100, 0x07060504, 0x0B0A0908, 0x0F0E0D0C)
HMAC_MSG = (0x61626364, 0x65666768, 0x696A6B6C, 0x6D6E6F70, 0x71727374, 0x75767778)
HMAC_SW_KEY = (
    0x5EC0DE01,
    0x5EC0DE02,
    0x5EC0DE03,
    0x5EC0DE04,
    0x5EC0DE05,
    0x5EC0DE06,
    0x5EC0DE07,
    0x5EC0DE08,
)
WITNESS_WORDS = 8

W_FACTOR = 8  # W = W_FACTOR x the duration of the first AES output of the leaf
AES_FIRST_BOUND = 80_000  # clocks for the first AES output (it always has a key)
AES_POLL_GAP = 20
SEP_RESET_BOUND = 20_000  # clocks for dbg_sep_reset_n_o to read 1


def _h(v: int) -> str:
    return f"0x{v:02x}"


class _BusWatch:
    """AW handshakes on the five key-path ports (``KM-BUS``), in clock order."""

    def __init__(self, test: sep_base_test) -> None:
        top = cocotb.top
        self.test = test
        self.clk = top.clk_i
        self.valid = top.km_key_aw_valid_o
        self.ready = top.km_key_aw_ready_o
        self.addr = top.km_key_aw_addr_o
        self.writes: list[tuple[int, int]] = []
        self.same_clock = 0
        self._on = False
        self._task = None

    def start(self) -> None:
        self.writes = []
        self.same_clock = 0
        self._on = True
        self._task = cocotb.start_soon(self._run())

    async def stop(self) -> list[tuple[int, int]]:
        self._on = False
        await ClockCycles(self.clk, 2)
        return list(self.writes)

    async def _run(self) -> None:
        while True:
            await RisingEdge(self.clk)
            await ReadOnly()
            if not self._on:
                return
            hs = self.test.rd(self.valid, allow_unknown=True) & self.test.rd(
                self.ready, allow_unknown=True
            )
            if not hs:
                continue
            addrs = self.test.rd_known(self.addr)
            ports = [p for p in range(pl.N_PORTS) if (hs >> p) & 1]
            if len(ports) > 1:
                self.same_clock += 1
            for p in ports:
                self.writes.append((p, (addrs >> (32 * p)) & pl.WORD))


@pyuvm.test()
class sep_km_key_transfer_rand_test(sep_base_test):
    """Longer keys, multi-engine masks, whole-request refusal and subset shred."""

    required_evidence = (
        "CHK-GOLD",
        "CHK-POLICY",
        "CHK-REFUSE",
        "CHK-SHRED-SUBSET",
        "CHK-BANKS",
        "CHK-ENG-ORDER",
    )

    # ------------------------------------------------------------------ main

    async def run_scenario(self) -> None:
        seed = self.random_seed()
        self.logger.info("SEED seed=%d", seed)
        self.chk = SepChkLog(self, TEST, seed)
        self.seed = seed
        self.plan = pl.draw_plan(seed)
        pl.check_plan(self.plan)
        for line in pl.draw_lines(self.plan):
            self.logger.info(line)
        self._check_witness_construction()

        self.period_ps = self._whole_ps(self.cfg.sys_clk_period_ns, "clk_i period")
        self.aes_first_clk: int | None = None
        self.w_clk: int | None = None
        self.banks: list[tuple[str, int, int]] = []  # (label, key_valid, expected)

        # Step 1: PROD image, real sense, entropy with noise forced, every
        # engine out of reset and idle, then the KM release and RESP_KM_READY.
        image = self.select_efuse_image(lc_raw=LC_PROD)
        self.write_efuse_image(image)
        await self.bring_up_no_cpu(park=("otbn", "aes", "hmac", "kmac"))
        if getattr(self, "swrst", None) is None:
            self.swrst = SepSwReset(self)
        self.suppress_host_axi_transaction_info()
        self.km = SepKmMailbox(self)
        self.aes = SepAes(self)
        self.hmac = SepHmac(self)
        self.bus = _BusWatch(self)

        await self.bring_up_entropy(strict=True, score_km="observe", score_sinks={"aes": "observe"})
        assert await self.wait_genbits(), "CSRNG CTR_DRBG never produced genbits"
        self.start_fifo_drain(log_batches=False)

        # A key write to an engine held in its SW_RESET_N reset ends in SLVERR,
        # which the KM reports as fatal, so every engine is out of reset and
        # idle before the KM runs.
        await self.swrst.release("aes", "hmac", "kmac", "otbn")
        await self.aes.wait_idle("post-release")
        await self.hmac.wait_idle("post-release")
        await SepKmac(self).wait_idle("post-release")
        await SepOtbn(self).wait_idle("post-release")
        engines = [n for n in SW_RESET_N_BIT if n != "km"]
        held = [n for n in engines if not (self.swrst.value >> SW_RESET_N_BIT[n]) & 1]
        assert not held, f"precondition FAIL: engines held in SW_RESET_N reset: {held}"
        await self._wait_sep_reset_n()
        await self.swrst.release("km")
        await self.km.wait_km_ready()
        self.logger.info("STEP precondition: rom_main booted, RESP_KM_READY over the mailbox")

        open_graded_window(TEST, self.logger)
        await self._delivery_leg()
        close_graded_window(self.logger)
        await self._warm_reset()
        open_graded_window(TEST, self.logger)
        await self._policy_leg()
        self._grade_banks()
        close_graded_window(self.logger)

        await self.km.check_outbound_empty("EOT")
        await self.aes.check_status_clean("EOT")
        await self.hmac.check_status_clean("EOT")
        await self.stop_fifo_drain()
        await self.check_entropy_alerts_zero()
        assert self.drbg_sb.report()
        self.chk.finish()

    # ------------------------------------------------------------ plumbing

    def _check_witness_construction(self) -> None:
        keys = [r.words for r in self.plan.rounds if r.runs] + [
            self.plan.k1,
            self.plan.k2,
            self.plan.k3,
        ]
        for k in keys:
            lead = tuple(k[:WITNESS_WORDS])
            if len(lead) == WITNESS_WORDS and lead == HMAC_SW_KEY:
                raise AssertionError("test construction error: a drawn key equals the HMAC SW key")

    def _cyc(self) -> int:
        return int(get_sim_time("ps")) // self.period_ps

    def _ctl(self, name: str, **fields) -> None:
        """A control line. It shows that the scenario ran and grades nothing."""
        text = " ".join(f"{k}={v}" for k, v in fields.items())
        self.logger.info("CTL-%s LOG seed=%d control=1 %s", name, self.seed, text)

    def _keyvalid(self) -> int:
        return self.rd_known(cocotb.top.km_engine_key_valid_o) & pl.ALL_BANKS

    def _bank(self, label: str, expected: int) -> int:
        got = self._keyvalid()
        self.banks.append((label, got, expected))
        if got != expected:
            self.logger.info(
                "LOG KM-VALID %s: key_valid=%s expected=%s", label, _h(got), _h(expected)
            )
        return got

    async def _wait_sep_reset_n(self) -> None:
        for _ in range(SEP_RESET_BOUND):
            await RisingEdge(cocotb.top.clk_i)
            if self.rd(cocotb.top.dbg_sep_reset_n_o, allow_unknown=True):
                return
        raise AssertionError(f"dbg_sep_reset_n_o did not read 1 within {SEP_RESET_BOUND} clocks")

    async def _cmd(self, cmd_id: int, payload: list[int]) -> tuple[int, int | None]:
        """Send one command; return (code, argument or None when the frame has none)."""
        seq = await self.km.send_command(cmd_id, payload)
        words = await self.km.recv_frame()
        resp_id = (words[0] >> 8) & 0xFF
        plen = (words[0] >> 16) & 0xFF
        if resp_id != KM_RESP_CMD or plen < 3:
            raise AssertionError(
                f"command 0x{cmd_id:02x}: expected RESP_CMD with 3 or more payload words, "
                f"got frame {[hex(w) for w in words]}"
            )
        if (words[1] & 0xFF) != seq or (words[2] & 0xFF) != cmd_id:
            raise AssertionError(
                f"command 0x{cmd_id:02x} seq {seq}: RESP_CMD echoes seq {words[1] & 0xFF} "
                f"id 0x{words[2] & 0xFF:02x}"
            )
        raw = words[3] & 0xFF
        code = raw - 256 if raw >= 128 else raw
        arg = words[4] if plen >= 4 else None
        await self.km.check_outbound_empty(f"POST-CMD-0x{cmd_id:02x}")
        self.logger.info(
            "KM cmd 0x%02x payload=%s code=%d arg=%s",
            cmd_id,
            [hex(w) for w in payload[:2]],
            code,
            "none" if arg is None else f"0x{arg:08x}",
        )
        return code, arg

    async def _transfer(self, handle: int, mask: int) -> tuple[int, int | None]:
        return await self._cmd(KM_CMD_KEY_TRANSFER, [handle, mask])

    @staticmethod
    def _xfer_echo_ok(code: int, arg: int | None, handle: int, mask: int) -> bool:
        return (
            code == KM_RC_SUCCESS
            and arg is not None
            and (arg & 0xFF) == handle
            and ((arg >> 8) & 0xFF) == mask
        )

    @staticmethod
    def _echo_mask(arg: int | None) -> str:
        return "none" if arg is None else _h((arg >> 8) & 0xFF)

    async def _shred(self, mask: int) -> tuple[int, int | None]:
        return await self._cmd(KM_CMD_ENGINE_SHRED, [mask])

    async def _shred_pre(self, mask: int, what: str) -> None:
        """A shred whose result a later check does not grade: success and echo required."""
        code, arg = await self._shred(mask)
        if code != KM_RC_SUCCESS or arg is None or (arg & 0xFF) != mask:
            raise AssertionError(
                f"precondition FAIL ({what}): CMD_ENGINE_SHRED mask {_h(mask)} code={code} "
                f"arg={'none' if arg is None else hex(arg)}"
            )

    async def _load(self, words: tuple[int, ...], dest: int) -> int:
        return await self.km.key_load(key_words=list(words), dest=dest)

    async def _revoke_pre(self, handle: int) -> None:
        code, arg = await self.km.key_revoke(handle=handle)
        if code != KM_RC_SUCCESS or (arg & 0xFF) != handle:
            raise AssertionError(
                f"precondition FAIL: CMD_KEY_REVOKE of handle 0x{handle:02x} code={code} "
                f"arg=0x{arg:08x}"
            )

    # ------------------------------------------------------------ witnesses

    async def _aes_reset(self) -> None:
        await self.swrst.park("aes")
        await self.swrst.release("aes")
        await self.aes.wait_idle("post-witness-reset")

    async def _aes_read(self, key: tuple[int, ...] | None, step: str) -> str:
        """AES witness: ``key`` or ``other``. Resets the AES after ``other``."""
        golden = aes256_ecb_encrypt_words(list(key[:WITNESS_WORDS]), list(AES_PT)) if key else None
        await self.aes.configure_ecb_enc_256(sideload=True)
        await self.aes.trigger_prng_reseed()
        await self.aes.start_block_no_wait(list(AES_PT))
        t0 = self._cyc()
        first = self.aes_first_clk is None
        dur = None
        while True:
            st = await self.aes._rd(AES_STATUS)
            el = self._cyc() - t0
            if st & (1 << AES_STATUS_OUTPUT_VALID):
                dur = el
                break
            if first and el > AES_FIRST_BOUND:
                raise AssertionError(
                    f"AES witness ({step}): the first AES read of the leaf gave no output "
                    f"within {AES_FIRST_BOUND} clocks"
                )
            if not first and el > self.w_clk:
                break
            await ClockCycles(cocotb.top.clk_i, AES_POLL_GAP)
        out = await self.aes.read_data_out() if dur is not None else None
        if first:
            self.aes_first_clk = dur
            self.w_clk = W_FACTOR * dur
            self.logger.info(
                "LOG aes_first_clk=%d w_clk=%d (step %s)", self.aes_first_clk, self.w_clk, step
            )
        state = "key" if (golden is not None and out == golden) else "other"
        if state == "other":
            self.chk.obs(
                "AES-NOKEY",
                step=step,
                output="none" if out is None else "0x" + "".join(f"{w:08x}" for w in out),
                aes_first_clk=self.aes_first_clk,
                w_clk=self.w_clk,
            )
            await self._aes_reset()
        return state

    async def _hmac_read(self, key: tuple[int, ...] | None) -> str:
        """HMAC witness: ``key``, ``nokey`` or ``other``."""
        await self.hmac.write_key(list(HMAC_SW_KEY))
        await self.hmac.configure_keyed_256()
        digest = await self.hmac.run_keyed_mac(list(HMAC_MSG))
        g_sw = hmac_sha256_words(list(HMAC_SW_KEY), list(HMAC_MSG), key_word_rev=False, key_be=True)
        g_key = (
            hmac_sha256_words(list(key[:WITNESS_WORDS]), list(HMAC_MSG))
            if key is not None
            else None
        )
        if g_key is not None and g_key == g_sw:
            raise AssertionError("test construction error: key golden equals the SW-key golden")
        if g_key is not None and digest == g_key:
            return "key"
        if digest == g_sw:
            return "nokey"
        self.logger.info("LOG hmac digest=%s (neither golden)", [hex(w) for w in digest])
        return "other"

    # ------------------------------------------------------------ delivery leg

    async def _delivery_leg(self) -> None:
        for i, r in enumerate(self.plan.rounds):
            name = pl.BANK_NAME[r.eng]
            if not r.runs:
                self.logger.info(
                    "LOG round%d eng=%s size=%d below the width: serves planned checks only, "
                    "not run",
                    i,
                    name,
                    r.size,
                )
                continue
            # Step 5: shred every bank; every key_valid reads 0.
            await self._shred_pre(pl.ALL_BANKS, f"round{i} pre-shred")
            self._bank(f"round{i}_pre", 0)
            # Step 6: load.
            handle = await self._load(r.words, r.mask)
            # Step 7: transfer to E.
            code, arg = await self._transfer(handle, r.mask)
            self.chk.ok(
                "POLICY",
                self._xfer_echo_ok(code, arg, handle, r.mask),
                leg="delivery",
                eng=name,
                size=r.size,
                m=_h(r.mask),
                code=code,
                echo=self._echo_mask(arg),
            )
            # Step 8: only the bank of E rises.
            self._bank(f"round{i}_{name}_s{r.size}", r.mask)
            if r.eng in pl.WITNESS:
                await self._witness_round(r)
            # Step 11: shred E (its bank clears), then revoke the key, so the
            # vault holds at most the key of the current round.
            await self._shred_pre(r.mask, f"round{i} shred")
            self._bank(f"round{i}_shred", 0)
            await self._revoke_pre(handle)

    async def _witness_round(self, r: pl.Round) -> None:
        name = pl.BANK_NAME[r.eng]
        if r.eng == pl.AES:
            state = await self._aes_read(r.words, f"gold_{name}_{r.size}")
            field = "ct_match"
        else:
            state = await self._hmac_read(r.words)
            field = "digest_match"
        match = state == "key"
        if r.size >= pl.GOLD_MIN_SIZE:
            # The trailing words differ from the leading words (pairwise
            # different key words), so a DUT that delivers another word set
            # gives another output and fails.
            self.chk.ok(
                "GOLD",
                match,
                eng=name,
                size=r.size,
                leading=r.width,
                state=state,
                **{field: match},
            )
        else:
            self._ctl("GOLD", eng=name, size=r.size, leading=r.width, state=state, match=int(match))

    # -------------------------------------------------------------- policy leg

    async def _warm_reset(self) -> None:
        # Step 12: SW_RESET_N bit 0 low, then high, with every other bit at 1.
        others = [n for n in SW_RESET_N_BIT if n != "km"]
        assert all((self.swrst.value >> SW_RESET_N_BIT[n]) & 1 for n in others), (
            f"precondition FAIL: SW_RESET_N 0x{self.swrst.value:08x} holds an engine"
        )
        await self.swrst.park("km")
        await self.swrst.release("km")
        self.km.reset_host_seq()
        await self.km.wait_km_ready()
        self.logger.info("STEP warm reset: RESP_KM_READY after the KM warm reset")

    async def _policy_leg(self) -> None:
        p = self.plan
        # Step 13.
        await self._shred_pre(pl.ALL_BANKS, "policy pre-shred")
        h1 = await self._load(p.k1, p.p1)
        h2 = await self._load(p.k2, p.p2)
        self.logger.info("LOG policy handles k1=0x%02x k2=0x%02x", h1, h2)

        permitted_ok = await self._permitted(h1)
        await self._refusal(h1, permitted_ok)
        self.logger.info(
            "LOG revoke leg (order %s) serves planned checks only, not run",
            ",".join(p.leg_order),
        )
        await self._shred_leg()
        await self._all_bank_pass()

    async def _permitted(self, h1: int) -> bool:
        """Step 14: K1 to M. CHK-POLICY and the first CHK-ENG-ORDER transfer."""
        p = self.plan
        self.bus.start()
        code, arg = await self._transfer(h1, p.m)
        writes = await self.bus.stop()
        kv = self._bank("permitted", p.m)
        self.chk.ctrl("BANKS-RISE", kv & p.m == p.m, m=_h(p.m), keyvalid=_h(kv))
        hmac = await self._hmac_read(p.k1)
        aes_in = bool(p.m & (1 << pl.AES))
        # The AES is read last: outside M it has no key and can stay waiting.
        aes = await self._aes_read(p.k1, "policy_permitted")
        echo_ok = self._xfer_echo_ok(code, arg, h1, p.m)
        wit_ok = hmac == "key" and (aes == "key" if aes_in else aes != "key")
        self.chk.ok(
            "POLICY",
            echo_ok and wit_ok and kv == p.m,
            leg="permitted",
            p1=_h(p.p1),
            m=_h(p.m),
            code=code,
            echo=self._echo_mask(arg),
            witness_aes=("golden" if aes == "key" else aes) if aes_in else f"outside:{aes}",
            witness_hmac="golden" if hmac == "key" else hmac,
            keyvalid=_h(kv),
        )
        self._grade_order(writes, p.m, "permitted")
        return echo_ok

    async def _refusal(self, h1: int, permitted_ok: bool) -> None:
        """Step 15: the mixed mask X and the outside mask Z (control)."""
        p = self.plan
        await self._shred_pre(pl.ALL_BANKS, "refusal pre-shred")
        # Negative stimulus differs from the legal value.
        assert p.x & ~p.p1 & pl.ALL_BANKS, f"X {_h(p.x)} holds no bit outside P1 {_h(p.p1)}"
        assert p.z and not p.z & p.p1, f"Z {_h(p.z)} is not outside P1 {_h(p.p1)}"
        code_x, arg_x = await self._transfer(h1, p.x)
        code_z, arg_z = await self._transfer(h1, p.z)
        self._ctl(
            "REFUSE-Z",
            p1=_h(p.p1),
            z=_h(p.z),
            code=code_z,
            arg="none" if arg_z is None else f"0x{arg_z:08x}",
        )
        hmac = await self._hmac_read(p.k1)
        aes_in = bool((p.x | p.z) & (1 << pl.AES))
        aes = await self._aes_read(p.k1, "refusal") if aes_in else "not_read"
        kv = self._bank("refused", 0)
        # Control: the same handle to the permitted mask M succeeded in step 14.
        self.chk.ctrl("REFUSE-ALLOW", permitted_ok, m=_h(p.m))
        self.chk.ok(
            "REFUSE",
            code_x == KM_RC_FAILURE and arg_x is None and hmac == "nokey" and aes != "key",
            p1=_h(p.p1),
            x=_h(p.x),
            code=code_x,
            arg="none" if arg_x is None else f"0x{arg_x:08x}",
            witness_hmac=hmac,
            aes_key=int(aes == "key"),
            keyvalid=_h(kv),
        )

    async def _shred_leg(self) -> None:
        """Step 17: K3 to V, then the proper-subset shred S."""
        p = self.plan
        h3 = await self._load(p.k3, pl.ALL_BANKS)
        await self._shred_pre(pl.ALL_BANKS, "shred-leg pre-shred")
        code, arg = await self._transfer(h3, p.v)
        pre_ok = self._xfer_echo_ok(code, arg, h3, p.v)
        self._bank("shred_leg_v", p.v)
        hmac_before = await self._hmac_read(p.k3)
        assert p.s != p.v and not p.s & ~p.v, f"S {_h(p.s)} is not a proper subset of V {_h(p.v)}"
        code_s, arg_s = await self._shred(p.s)
        echo_s = None if arg_s is None else arg_s & 0xFF
        hmac = await self._hmac_read(p.k3)
        aes = await self._aes_read(p.k3, "shred_subset_outside")
        self._bank("shred_leg_after_s", p.v & ~p.s)
        self.chk.ok(
            "SHRED-SUBSET",
            pre_ok
            and hmac_before == "key"
            and code_s == KM_RC_SUCCESS
            and echo_s == p.s
            and hmac == "nokey"
            and aes == "key",
            v=_h(p.v),
            s=_h(p.s),
            xfer_code=code,
            echo=_h(echo_s) if echo_s is not None else "none",
            code=code_s,
            hmac_before="golden" if hmac_before == "key" else hmac_before,
            hmac=hmac,
            aes="golden" if aes == "key" else aes,
        )
        self.h3 = h3

    async def _all_bank_pass(self) -> None:
        """Step 18: K3 to 0xFF and the all-bank shred (echo and witnesses as controls)."""
        p = self.plan
        await self._shred_pre(pl.ALL_BANKS, "all-bank pre-shred")
        self.bus.start()
        code, arg = await self._transfer(self.h3, pl.ALL_BANKS)
        writes = await self.bus.stop()
        kv = self._bank("all_bank", pl.ALL_BANKS)
        hmac = await self._hmac_read(p.k3)
        aes = await self._aes_read(p.k3, "all_bank")
        self._ctl(
            "ALL-BANK-XFER",
            code=code,
            echo=self._echo_mask(arg),
            witness_hmac=hmac,
            witness_aes=aes,
            keyvalid=_h(kv),
        )
        self._grade_order(writes, pl.ALL_BANKS, "all_bank")
        code_s, arg_s = await self._shred(pl.ALL_BANKS)
        kv_after = self._bank("all_bank_after_shred", 0)
        hmac_after = await self._hmac_read(p.k3)
        aes_after = await self._aes_read(p.k3, "all_bank_after_shred")
        self._ctl(
            "ALL-BANK-SHRED",
            code=code_s,
            echo="none" if arg_s is None else _h(arg_s & 0xFF),
            witness_hmac=hmac_after,
            witness_aes=aes_after,
            keyvalid=_h(kv_after),
        )

    # ----------------------------------------------------------------- grading

    def _grade_order(self, writes: list[tuple[int, int]], mask: int, leg: str) -> None:
        # Single KM master: its key-path stores issue one at a time, so the AW
        # handshake order is the write order.
        res = pl.grade_order(writes, mask)
        self.chk.ok(
            "ENG-ORDER",
            res.ok and self.bus.same_clock == 0,
            leg=leg,
            mask=_h(mask),
            banks_in_order=res.banks_in_order,
            interleaved=res.interleaved,
            missing=",".join(pl.BANK_NAME[b] for b in res.missing) or "-",
            order=res.order_names(),
            writes=res.writes,
            outside_mask=res.outside_mask,
            unknown_addr=res.unknown,
            same_clock=self.bus.same_clock,
        )

    def _grade_banks(self) -> None:
        bad = [f"{lbl}:{_h(got)}!={_h(exp)}" for lbl, got, exp in self.banks if got != exp]
        by = {lbl: got for lbl, got, _exp in self.banks}
        p = self.plan
        self.chk.ok(
            "BANKS",
            not bad and len(self.banks) > 0,
            observations=len(self.banks),
            mismatches=",".join(bad) or "-",
            p1=_h(p.p1),
            x=_h(p.x),
            refused_keyvalid=_h(by.get("refused", 0)),
            v=_h(p.v),
            s=_h(p.s),
            keyvalid=_h(by.get("shred_leg_after_s", 0)),
            all_bank_keyvalid=_h(by.get("all_bank", 0)),
            all_bank_after_shred=_h(by.get("all_bank_after_shred", 0)),
        )
