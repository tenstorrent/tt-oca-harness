# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""KM command frame validation order, sequence counters, transport recovery and the recovery gate.

no_cpu / lsu_stub_all_live / real fuse sense / +esrc_noise_force /
+km_rom_hex=rom_main.rom.parhex (vehicle HOST). RAND-REP: ``SepSeededRng`` from
the run seed draws points from the legal matrices; every draw is logged as
``DRAW``. Contract: VPLAN 7.22, ``docs/test_contracts/key_manager.adoc``.

The testbench LSU master is the SEP host. It reaches the KM only through the
``km_mailbox_sep`` window. Every frame is built here (``CMD_SEQ_NUM`` from the
command model e, the CRC-8/ROHC and CRC-32C goldens of ``env/sep_crc_golden.py``)
and every response frame is read word by word after a bounded wait on
``SEP_IRQ_STATUS.outbound_read_data_avail``. The response check compares the
header CRC-8, the payload CRC-32C, RESPONSE_ID, the echoed CMD_SEQ_NUM and
COMMAND_ID, bits [31:8] of the return-code word (0) and the response sequence
with the response model r. Spec tables, frame builders and draws are in
``sep_km_command_protocol_rand_plan.py``; the source of each value is
``hw/ip/key_manager/doc/firmware.adoc`` and ``km_mailbox_sep.adoc``.

Checks:
  CHK-PAIR         13 ordered pairs of frame faults: the frame returns the code and
                   argument of the earlier check; the twin with only the later fault
                   returns the later code
  CHK-NOCHG-VAULT  KM-KPV CTRL and KM-VALID key_valid read 0 after every rejection of
                   the pair leg; each gated command leaves both taps unchanged
  CHK-WRAP         both 8-bit counters roll over from 255 to 0
  CHK-CNT-RESET    rx_buff_oflow, a SEP flush and a warm reset restart both counters:
                   first response sequence 0, the old sequence refused with -3 arg 0,
                   sequence 0 accepted
  CHK-RECOVER      one RESP_RECOVERABLE_FAULT, no paired RESP_CMD, the gate, the
                   acknowledge and probe bit 31 (graded in full for rx_buff_oflow)
  CHK-GATE         every gated command returns -1 with no argument while
                   RECOVERABLE_ERR is set
  CHK-VALID-FIRST  under the gate a wrong header CRC gives -2, a wrong payload CRC -6
  CHK-ADMIT        the admitted queries return their normal results under the gate
  CHK-PERSIST      probe bit 31 stays 1 after every admitted query until the acknowledge
  CHK-RESET-CLR    a warm reset clears RECOVERABLE_ERR and probe bit 31
  CHK-OFLOW-PEND   after rx_buff_oflow with responses pending, the first word read is
                   the fault header and no pending word comes before or after the frame

Controls (``control=1``): CHK-WRAP-CTRL (sequence 0 at e = 1 returns -3 arg 1),
CHK-ALIVE (CMD_STAT reports recov_fault 0 after the pair leg) and CHK-RESPSEQ (the
response sequence rises by one on every frame except at a reset cause).

The procedure steps that serve only planned checkers do not run: the single-fault
legs (steps 4 to 8), the argument legs (11 to 13), the DEST_VALID walk (15), the
transport leg (33 to 39) and the record of ``inbound_separator`` in step 1.

Known limitation (contract): CHK-OFLOW-PEND can fail on this DUT, because the ROM
recovers from rx_buff_oflow in main context with the mailbox interrupt unmasked.
The overflow step runs last, so every other check grades before it.
"""

from __future__ import annotations

from dataclasses import dataclass

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge
from env.sep_axi_agent import SepAxiOp
from env.sep_chk_log import SepChkLog
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_spec_tables import agg_from_pic
from km import sep_km_command_protocol_rand_plan as pl
from sep_base_test import sep_base_test
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_km_mailbox_seq import (
    KM_CTRL_FLUSH,
    KM_HW_VER_1_0_0,
    KM_IRQ_OUTBOUND_DATA_AVAIL,
    KM_MBOX_BASE,
    KM_MBOX_CTRL,
    KM_MBOX_DEPTH,
    KM_MBOX_IRQ_STATUS,
    KM_MBOX_READ_DATA,
    KM_MBOX_STATUS,
    KM_MBOX_WRITE_DATA,
    KM_MBOX_WRITE_SEPARATOR,
    KM_STATUS_INBOUND_DEPTH_LSB,
    KM_STATUS_INBOUND_DEPTH_MASK,
    KM_STATUS_INBOUND_EMPTY,
    KM_STATUS_INBOUND_FULL,
    KM_STATUS_OUTBOUND_DEPTH_LSB,
    KM_STATUS_OUTBOUND_DEPTH_MASK,
    KM_STATUS_OUTBOUND_EMPTY,
    KM_STATUS_OUTBOUND_FULL,
)
from seq_lib.sep_sw_reset_seq import SepSwReset

TEST = "sep_km_command_protocol_rand_test"

# Probe bit 31 of sep_internal_interrupts_probe_o is km_recoverable_err_o
# (PIC source 32, hw/sys/sep/doc/interrupts.adoc).
_KM_RECOV = agg_from_pic("KM recoverable error")

_POLL_GAP = 20  # clocks between two status polls
_RESP_POLLS = 50_000  # polls for one response word
_READY_POLLS = 40_000  # polls for RESP_KM_READY after a release
_INBOUND_POLLS = 20_000  # polls for inbound_full to read 0
_CTRL_POLLS = 4_000  # polls for SEP_CTRL.flush to self-clear
_OUT_FULL_POLLS = 20_000  # polls for outbound_full to read 1
_SEP_RESET_BOUND = 20_000  # clocks for dbg_sep_reset_n_o to read 1
_PIC_BOUND = 2_000  # clocks for probe bit 31 to rise after the fault frame
_OFLOW_SETTLE = 20_000  # clocks between the last overflow word and the drain
_DRAIN_IDLE_POLLS = 200  # consecutive empty polls that end the drain
_DRAIN_MAX_WORDS = 600  # words the drain reads at most

_FAULT_HDR_WORDS = 3  # header, one sign-extended code word, CRC-32C


def _a(value: int | None) -> str:
    return "none" if value is None else f"0x{value:08x}"


@dataclass(frozen=True)
class _Frame:
    seq: int
    rid: int
    plen: int
    payload: tuple[int, ...]


@dataclass(frozen=True)
class _Resp:
    code: int
    arg: int | None
    seq: int


@pyuvm.test()
class sep_km_command_protocol_rand_test(sep_base_test):
    """Frame validation order, both sequence counters, transport recovery and the gate."""

    required_evidence = (
        "CHK-PAIR",
        "CHK-NOCHG-VAULT",
        "CHK-WRAP",
        "CHK-RECOVER",
        "CHK-CNT-RESET",
        "CHK-OFLOW-PEND",
        "CHK-GATE",
        "CHK-VALID-FIRST",
        "CHK-ADMIT",
        "CHK-PERSIST",
        "CHK-RESET-CLR",
        "CHK-WRAP-CTRL",
        "CHK-ALIVE",
        "CHK-RESPSEQ",
    )

    # ------------------------------------------------------------------ main

    async def run_scenario(self) -> None:
        seed = self.random_seed()
        self.logger.info("SEED seed=%d", seed)
        self.plan = pl.CommandProtocolPlan(seed)
        for line in self.plan.draw_lines():
            self.logger.info(line)
        self.chk = SepChkLog(self, TEST, seed)
        self.dut = cocotb.top
        self.clk = self.dut.clk_i
        self.e = 0  # next expected command sequence number
        self.r = 0  # next expected response sequence number
        self.n_resp = 0
        self.resp_seq_err: list[str] = []
        self.resp_seq_graded = False

        # Step 1: PROD fuse image sensed for real, every engine out of reset
        # (SW_RESET_N reset value 0x7E), entropy up with noise forced.
        image = self.select_efuse_image(lc_raw=0x1)  # LC_PROD
        self.write_efuse_image(image)
        await self.bring_up_no_cpu()
        self.swrst = SepSwReset(self)
        self.suppress_host_axi_transaction_info()
        await self.bring_up_entropy(strict=True, score_km="observe")
        assert await self.wait_genbits(), "CSRNG CTR_DRBG never produced genbits"
        self.start_fifo_drain()
        await self._wait_sep_reset_release()
        await self.swrst.release("km")
        ready = await self._read_frame("boot RESP_KM_READY", polls=_READY_POLLS)
        if ready.rid != pl.RESP_KM_READY or ready.seq != 0:
            raise AssertionError(
                f"boot: first frame rid=0x{ready.rid:02x} seq={ready.seq}, expected "
                f"RESP_KM_READY (0x{pl.RESP_KM_READY:02x}) with sequence 0"
            )
        # Step 2: the models.
        self.r, self.e = 1, 0
        open_graded_window(TEST, self.logger)

        await self._pair_leg()
        await self._alive_and_twins()
        await self._wrap_leg()
        await self._cause_loop()
        for g in self.plan.gates:
            await self._gate_leg(g)
        for hd in self.plan.handovers:
            await self._handover_leg(hd)

        # CHK-RESPSEQ covers every frame of the response reader up to here; the
        # drain of the overflow step reads raw words and is graded on its own.
        self.chk.ok(
            "RESPSEQ",
            self.n_resp > 0 and not self.resp_seq_err,
            control=1,
            n=self.n_resp,
            monotonic=int(not self.resp_seq_err),
            mismatches=self.resp_seq_err[:4],
        )
        # A frame that the response reader reads after this point fails the leaf
        # on a sequence mismatch.
        self.resp_seq_graded = True

        await self._oflow_pend_leg()

        close_graded_window(self.logger)
        await self.stop_fifo_drain()
        await self.check_entropy_alerts_zero()
        assert self.drbg_sb.report()
        self.chk.finish()

    # ------------------------------------------------------------- bus access

    async def _rd(self, offset: int) -> int:
        seq = SepAxiAccessSeq("kmcp_rd", op=SepAxiOp.READ, addr=KM_MBOX_BASE + offset, size=2)
        await self.start_seq(seq)
        if not seq.resp_ok:
            raise AssertionError(f"KM mailbox read @0x{KM_MBOX_BASE + offset:08x} not OKAY")
        return seq.rdata

    async def _wr(self, offset: int, data: int) -> None:
        seq = SepAxiAccessSeq(
            "kmcp_wr", op=SepAxiOp.WRITE, addr=KM_MBOX_BASE + offset, wdata=data, size=2
        )
        await self.start_seq(seq)
        if not seq.resp_ok:
            raise AssertionError(f"KM mailbox write @0x{KM_MBOX_BASE + offset:08x} not OKAY")

    async def _wait_sep_reset_release(self) -> None:
        for _ in range(_SEP_RESET_BOUND):
            await RisingEdge(self.clk)
            await ReadOnly()
            if self.rd(self.dut.dbg_sep_reset_n_o, allow_unknown=True):
                await RisingEdge(self.clk)
                return
        raise AssertionError(
            f"dbg_sep_reset_n_o did not read 1 within {_SEP_RESET_BOUND} clocks; "
            "a SW_RESET_N write before it is lost"
        )

    async def _vault(self) -> tuple[int, int]:
        """KM-KPV CTRL[63:0] and KM-VALID {shared-key key_valid, engine key_valid[7:0]}."""
        await RisingEdge(self.clk)
        await ReadOnly()
        ctrl = self.rd_known(self.dut.km_kpv_ctrl_o)
        kv = self.rd_known(self.dut.km_engine_key_valid_o)
        kv |= self.rd_known(self.dut.km_abr_sk_valid_o) << 8
        await RisingEdge(self.clk)
        return ctrl, kv

    async def _pic31(self) -> int:
        await RisingEdge(self.clk)
        await ReadOnly()
        vec = self.rd_known(self.dut.sep_internal_interrupts_probe_o, mask=1 << _KM_RECOV)
        await RisingEdge(self.clk)
        return (vec >> _KM_RECOV) & 1

    async def _wait_pic31_high(self) -> bool:
        """Bounded wait for probe bit 31 to read 1; False when the bound expires."""
        for _ in range(_PIC_BOUND):
            await RisingEdge(self.clk)
            await ReadOnly()
            vec = self.rd_known(self.dut.sep_internal_interrupts_probe_o, mask=1 << _KM_RECOV)
            if (vec >> _KM_RECOV) & 1:
                await RisingEdge(self.clk)
                return True
        await RisingEdge(self.clk)
        return False

    # ----------------------------------------------------------- frame writer

    async def _inbound_room(self, tag: str) -> int:
        """Free inbound words, after a bounded wait for ``inbound_full`` to read 0.

        The KM only takes words out of the inbound FIFO, so the room read here is
        a lower bound until the host writes again.
        """
        for _ in range(_INBOUND_POLLS):
            status = await self._rd(KM_MBOX_STATUS)
            if not (status >> KM_STATUS_INBOUND_FULL) & 1:
                depth = (status >> KM_STATUS_INBOUND_DEPTH_LSB) & KM_STATUS_INBOUND_DEPTH_MASK
                return max(1, KM_MBOX_DEPTH - depth)
            await ClockCycles(self.clk, _POLL_GAP)
        raise AssertionError(
            f"[{tag}] SEP_STATUS.inbound_full stayed 1 for {_INBOUND_POLLS} polls: the KM "
            "does not take inbound words"
        )

    async def _write_words(self, words, *, separator: bool, tag: str) -> None:
        """Write ``words`` while ``inbound_full`` reads 0; the separator goes on the last word."""
        n = len(words)
        i = 0
        while i < n:
            room = await self._inbound_room(tag)
            while room and i < n:
                if separator and i == n - 1:
                    await self._wr(KM_MBOX_WRITE_SEPARATOR, 1)
                await self._wr(KM_MBOX_WRITE_DATA, words[i] & pl.WORD_MASK)
                i += 1
                room -= 1

    # ---------------------------------------------------------- frame reader

    async def _read_word(self, tag: str, polls: int = _RESP_POLLS) -> int:
        for _ in range(polls):
            irq = await self._rd(KM_MBOX_IRQ_STATUS)
            if (irq >> KM_IRQ_OUTBOUND_DATA_AVAIL) & 1:
                return await self._rd(KM_MBOX_READ_DATA)
            await ClockCycles(self.clk, _POLL_GAP)
        raise AssertionError(
            f"[{tag}] no outbound word within {polls} polls of "
            "SEP_IRQ_STATUS.outbound_read_data_avail"
        )

    async def _read_frame(self, tag: str, *, polls: int = _RESP_POLLS) -> _Frame:
        """Read one response frame; check its CRCs and the response sequence model."""
        hdr = await self._read_word(tag, polls)
        seq, rid, plen, crc8 = hdr & 0xFF, (hdr >> 8) & 0xFF, (hdr >> 16) & 0xFF, hdr >> 24
        if crc8 != pl.header_crc(seq, rid, plen):
            raise AssertionError(
                f"[{tag}] response header 0x{hdr:08x}: HEADER_CRC8 0x{crc8:02x}, expected "
                f"0x{pl.header_crc(seq, rid, plen):02x}"
            )
        payload = tuple([await self._read_word(tag) for _ in range(plen)])
        if plen:
            crc = await self._read_word(tag)
            if crc != pl.payload_crc(payload):
                raise AssertionError(
                    f"[{tag}] response 0x{rid:02x}: PAYLOAD_CRC32 0x{crc:08x}, expected "
                    f"0x{pl.payload_crc(payload):08x}"
                )
        self.n_resp += 1
        if seq != self.r:
            if self.resp_seq_graded:
                raise AssertionError(
                    f"[{tag}] response sequence {seq}, model expects {self.r} "
                    "(a frame read after CHK-RESPSEQ)"
                )
            self.resp_seq_err.append(f"{tag}:exp={self.r}:got={seq}")
            self.logger.error("[%s] response sequence %d, model expects %d", tag, seq, self.r)
        self.r = (seq + 1) & 0xFF
        return _Frame(seq, rid, plen, payload)

    @staticmethod
    def _parse_cmd(f: _Frame, cmd: int, seq: int) -> _Resp | None:
        """The RESP_CMD of command (``cmd``, ``seq``), or None when ``f`` is not that response."""
        if f.rid != pl.RESP_CMD or f.plen not in (3, 4):
            return None
        if f.payload[0] != (seq & 0xFF) or f.payload[1] != (cmd & 0xFF):
            return None
        if f.payload[2] >> 8:
            return None
        arg = f.payload[3] if f.plen == 4 else None
        return _Resp(pl.signed8(f.payload[2]), arg, f.seq)

    async def _resp_cmd(self, cmd: int, seq: int, tag: str) -> _Resp:
        f = await self._read_frame(tag)
        resp = self._parse_cmd(f, cmd, seq)
        if resp is None:
            raise AssertionError(
                f"[{tag}] expected the RESP_CMD of cmd 0x{cmd:02x} seq {seq} with a return-code "
                f"word whose bits [31:8] are 0; got rid=0x{f.rid:02x} plen={f.plen} "
                f"payload={[hex(w) for w in f.payload]}"
            )
        return resp

    async def _send_words(self, words, cmd: int, seq: int, tag: str) -> _Resp:
        await self._write_words(words, separator=True, tag=tag)
        return await self._resp_cmd(cmd, seq, tag)

    async def _cmd(self, cmd: int, payload=(), tag: str = "") -> _Resp:
        """Send a well-formed frame at e; e advances (it passes the sequence check)."""
        seq = self.e
        await self._write_words(pl.cmd_frame(cmd, seq, list(payload)), separator=True, tag=tag)
        self.e = (self.e + 1) & 0xFF
        return await self._resp_cmd(cmd, seq, tag or f"cmd 0x{cmd:02x}")

    # --------------------------------------------------------- reset causes

    async def _warm_reset(self, tag: str) -> _Frame:
        """SW_RESET_N bit 0 low, then high, the other bits 1; read RESP_KM_READY."""
        await self.swrst.park("km")
        await self.swrst.release("km")
        self.r = 0
        f = await self._read_frame(f"{tag} RESP_KM_READY", polls=_READY_POLLS)
        if f.rid != pl.RESP_KM_READY:
            raise AssertionError(
                f"[{tag}] first frame after the warm reset has rid 0x{f.rid:02x}, expected "
                f"RESP_KM_READY 0x{pl.RESP_KM_READY:02x}"
            )
        self.r, self.e = 1, 0
        return f

    async def _assert_idle(self, tag: str) -> None:
        """Every command is answered: both FIFOs read empty before a SEP flush."""
        status = await self._rd(KM_MBOX_STATUS)
        empty = (1 << KM_STATUS_INBOUND_EMPTY) | (1 << KM_STATUS_OUTBOUND_EMPTY)
        if status & empty != empty:
            raise AssertionError(
                f"[{tag}] SEP_STATUS 0x{status:08x}: a FIFO is not empty before the SEP flush"
            )

    async def _sep_flush(self, tag: str) -> None:
        await self._assert_idle(tag)
        await self._wr(KM_MBOX_CTRL, 1 << KM_CTRL_FLUSH)
        for _ in range(_CTRL_POLLS):
            if not (await self._rd(KM_MBOX_CTRL) >> KM_CTRL_FLUSH) & 1:
                return
            await ClockCycles(self.clk, _POLL_GAP)
        raise AssertionError(f"[{tag}] SEP_CTRL.flush did not self-clear in {_CTRL_POLLS} polls")

    async def _apply_cause(self, cause: str, oflow_words, tag: str) -> _Frame:
        """Apply one transport cause and read the frame that answers it (sequence 0)."""
        if cause == "warm_reset":
            return await self._warm_reset(tag)
        if cause == "rx_oflow":
            assert len(oflow_words) == pl.RX_BUFFER_WORDS and all(oflow_words)
            await self._write_words(oflow_words, separator=False, tag=f"{tag} rx_oflow")
        elif cause == "flush":
            await self._sep_flush(tag)
        else:
            raise ValueError(cause)
        self.r = 0
        f = await self._read_frame(f"{tag} fault frame")
        self.r, self.e = 1, 0
        return f

    # ------------------------------------------------------------- pair leg

    async def _pair_leg(self) -> None:
        """Step 9 (with the vault samples of step 10): 13 ordered fault pairs, twins and vault frames."""
        rejected = 0
        nonzero: list[str] = []
        kv_seen = 0
        ctrl_seen = 0
        vault_bad: list[str] = []
        for idx, (d, v) in enumerate(zip(self.plan.pairs, self.plan.vault, strict=True)):
            e0 = self.e
            pf = pl.build_fault_frame(d, frozenset(d.kinds), e0)
            tag = f"pair{idx} {d.first}>{d.second}"
            pr = await self._send_words(pf.words, pf.sent_cmd, pf.sent_seq, tag)
            self.e = pf.e_after
            ctrl, kv = await self._vault()
            rejected += 1
            ctrl_seen |= ctrl
            kv_seen |= kv
            if ctrl or kv:
                nonzero.append(f"{tag}:ctrl={ctrl:#x}:kv={kv:#x}")

            tf = pl.build_fault_frame(d, frozenset([d.second]), self.e)
            tr = await self._send_words(tf.words, tf.sent_cmd, tf.sent_seq, f"{tag} twin")
            self.e = tf.e_after
            ctrl, kv = await self._vault()
            rejected += 1
            ctrl_seen |= ctrl
            kv_seen |= kv
            if ctrl or kv:
                nonzero.append(f"{tag} twin:ctrl={ctrl:#x}:kv={kv:#x}")

            # A vault-writing command with the frame-level faults of the pair: a
            # DUT that acts on the command before it validates the frame changes
            # the vault sample below.
            vf = pl.build_vault_frame(d, v, self.e)
            vr = await self._send_words(vf.words, vf.sent_cmd, vf.sent_seq, f"{tag} vault")
            self.e = vf.e_after
            ctrl, kv = await self._vault()
            rejected += 1
            ctrl_seen |= ctrl
            kv_seen |= kv
            if ctrl or kv:
                nonzero.append(f"{tag} vault:ctrl={ctrl:#x}:kv={kv:#x}")
            if vr.code != vf.code:
                vault_bad.append(f"{tag}:cmd=0x{v.cmd:02x}:code={vr.code}:golden={vf.code}")

            if pf.arg == pl.ARG_LOGGED:
                arg_ok, golden = True, "logged"
            elif pf.arg is None:
                arg_ok, golden = pr.arg is None, "none"
            else:
                arg_ok, golden = pr.arg == pf.arg, f"0x{pf.arg:08x}"
            self.chk.ok(
                "PAIR",
                pr.code == pf.code and arg_ok and tr.code == tf.code,
                pair=idx,
                first=d.first,
                second=d.second,
                code=pr.code,
                golden_code=pf.code,
                arg=_a(pr.arg),
                golden=golden,
                e=e0,
                e_after=pf.e_after,
                twin_code=tr.code,
                twin_golden=tf.code,
                twin_arg=_a(tr.arg),
                pairs=len(self.plan.pairs),
            )
        self._pair_rejected = rejected
        self._pair_nonzero = nonzero
        self._pair_ctrl = ctrl_seen
        self._pair_kv = kv_seen
        self._pair_vault_bad = vault_bad

    async def _alive_and_twins(self) -> None:
        """Steps 10 and 14: CMD_STAT after the pair leg, then the positive twins."""
        stat = await self._cmd(pl.CMD_STAT, (), "alive CMD_STAT")
        # A rejection that latched RECOVERABLE_ERR would make every later -1 of
        # this leaf ambiguous; recov_fault 0 here shows it did not.
        self.chk.ok(
            "ALIVE", stat.code == 0 and stat.arg == 0, control=1, code=stat.code, stat=_a(stat.arg)
        )

        # CHK-NOCHG-VAULT control: a generate write-locks every slot of its span
        # ("Key Management"), so KM-KPV must show lock_write in one CTRL entry.
        # The all-zero samples of the pair leg are therefore not a dead tap.
        gen = await self._cmd(pl.CMD_KEY_GENERATE, (4, pl.DEST_AES), "twin CMD_KEY_GENERATE")
        ctrl, _ = await self._vault()
        lock_write = int(any((ctrl >> (4 * s)) & 1 for s in range(64)))
        self.logger.info(
            "LOG twin cmd=0x22 code=%d arg=%s ctrl=0x%064x control=1", gen.code, _a(gen.arg), ctrl
        )
        load = await self._cmd(
            pl.CMD_KEY_LOAD, (3, 0xF0, *self.plan.twin_load_key), "twin CMD_KEY_LOAD"
        )
        self.logger.info("LOG twin cmd=0x26 code=%d arg=%s control=1", load.code, _a(load.arg))
        abr = await self._cmd(
            pl.CMD_ABR_SK_TRANSFER, (self.plan.twin_abr_dest,), "twin CMD_ABR_SK_TRANSFER"
        )
        self.logger.info("LOG twin cmd=0x27 code=%d arg=%s control=1", abr.code, _a(abr.arg))

        self.chk.ok(
            "NOCHG-VAULT",
            not self._pair_nonzero
            and not self._pair_vault_bad
            and gen.code == 0
            and lock_write == 1,
            leg="pair",
            rejected=self._pair_rejected,
            vault_frames=len(self.plan.vault),
            vault_code_bad=self._pair_vault_bad[:4],
            ctrl_nonzero=int(self._pair_ctrl != 0),
            key_valid=f"0x{self._pair_kv:03x}",
            samples_nonzero=self._pair_nonzero[:4],
            control_gen_code=gen.code,
            control_ctrl_lock_write=lock_write,
        )

    # ------------------------------------------------------------- wrap leg

    async def _wrap_leg(self) -> None:
        """Steps 16 and 17: CHK-WRAP-CTRL, then 260 frames across both rollovers."""
        await self._warm_reset("wrap")
        st = await self._cmd(pl.CMD_STAT, (), "wrap first CMD_STAT")
        if st.code != 0:
            raise AssertionError(f"wrap: CMD_STAT at e=0 returned {st.code}")
        assert self.e == 1
        # Sequence 0 at e = 1: cmd_noseq with the expected number. This shows that
        # the acceptance of sequence 0 at the wrap comes from the rollover and not
        # from a KM that accepts any sequence number.
        ctrl = await self._send_words(pl.cmd_frame(pl.CMD_STAT, 0, []), pl.CMD_STAT, 0, "wrap ctrl")
        self.chk.ok(
            "WRAP-CTRL",
            ctrl.code == pl.RC_CMD_NOSEQ and ctrl.arg == 1,
            control=1,
            e=1,
            sent=0,
            code=ctrl.code,
            arg=_a(ctrl.arg),
        )

        bad: list[str] = []
        prev_sent = prev_resp = None
        sent_255 = resp_255 = False
        zero_after_255: tuple[int, int] | None = None
        resp_after_255: int | None = None
        for i, carrier in enumerate(self.plan.wrap_carriers):
            sent = self.e
            r = await self._cmd(carrier, (), f"wrap {i}")
            if r.code != pl.CARRIER_CODE[carrier]:
                bad.append(f"{i}:seq={sent}:cmd=0x{carrier:02x}:code={r.code}")
            if prev_sent == 255 and sent == 0:
                zero_after_255 = (carrier, r.code)
            if prev_resp == 255 and resp_after_255 is None:
                resp_after_255 = r.seq
            sent_255 |= sent == 255
            resp_255 |= r.seq == 255
            prev_sent, prev_resp = sent, r.seq
        zero_ok = (
            zero_after_255 is not None and zero_after_255[1] == pl.CARRIER_CODE[zero_after_255[0]]
        )
        self.chk.ok(
            "WRAP",
            sent_255 and resp_255 and zero_ok and resp_after_255 == 0 and not bad,
            cmd_e=255,
            sent=255 if sent_255 else -1,
            next=0 if zero_after_255 is not None else -1,
            next_code=zero_after_255[1] if zero_after_255 else "none",
            resp_prev=255 if resp_255 else -1,
            resp_next=resp_after_255 if resp_after_255 is not None else "none",
            frames=len(self.plan.wrap_carriers),
            rejected=bad[:4],
        )

    # ---------------------------------------------------- transport causes

    async def _cause_loop(self) -> None:
        """Steps 18 to 21: rx_buff_oflow, SEP flush and warm reset in drawn order."""
        prev = None
        for cause in self.plan.cause_order:
            tag = f"cause {cause}"
            if prev in ("rx_oflow", "flush"):
                ack = await self._cmd(pl.CMD_RECOV_ACK, (), f"{tag} CMD_RECOV_ACK")
                if ack.code != 0:
                    raise AssertionError(f"[{tag}] CMD_RECOV_ACK returned {ack.code}")
            for j, carrier in enumerate(self.plan.cause_p[cause]):
                r = await self._cmd(carrier, (), f"{tag} p{j}")
                if r.code != 0:
                    raise AssertionError(f"[{tag}] carrier 0x{carrier:02x} returned {r.code}")
            e_old, r_old = self.e, self.r
            # Control: both counters hold a non-zero value before the cause.
            assert e_old != 0 and r_old != 0, (
                f"[{tag}] counters e={e_old} r={r_old} before the cause"
            )

            first = await self._apply_cause(cause, self.plan.cause_oflow[cause], tag)
            exp_rid = pl.RESP_KM_READY if cause == "warm_reset" else pl.RESP_RECOVERABLE_FAULT
            fault_code = (
                pl.signed8(first.payload[0]) if first.rid == pl.RESP_RECOVERABLE_FAULT else None
            )

            # The old, non-zero sequence: refused with -3 and the expected number 0,
            # and its response is the first frame after the fault or READY frame.
            f = await self._send_frame_raw(pl.cmd_frame(pl.CMD_STAT, e_old, []), f"{tag} old seq")
            old = self._parse_cmd(f, pl.CMD_STAT, e_old)
            s0 = await self._cmd(pl.CMD_STAT, (), f"{tag} seq0 CMD_STAT")
            self.chk.ok(
                "CNT-RESET",
                first.rid == exp_rid
                and first.seq == 0
                and old is not None
                and old.code == pl.RC_CMD_NOSEQ
                and old.arg == 0
                and s0.code == 0,
                cause=cause,
                first_rid=f"0x{first.rid:02x}",
                first_resp_seq=first.seq,
                fault_code=fault_code if fault_code is not None else "none",
                e_old=e_old,
                r_old=r_old,
                first_after=int(old is not None),
                old_seq_code=old.code if old else "none",
                arg=_a(old.arg) if old else "none",
                first_cmd_seq=0,
                first_cmd_code=s0.code,
                stat=_a(s0.arg),
            )
            prev = cause

    async def _send_frame_raw(self, words, tag: str) -> _Frame:
        await self._write_words(words, separator=True, tag=tag)
        return await self._read_frame(tag)

    # ------------------------------------------------------------ gate legs

    def _gate_payloads(self, g: pl.GateDraw, h: int) -> dict[int, tuple[int, ...]]:
        return {
            pl.CMD_HW_VER: (),
            pl.CMD_ROM_VER: (),
            pl.CMD_SRAM_VER: (),
            pl.CMD_STAT: (),
            pl.CMD_KEY_GENERATE: (g.gen_words - 1, g.gen_dest),
            pl.CMD_KEY_LOAD: (len(g.load_key) - 1, g.load_dest, *g.load_key),
            pl.CMD_KEY_REVOKE: (h,),
            pl.CMD_KEY_TRANSFER: (h, pl.DEST_AES),
            pl.CMD_ENGINE_SHRED: (pl.SHRED_MASK,),
            pl.CMD_OTP_READ_LOCK_COLD: (pl.OTP_LOCK_MASK,),
            pl.CMD_ABR_SK_TRANSFER: (g.abr_dest,),
            pl.CMD_EXEC_ROM: (),
            pl.CMD_SRAM_LOAD_EXEC: (0,),  # FW_WORDS 0
            pl.CMD_SRAM_EXEC: (),
        }

    async def _gate_leg(self, g: pl.GateDraw) -> None:
        """Steps 22 to 29 for one fault source."""
        src = g.source
        tag = f"gate {src}"
        await self._warm_reset(tag)

        # Step 23: the pre-fault window with the gate clear.
        pre: dict[int, int] = {}
        gen = await self._cmd(pl.CMD_KEY_GENERATE, (g.gen_words - 1, g.gen_dest), f"{tag} pre gen")
        pre[pl.CMD_KEY_GENERATE] = gen.code
        load = await self._cmd(
            pl.CMD_KEY_LOAD, (len(g.load_key) - 1, g.load_dest, *g.load_key), f"{tag} pre load"
        )
        pre[pl.CMD_KEY_LOAD] = load.code
        gen_h = gen.arg & 0xFF if gen.code == 0 and gen.arg is not None else 0
        load_h = load.arg & 0xFF if load.code == 0 and load.arg is not None else 0
        rev = await self._cmd(pl.CMD_KEY_REVOKE, (gen_h,), f"{tag} pre revoke")
        pre[pl.CMD_KEY_REVOKE] = rev.code
        xfer = await self._cmd(pl.CMD_KEY_TRANSFER, (load_h, pl.DEST_AES), f"{tag} pre transfer")
        pre[pl.CMD_KEY_TRANSFER] = xfer.code
        # CHK-NOCHG-VAULT control: the AES key_valid bit (DEST_VALID bit 2) is set
        # after a transfer to AES, so an unchanged tap in the matrix is not a dead tap.
        _, kv_ctrl = await self._vault()
        aes_valid = (kv_ctrl >> 2) & 1
        shred = await self._cmd(pl.CMD_ENGINE_SHRED, (pl.SHRED_MASK,), f"{tag} pre shred")
        pre[pl.CMD_ENGINE_SHRED] = shred.code
        otp = await self._cmd(pl.CMD_OTP_READ_LOCK_COLD, (pl.OTP_LOCK_MASK,), f"{tag} pre otp")
        pre[pl.CMD_OTP_READ_LOCK_COLD] = otp.code
        hl = await self._cmd(
            pl.CMD_KEY_LOAD, (len(g.h_key) - 1, g.h_dest, *g.h_key), f"{tag} load h"
        )
        if hl.code != 0 or hl.arg is None or not hl.arg & 0xFF:
            raise AssertionError(f"[{tag}] the load of key h returned {hl.code} {_a(hl.arg)}")
        h = hl.arg & 0xFF
        self.logger.info(
            "LOG %s pre-fault codes=%s gen_h=%d load_h=%d h=%d aes_key_valid=%d",
            tag,
            {f"0x{c:02x}": v for c, v in pre.items()},
            gen_h,
            load_h,
            h,
            aes_valid,
        )

        # Steps 24 and 25: the fault, then the old sequence and sequence 0.
        e_old = self.e
        assert e_old != 0, f"[{tag}] e=0 before the fault"
        fault = await self._apply_cause(src, g.oflow_words, tag)
        pic_fault = await self._wait_pic31_high()
        fault_word = fault.payload[0] if fault.plen >= 1 else None
        f = await self._send_frame_raw(pl.cmd_frame(pl.CMD_STAT, e_old, []), f"{tag} old seq")
        old = self._parse_cmd(f, pl.CMD_STAT, e_old)
        s0 = await self._cmd(pl.CMD_STAT, (), f"{tag} seq0 CMD_STAT")
        persist = [await self._pic31()]
        first_seq_ok = fault.rid == pl.RESP_RECOVERABLE_FAULT and fault.seq == 0
        self.chk.ok(
            "CNT-RESET",
            first_seq_ok
            and old is not None
            and old.code == pl.RC_CMD_NOSEQ
            and old.arg == 0
            and s0.code == 0,
            leg="gate",
            cause=src,
            first_resp_seq=fault.seq,
            e_old=e_old,
            first_after=int(old is not None),
            old_seq_code=old.code if old else "none",
            arg=_a(old.arg) if old else "none",
            first_cmd_seq=0,
            first_cmd_code=s0.code,
        )

        # Step 26: the gate matrix.
        pays = self._gate_payloads(g, h)
        res: dict[int, _Resp] = {}
        changed: list[str] = []
        for c in g.order:
            if c in pl.ADMITTED:
                res[c] = await self._cmd(c, pays[c], f"{tag} matrix 0x{c:02x}")
                persist.append(await self._pic31())
                continue
            before = await self._vault()
            res[c] = await self._cmd(c, pays[c], f"{tag} matrix 0x{c:02x}")
            after = await self._vault()
            if before != after:
                changed.append(
                    f"0x{c:02x}:ctrl={before[0] ^ after[0]:#x}:kv={before[1]:#x}->{after[1]:#x}"
                )

        # Step 27: frame validation runs before the gate.
        right = pl.cmd_frame(pl.CMD_KEY_TRANSFER, self.e, [h, pl.DEST_AES])
        bad_hdr = list(right)
        bad_hdr[0] ^= g.vf_crc_xor << 24
        assert bad_hdr[0] != right[0], "validation-first header CRC is not wrong"
        vf_hdr = await self._send_words(bad_hdr, pl.CMD_KEY_TRANSFER, self.e, f"{tag} vf hdr")
        bad_pcrc = list(right)
        bad_pcrc[-1] ^= 1 << g.vf_flip_bit
        assert bad_pcrc[-1] != right[-1], "validation-first payload CRC is not wrong"
        vf_pcrc = await self._send_words(bad_pcrc, pl.CMD_KEY_TRANSFER, self.e, f"{tag} vf pcrc")
        self.e = (self.e + 1) & 0xFF
        vf_right = await self._cmd(pl.CMD_KEY_TRANSFER, (h, pl.DEST_AES), f"{tag} vf right")
        self.chk.ok(
            "VALID-FIRST",
            vf_hdr.code == pl.RC_HEADER_CRC
            and vf_pcrc.code == pl.RC_PAYLOAD_CRC
            and vf_right.code == pl.RC_FAILURE,
            source=src,
            cmd="0x24",
            hdr_crc_code=vf_hdr.code,
            payload_crc_code=vf_pcrc.code,
            right_frame_code=vf_right.code,
        )

        # Step 28: the drawn host delay, the acknowledge and CMD_STAT.
        if g.ack_delay:
            await ClockCycles(self.clk, g.ack_delay)
        persist.append(await self._pic31())
        ack = await self._cmd(pl.CMD_RECOV_ACK, (), f"{tag} CMD_RECOV_ACK")
        st2 = await self._cmd(pl.CMD_STAT, (), f"{tag} CMD_STAT after ack")
        pic_after = await self._pic31()

        # Step 29: the gate-clear twins, transfer before revoke.
        clear: dict[int, _Resp] = {}
        for c in (
            pl.CMD_KEY_GENERATE,
            pl.CMD_KEY_LOAD,
            pl.CMD_KEY_TRANSFER,
            pl.CMD_KEY_REVOKE,
            pl.CMD_ENGINE_SHRED,
            pl.CMD_OTP_READ_LOCK_COLD,
            pl.CMD_ABR_SK_TRANSFER,
        ):
            clear[c] = await self._cmd(c, pays[c], f"{tag} clear 0x{c:02x}")

        # CHK-GATE: each key and OTP command returns -1 with no argument under the
        # gate; its success before the fault and after the acknowledge shows that
        # the -1 is the gate and not the handler.
        for c in pl.KEY_OTP_WITNESSES:
            r = res[c]
            self.chk.ok(
                "GATE",
                r.code == pl.RC_FAILURE
                and r.arg is None
                and pre[c] == pl.RC_SUCCESS
                and clear[c].code == pl.RC_SUCCESS,
                source=src,
                cmd=f"0x{c:02x}",
                code=r.code,
                arg=_a(r.arg),
                pre_fault_code=pre[c],
                clear_code=clear[c].code,
            )
        # The handover commands: their handler results come from the handover legs.
        for c in pl.HANDOVER:
            r = res[c]
            self.chk.ok(
                "GATE",
                r.code == pl.RC_FAILURE and r.arg is None,
                source=src,
                cmd=f"0x{c:02x}",
                code=r.code,
                arg=_a(r.arg),
                control="handover_leg",
            )
        for c, r in (
            (pl.CMD_ABR_SK_TRANSFER, res[pl.CMD_ABR_SK_TRANSFER]),
            (pl.CMD_SRAM_VER, res[pl.CMD_SRAM_VER]),
        ):
            # Failure with no argument in both states: not a gate witness.
            self.logger.info(
                "LOG gate source=%s cmd=0x%02x code=%d arg=%s clear_code=%s witness=0",
                src,
                c,
                r.code,
                _a(r.arg),
                clear[c].code if c in clear else "na",
            )

        # CHK-ADMIT: the admitted queries reach their handlers under the gate.
        hw, rom, stat = res[pl.CMD_HW_VER], res[pl.CMD_ROM_VER], res[pl.CMD_STAT]
        self.chk.ok(
            "ADMIT",
            hw.code == 0 and hw.arg == KM_HW_VER_1_0_0,
            source=src,
            cmd="0x00",
            code=hw.code,
            ver=_a(hw.arg),
            golden=_a(KM_HW_VER_1_0_0),
        )
        self.chk.ok(
            "ADMIT",
            rom.code == 0 and rom.arg is not None and rom.arg >> 24 == 0,
            source=src,
            cmd="0x01",
            code=rom.code,
            ver=_a(rom.arg),
        )
        self.chk.ok(
            "ADMIT",
            stat.code == 0 and stat.arg == 1,
            source=src,
            cmd="0x03",
            code=stat.code,
            stat=_a(stat.arg),
        )

        # CHK-PERSIST: probe bit 31 after each admitted query and after the delay.
        self.chk.ok(
            "PERSIST",
            len(persist) == len(pl.ADMITTED) + 2 and all(v == 1 for v in persist),
            source=src,
            samples=len(persist),
            err_o=persist,
            delay_clk=g.ack_delay,
        )

        # CHK-NOCHG-VAULT: each gated command leaves KM-KPV CTRL and KM-VALID as they were.
        self.chk.ok(
            "NOCHG-VAULT",
            not changed and aes_valid == 1,
            leg="gate",
            source=src,
            gated=len(pl.GATED),
            changed=changed[:4],
            control_aes_key_valid=aes_valid,
        )

        # CHK-RECOVER.
        exp_code = pl.FAULT_RX_BUFF_OFLOW if src == "rx_oflow" else pl.FAULT_FLUSHED_BY_SEP
        frames_one = old is not None
        gated = res[pl.CMD_KEY_TRANSFER]
        gated_ok = gated.code == pl.RC_FAILURE and gated.arg is None
        gated_after_ok = clear[pl.CMD_KEY_TRANSFER].code == pl.RC_SUCCESS
        control_ok = pre[pl.CMD_KEY_TRANSFER] == pl.RC_SUCCESS
        code_ok = fault.plen == 1 and fault_word == (exp_code & pl.WORD_MASK)
        stat_ok = s0.code == 0 and s0.arg == 1
        ack_ok = ack.code == 0 and ack.arg is None
        stat_after_ok = st2.code == 0 and st2.arg == 0
        pic_ok = pic_fault and pic_after == 0
        cond = frames_one and first_seq_ok and gated_ok and gated_after_ok and control_ok
        if src == "rx_oflow":
            cond = cond and code_ok and stat_ok and ack_ok and stat_after_ok and pic_ok
        self.chk.ok(
            "RECOVER",
            cond,
            cause=src,
            frames=1 if frames_one else "paired",
            code=pl.signed8(fault_word) if fault_word is not None else "none",
            code_word=_a(fault_word),
            first_seq=fault.seq,
            stat=_a(s0.arg),
            gated=gated.code,
            gated_arg=_a(gated.arg),
            ack=ack.code,
            ack_arg=_a(ack.arg),
            stat_after=_a(st2.arg),
            gated_after=clear[pl.CMD_KEY_TRANSFER].code,
            pic31=[int(pic_fault), pic_after],
            pre_fault_code=pre[pl.CMD_KEY_TRANSFER],
            control=1 if src == "flush" else 0,
        )

    # -------------------------------------------------------- handover legs

    async def _handover_leg(self, hd: pl.HandoverDraw) -> None:
        """Steps 30 to 32 for one handover command."""
        c = hd.cmd
        tag = f"handover 0x{c:02x}"
        pay = (0,) if c == pl.CMD_SRAM_LOAD_EXEC else ()
        await self._warm_reset(tag)
        fault = await self._apply_cause(hd.source, hd.oflow_words, tag)
        fault_ok = fault.rid == pl.RESP_RECOVERABLE_FAULT and fault.seq == 0
        gated = await self._cmd(c, pay, f"{tag} gated")
        st_before = await self._cmd(pl.CMD_STAT, (), f"{tag} CMD_STAT before reset")
        pic_before = await self._pic31()

        await self._warm_reset(f"{tag} clear")
        st = await self._cmd(pl.CMD_STAT, (), f"{tag} CMD_STAT after reset")
        pic = await self._pic31()
        # Control: CMD_STAT bit 0 and the probe read 1 before the reset, so a 0
        # after it is the reset.
        stat_before_ok = (
            st_before.code == 0 and st_before.arg is not None and (st_before.arg & 1) == 1
        )
        self.chk.ok(
            "RESET-CLR",
            st.code == 0 and st.arg == 0 and pic == 0 and pic_before == 1 and stat_before_ok,
            cmd=f"0x{c:02x}",
            source=hd.source,
            stat=_a(st.arg),
            err_o=pic,
            control_stat_before=_a(st_before.arg),
            control_err_o_before=pic_before,
        )

        first = await self._cmd(c, pay, f"{tag} first handover command")
        if c == pl.CMD_EXEC_ROM:
            first_ok = first.code == pl.RC_SUCCESS
        elif c == pl.CMD_SRAM_LOAD_EXEC:
            first_ok = first.code == pl.RC_INVALID_ARG and first.arg == 0
        else:
            first_ok = first.code == pl.RC_INVALID_ARG and first.arg is None
        self.chk.ok(
            "GATE",
            fault_ok and gated.code == pl.RC_FAILURE and gated.arg is None and first_ok,
            source=hd.source,
            cmd=f"0x{c:02x}",
            code=gated.code,
            arg=_a(gated.arg),
            first_seq=0,
            clear_code=first.code,
            clear_arg=_a(first.arg),
        )

    # ---------------------------------------------------- overflow pending

    async def _drain_raw(self, tag: str) -> list[int]:
        """Read SEP_READ_DATA word by word until ``outbound_depth`` stays 0."""
        words: list[int] = []
        idle = 0
        while idle < _DRAIN_IDLE_POLLS and len(words) < _DRAIN_MAX_WORDS:
            status = await self._rd(KM_MBOX_STATUS)
            depth = (status >> KM_STATUS_OUTBOUND_DEPTH_LSB) & KM_STATUS_OUTBOUND_DEPTH_MASK
            if depth:
                words.append(await self._rd(KM_MBOX_READ_DATA))
                idle = 0
            else:
                idle += 1
                await ClockCycles(self.clk, _POLL_GAP)
        self.logger.info(
            "LOG %s drained=%d words=%s", tag, len(words), [hex(w) for w in words[:40]]
        )
        return words

    async def _oflow_pend_leg(self) -> None:
        """Step 40: rx_buff_oflow while responses wait in the outbound FIFO and the TX buffer."""
        tag = "oflow pend"
        await self._warm_reset(tag)
        q = self.plan.oflow_q
        for i in range(q):
            await self._write_words(
                pl.cmd_frame(pl.CMD_HW_VER, self.e, []), separator=True, tag=f"{tag} q{i}"
            )
            self.e = (self.e + 1) & 0xFF
        # Control: a response is pending when outbound_full reads 1.
        full = 0
        for _ in range(_OUT_FULL_POLLS):
            if (await self._rd(KM_MBOX_STATUS) >> KM_STATUS_OUTBOUND_FULL) & 1:
                full = 1
                break
            await ClockCycles(self.clk, _POLL_GAP)
        if not full:
            raise AssertionError(
                f"[{tag}] SEP_STATUS.outbound_full did not read 1 within {_OUT_FULL_POLLS} polls "
                f"after {q} unread CMD_HW_VER frames"
            )
        words = self.plan.oflow_words
        assert len(words) == pl.RX_BUFFER_WORDS and all(words)
        await self._write_words(words, separator=False, tag=f"{tag} rx_oflow")
        await ClockCycles(self.clk, _OFLOW_SETTLE)
        got = await self._drain_raw(tag)

        fault_hdr = pl.header(pl.RESP_RECOVERABLE_FAULT, 0, 1)
        hdr = got[0] if got else None
        first_ok = hdr == fault_hdr
        code_ok = (
            first_ok
            and len(got) >= _FAULT_HDR_WORDS
            and got[1] == (pl.FAULT_RX_BUFF_OFLOW & pl.WORD_MASK)
            and got[2] == pl.payload_crc([got[1]])
        )
        # Stale words: after the fault frame when it comes first, else the words
        # before the first fault header (all words when none is read).
        if first_ok:
            stale = len(got) - _FAULT_HDR_WORDS
        else:
            stale = got.index(fault_hdr) if fault_hdr in got else len(got)
        self.chk.ok(
            "OFLOW-PEND",
            full == 1 and first_ok and code_ok and stale == 0,
            q=q,
            outbound_full_before=full,
            first_word=_a(hdr),
            first_rid=f"0x{(hdr >> 8) & 0xFF:02x}" if hdr is not None else "none",
            seq=hdr & 0xFF if hdr is not None else "none",
            code=pl.signed8(got[1]) if first_ok and len(got) > 1 else "none",
            stale_words=stale,
            words_read=len(got),
        )
        self.r, self.e = 1, 0
        ack = await self._cmd(pl.CMD_RECOV_ACK, (), f"{tag} CMD_RECOV_ACK")
        self.logger.info("LOG %s CMD_RECOV_ACK code=%d arg=%s", tag, ack.code, _a(ack.arg))
