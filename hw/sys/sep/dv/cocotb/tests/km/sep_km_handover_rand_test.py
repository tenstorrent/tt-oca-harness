# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""KM SRAM image load refusals, the fw_crc fault, and the KM state at the handover jump.

no_cpu (``lsu_stub_all_live``) / real fuse sense / ``+esrc_noise_force`` /
``+km_rom_hex=rom_main.rom.parhex`` (the bench build of ``rom_main``: the boot
wipe and the SRAM wipe of the fatal handler are off). The testbench LSU master
is the SEP host and reaches the KM only through ``km_mailbox_sep``.

Images. The spin image (``env/sep_km_img_h.py``, ``spin_image``) is a drawn image
whose word 0 jumps to itself. IMG-H (``tests/km_fw/km_img_h.S``, committed as
``tests/km_img_h.parhex``) runs after the handover and sends the KM state that
it reads at the jump to the host as one 263-word KM mailbox message, decoded by
``env/sep_km_img_h.py``. The images grade nothing; every golden is in this leaf
and its model (``sep_km_handover_rand_model.py``), from
``hw/ip/key_manager/doc/firmware.adoc`` ("0x11 - CMD_SRAM_LOAD_EXEC",
"0x12 - CMD_SRAM_EXEC", "0xFF - RESP_UNRECOVERABLE_FAULT", "Error Recovery",
"SRAM Firmware Handover", "ROM Stack Budget and the Static Load Ceiling"),
``hw/ip/key_manager/doc/architecture.adoc`` ("OTP Inputs and Readout", "Key and
Policy Vault (KPV)", "Key Manager CPU Interrupt Processing") and the generated
Key Manager register map.

Probes: ``HOST-MBX`` (``SEP_STATUS``, ``SEP_READ_DATA``, ``SEP_IRQ_STATUS``),
``PIC-IRQ`` bit 30 (``sep_ras_o.km_uncorrectable``), ``KM-COUNT``
(``km_sram_write_count_o``), and the read-only taps ``KM-BUS``
(``km_key_aw_*``) and ``KM-VALID`` (``km_engine_key_valid_o``,
``km_abr_sk_valid_o``, ``km_abr_sk_key_o``). No inject: the flipped image bit
and the refused FW_WORDS values are legal host stimulus.

Plan (``SepSeededRng`` from the run seed). RAND-REP for the load legs: the good
size n1 and the corrupted size n2 in [8, 256], the flipped position (word 0,
the last word, the trailer or a drawn word) and bit (0, 31 or a drawn bit), one
oversize FW_WORDS in [8193, 0xFFFE], one mid size in [n1 + 1, 8191], and the
image words. 8192 and 0xFFFF run on every seed. RAND-NONE for the state leg:
the pre-state of each pass is directed; the seed draws the key words, the
staged OTP words and the junk words only.

Checks:
  CHK-FWCRC           a flipped image or trailer bit gives exactly one
                      RESP_UNRECOVERABLE_FAULT 0xFFFFFFF2, no other frame, and
                      PIC bit 30 rises and stays 1 over 8 times its rise time.
  CHK-SIZE-REJ        FW_WORDS 8192, 0xFFFF and the drawn oversize value return
                      invalid_arg with argument 0 and no image request (the
                      CMD_STAT reply is the next frame); FW_WORDS 0 returns
                      argument 0 and no image request (its code is a control).
  CHK-HO-FIRST        the first word after the confirmation (pass 1: and the
                      stream) is the IMG-H MAGIC, not RESP_KM_READY.
  CHK-HO-REGS         IRQ_ENABLE 0, KM_IRQ_ENABLE 0, IRQ_ENTRY_ADDR 0x10,
                      IRQ_ENTRY_LOCK 0, CPU IRQ mask bits 3 to 5 set,
                      SRAM_EXEC_MODE.enable 1 at the jump.
  CHK-HO-NOIRQ        every IRQ_STATUS bit reads 0 at the jump.
  CHK-HO-ENTRY        x5 = 0x8000, every other reported GPR 0.
  CHK-HO-OTP          OTP_READ_LOCK: the four secret bits set; the public and
                      life-cycle bits clear.
  CHK-HO-KPV-LOCK     every registered slot has lock_use and reads 0 with
                      AXI_SLVERR; every other slot has CTRL 0.
  CHK-HO-SIDELOAD     no bank key_valid and no shared-key key_valid at the jump.
  CHK-HO-SK-WORDS     the eight shared-key KEY words read 0 at the jump of the
                      pass that hands over with the shared key pending.
  CHK-HO-SIDELOAD-BUS every (share, word) address of the eight bank windows is
                      written after the handover command, also in empty banks.
  CHK-HO-SRAM         SRAM_LOCK = 0x80000001 and every word of every unlocked
                      region is written before the jump (KM-WMAP-JUMP).
  CHK-HO-MBOX         KM_STATUS.inbound_empty = 1 at the jump.

Controls: PIC bit 30 reads 0 in a quiet window before the corrupted load and
after the good load; the good size n1 gets the confirmation; the read path of
each locked-slot read shows AXI_SLVERR; the free-slot word and the KMAC
KEY_CTRL write and readback show a live read path; pass 1 posts 6 junk words;
pass 2 has six banks with no key; the pass 1 shared key is pending and its KEY
words are non-zero before the handover. The cells that ``sep_km_handover_test`` grades (the code of FW_WORDS
0, CMD_SRAM_EXEC after a good load) run here as controls with ``control=1``.

Logged only: the response to the mid size (``OBS-SIZE-MID``), the shared-key
words at the jump of each pass (``OBS-HO-SK-WORDS``), the VAL_0 reads of the OTP fields, the
SRAM store and violation readbacks, the demotion lock bit and the full CPU IRQ
mask. CHK-HO-NOIRQ and CHK-HO-SK-WORDS can fail on this DUT (contract, "Known
limitation").
"""

from __future__ import annotations

import hashlib

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, Event, FallingEdge, ReadOnly, RisingEdge
from env import sep_km_img_h as imgh
from env.sep_chk_log import SepChkLog
from env.sep_efuse_image import LC_PROD, SepEfuseImage
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_km_fuse_plan import OTP_DUAL_RAIL_FIELDS
from env.sep_spec_tables import agg_from_pic
from km import sep_km_handover_rand_model as md
from sep_base_test import sep_base_test
from seq_lib.sep_abr_mlkem_seq import (
    KEM_CMD_ENCAPS,
    KEM_CMD_KEYGEN,
    KEM_CTRL_ZEROIZE,
    KEM_EK_WORDS,
    KEM_ST_ERROR,
    KEM_ST_READY,
    KEM_ST_VALID,
    KV_READ_EN,
    KV_WRITE_EN,
    MLKEM_CTRL,
    MLKEM_ENCAPS_KEY,
    MLKEM_KV_MSG_RD_CTRL,
    MLKEM_KV_SK_WR_CTRL,
    MLKEM_SEED_D,
    MLKEM_SEED_Z,
    MLKEM_STATUS,
    SepAbrMlkem,
)
from seq_lib.sep_aes_seq import SepAes
from seq_lib.sep_hmac_seq import SepHmac
from seq_lib.sep_km_mailbox_seq import (
    KM_CMD_KEY_LOAD,
    KM_CMD_SRAM_EXEC,
    KM_CMD_SRAM_LOAD_EXEC,
    KM_CMD_STAT,
    KM_IRQ_FLUSHED_BY_KM,
    KM_MBOX_DEPTH,
    KM_RC_INVALID_ARG,
    KM_RC_SUCCESS,
    KM_RESP_ABR_SHARED_KEY_READY,
    KM_RESP_CMD,
    KM_RESP_UNRECOVERABLE_FAULT,
    KM_STATUS_INBOUND_DEPTH_LSB,
    KM_STATUS_INBOUND_DEPTH_MASK,
    KM_STATUS_OUTBOUND_DEPTH_LSB,
    KM_STATUS_OUTBOUND_DEPTH_MASK,
    KM_STATUS_OUTBOUND_EMPTY,
    KM_STATUS_OUTBOUND_SEPARATOR,
    RESP_OKAY,
    SepKmMailbox,
    crc8_rohc,
    crc32c,
)
from seq_lib.sep_kmac_seq import SepKmac
from seq_lib.sep_otbn_seq import SepOtbn

TEST = md.TEST
KM_UNREC_BIT = agg_from_pic("KM unrecoverable error")  # PIC vector bit 30

# Bounded waits, in host clocks or mailbox polls. Each expiry fails the leaf
# with a named message.
SEP_RESET_BOUND = 20_000  # clocks for dbg_sep_reset_n_o after the fuse sense
POLL = 20  # clocks between two mailbox status polls
FRAME_POLLS = 20_000  # polls for one response frame
IMG_FIRST_POLLS = 250_000  # polls for the first IMG-H word (the handover runs first)
IMG_WORD_POLLS = 20_000  # polls for each later batch of IMG-H words
INBOUND_POLLS = 20_000  # polls for inbound FIFO space while streaming
FLUSH_POLLS = 50_000  # polls for FLUSHED_BY_KM after the good stream
RISE_BOUND = 4_000_000  # clocks from the trailer write to the PIC bit 30 rise
QUIET_CLKS = 512  # quiet window of PIC bit 30
GOOD_WINDOW_CLKS = 4_000  # frame record window after the good load
HOLD_FACTOR = 8  # hold window = 8 x the rise time
KEM_POLLS = 20_000
KEM_GAP = 200

# Directed ML-KEM seed of the register KEYGEN that gives the encapsulation key
# of the pass 1 ENCAPS (test vectors, pairwise different, no zero word).
_KEM_D = (
    0x0BADC0DE,
    0x13572468,
    0xA5A5A5A5,
    0xFEEDFACE,
    0x2468ACE0,
    0x5A5A0F0F,
    0x97531ECA,
    0x600DF00D,
)
_KEM_Z = (
    0x1234ABCD,
    0x0F0F0F0F,
    0xC0FFEE00,
    0x5EED5EED,
    0x7E57CA5E,
    0x31415926,
    0x4B1D2C3E,
    0x8BADF00D,
)

# Report field name of each staged OTP field (env/sep_km_img_h.py), in the
# OTP_READ_LOCK bit order 2 to 8.
_OTP_REPORT_NAME = dict(
    zip(OTP_DUAL_RAIL_FIELDS, imgh.SECRET_FIELDS + imgh.PUBLIC_FIELDS, strict=True)
)


def _signed8(v: int) -> int:
    v &= 0xFF
    return v - 256 if v >= 128 else v


def _hx(v: int) -> str:
    return f"0x{v & 0xFFFF_FFFF:08x}"


class _Frame:
    """One response frame read from SEP_READ_DATA (header CRC and length checked)."""

    def __init__(self, words: list[int]) -> None:
        self.words = words
        hdr = words[0]
        self.seq = hdr & 0xFF
        self.resp_id = (hdr >> 8) & 0xFF
        self.payload_len = (hdr >> 16) & 0xFF
        self.payload = words[1 : 1 + self.payload_len]

    def resp_cmd(self, cmd_id: int, cmd_seq: int) -> tuple[int | None, int | None]:
        """(return code, return argument or None) of a RESP_CMD for this command.

        The code is None when the frame is not a RESP_CMD echo of the command.
        """
        p = self.payload
        if (
            self.resp_id != KM_RESP_CMD
            or len(p) < 3
            or (p[0] & 0xFF) != (cmd_seq & 0xFF)
            or (p[1] & 0xFF) != (cmd_id & 0xFF)
        ):
            return None, None
        return _signed8(p[2]), (p[3] if len(p) >= 4 else None)

    def text(self) -> str:
        return "[" + ",".join(_hx(w) for w in self.words) + "]"


class _KeyBusWatch:
    """KM-BUS: the (port, low address bits) of every completed AW handshake."""

    def __init__(self, test: sep_base_test) -> None:
        dut = cocotb.top
        self.test = test
        self.clk = dut.clk_i
        self.valid = dut.km_key_aw_valid_o
        self.ready = dut.km_key_aw_ready_o
        self.addr = dut.km_key_aw_addr_o
        self.writes: set[tuple[int, int]] = set()
        self.count = 0
        self._on = False

    def start(self) -> None:
        self.writes = set()
        self.count = 0
        self._on = True
        cocotb.start_soon(self._run())

    async def stop(self) -> None:
        self._on = False
        await ClockCycles(self.clk, 2)

    async def _run(self) -> None:
        while True:
            await RisingEdge(self.clk)
            await ReadOnly()
            if not self._on:
                return
            # An unknown valid or ready reads 0: a lost handshake fails closed.
            hs = self.test.rd(self.valid, allow_unknown=True) & self.test.rd(
                self.ready, allow_unknown=True
            )
            if not hs:
                continue
            mask = 0
            for i in range(5):
                if (hs >> i) & 1:
                    mask |= 0xFFFF_FFFF << (32 * i)
            addr = self.test.rd_known(self.addr, mask=mask)
            for i in range(5):
                if (hs >> i) & 1:
                    self.writes.add((i, (addr >> (32 * i)) & md.WINDOW_MASK))
                    self.count += 1


class _RiseHold:
    """PIC bit 30 on every clock: the rise after the trailer, then the hold window."""

    def __init__(self, test: sep_base_test) -> None:
        self.test = test
        self.clk = cocotb.top.clk_i
        self.vec = cocotb.top.sep_internal_interrupts_probe_o
        self.cyc = 0
        self.trailer: int | None = None
        self.rise: int | None = None
        self.hold = 0
        self.held_samples = 0
        self.low_samples = 0
        self.timed_out = False
        self.done = Event()

    def bit(self) -> int:
        return (self.test.rd_known(self.vec, mask=1 << KM_UNREC_BIT) >> KM_UNREC_BIT) & 1

    def start(self) -> None:
        cocotb.start_soon(self._run())

    def mark_trailer(self) -> None:
        self.trailer = self.cyc

    @property
    def rise_clk(self) -> int | None:
        if self.rise is None or self.trailer is None:
            return None
        return self.rise - self.trailer

    async def _run(self) -> None:
        while True:
            await RisingEdge(self.clk)
            await ReadOnly()
            self.cyc += 1
            v = self.bit()
            if self.rise is None:
                if v:
                    self.rise = self.cyc
                    r = self.rise_clk
                    self.hold = HOLD_FACTOR * max(r if r is not None else 0, 1)
                elif self.trailer is not None and self.cyc - self.trailer > RISE_BOUND:
                    self.timed_out = True
                    self.done.set()
                    return
                continue
            self.held_samples += 1
            self.low_samples += 1 - v
            if self.held_samples >= self.hold:
                self.done.set()
                return


@pyuvm.test()
class sep_km_handover_rand_test(sep_base_test):
    """Image load refusals, the fw_crc fault and the KM state at the handover jump."""

    required_evidence = (
        "CHK-FWCRC",
        "CHK-SIZE-REJ",
        "CHK-HO-FIRST",
        "CHK-HO-REGS",
        "CHK-HO-NOIRQ",
        "CHK-HO-ENTRY",
        "CHK-HO-OTP",
        "CHK-HO-KPV-LOCK",
        "CHK-HO-SIDELOAD",
        "CHK-HO-SK-WORDS",
        "CHK-HO-SIDELOAD-BUS",
        "CHK-HO-SRAM",
        "CHK-HO-MBOX",
    )

    # --- probes ---------------------------------------------------------------
    def _pic30(self) -> int:
        vec = self.rd_known(cocotb.top.sep_internal_interrupts_probe_o, mask=1 << KM_UNREC_BIT)
        return (vec >> KM_UNREC_BIT) & 1

    def _sram_writes(self) -> int:
        return self.rd_known(cocotb.top.km_sram_write_count_o)

    async def _wmap_clear(self) -> None:
        """KM-WMAP: clear the distinct-word counts. The clear is held to the
        falling edge, so the rising edge that the model evaluates samples it."""
        cocotb.top.km_sram_wmap_clr_i.value = 1
        await RisingEdge(cocotb.top.clk_i)
        await FallingEdge(cocotb.top.clk_i)
        cocotb.top.km_sram_wmap_clr_i.value = 0

    def _wmap_regions(self) -> list[int]:
        """KM-WMAP: the distinct words written in each SRAM write-lock region."""
        v = self.rd_known(cocotb.top.km_sram_wmap_region_o)
        return [(v >> (9 * r)) & 0x1FF for r in range(md.N_REGIONS)]

    def _wmap_jump(self) -> tuple[int, int, list[int]]:
        """KM-WMAP-JUMP: the capture flag, the SRAM write count and the KM-WMAP
        counts at the jump."""
        seen = self.rd_known(cocotb.top.km_sram_wmap_jump_seen_o)
        wr = self.rd_known(cocotb.top.km_sram_wmap_jump_wr_o)
        v = self.rd_known(cocotb.top.km_sram_wmap_jump_o)
        return seen, wr, [(v >> (9 * r)) & 0x1FF for r in range(md.N_REGIONS)]

    def _bank_valid(self) -> int:
        return self.rd_known(cocotb.top.km_engine_key_valid_o)

    def _sk_valid(self) -> int:
        return self.rd_known(cocotb.top.km_abr_sk_valid_o)

    def _sk_words(self) -> list[int]:
        v = self.rd_known(cocotb.top.km_abr_sk_key_o)
        return [(v >> (32 * i)) & 0xFFFF_FFFF for i in range(8)]

    async def _quiet_pic30(self, clks: int) -> int:
        """Clocks with PIC bit 30 high over ``clks`` clocks."""
        high = 0
        for _ in range(clks):
            await RisingEdge(cocotb.top.clk_i)
            await ReadOnly()
            high += self._pic30()
        return high

    async def _graded(self, on: bool) -> None:
        # The gate is a signal write, which cocotb refuses in the ReadOnly phase.
        await RisingEdge(cocotb.top.clk_i)
        if on:
            open_graded_window(TEST, self.logger)
        else:
            close_graded_window(self.logger)

    # --- mailbox transport ------------------------------------------------------
    async def _status(self) -> int:
        return await self.km.read_status()

    async def _post(self, words: list[int]) -> None:
        """Write ``words`` to SEP_WRITE_DATA, the separator on the last word.

        The writer waits for space in the 16-word inbound FIFO, so a frame or
        an image longer than the FIFO never overflows it.
        """
        i = 0
        while i < len(words):
            for _ in range(INBOUND_POLLS):
                depth = (
                    await self._status() >> KM_STATUS_INBOUND_DEPTH_LSB
                ) & KM_STATUS_INBOUND_DEPTH_MASK
                if depth < KM_MBOX_DEPTH:
                    break
                await ClockCycles(cocotb.top.clk_i, POLL)
            else:
                raise AssertionError(
                    f"the inbound FIFO stayed full for {INBOUND_POLLS} polls at word {i} "
                    f"of {len(words)}"
                )
            for _ in range(KM_MBOX_DEPTH - depth):
                if i == len(words) - 1:
                    await self.km.post_raw_words([words[i]])
                else:
                    resp = await self.km.write_data_raw(words[i])
                    if resp != RESP_OKAY:
                        raise AssertionError(f"SEP_WRITE_DATA write {i} answered resp={resp}")
                i += 1
                if i == len(words):
                    break

    async def _read_word(self, polls: int) -> int | None:
        """One word of SEP_READ_DATA, or None if the outbound FIFO stays empty."""
        for _ in range(polls):
            if not (await self._status() & (1 << KM_STATUS_OUTBOUND_EMPTY)):
                resp, data = await self.km.read_data_raw()
                if resp != RESP_OKAY:
                    raise AssertionError(f"SEP_READ_DATA read answered resp={resp}")
                return data
            await ClockCycles(cocotb.top.clk_i, POLL)
        return None

    async def _read_words(self, n: int, what: str) -> tuple[list[int], int]:
        """``n`` outbound words read in batches, and SEP_STATUS after the last one."""
        out: list[int] = []
        while len(out) < n:
            for _ in range(IMG_WORD_POLLS):
                st = await self._status()
                depth = (st >> KM_STATUS_OUTBOUND_DEPTH_LSB) & KM_STATUS_OUTBOUND_DEPTH_MASK
                if depth:
                    break
                await ClockCycles(cocotb.top.clk_i, POLL)
            else:
                raise AssertionError(
                    f"{what}: no outbound word for {IMG_WORD_POLLS} polls after word {len(out)} "
                    f"of {n}"
                )
            for _ in range(min(depth, n - len(out))):
                resp, data = await self.km.read_data_raw()
                if resp != RESP_OKAY:
                    raise AssertionError(f"{what}: SEP_READ_DATA answered resp={resp}")
                out.append(data)
        return out, await self._status()

    async def _read_frame(self, polls: int = FRAME_POLLS) -> _Frame | None:
        """One response frame, or None if no word arrives within ``polls`` polls.

        The header CRC-8, the declared length and the payload CRC-32C are
        checked (firmware.adoc, frame format); a malformed frame fails the leaf.
        The response sequence number is not checked here.
        """
        first = await self._read_word(polls)
        if first is None:
            return None
        words = [first]
        while not (await self._status() & (1 << KM_STATUS_OUTBOUND_SEPARATOR)):
            if len(words) >= 32:
                raise AssertionError(f"response frame of 32 words without a separator: {words}")
            w = await self._read_word(FRAME_POLLS)
            if w is None:
                raise AssertionError(f"response frame stopped after {len(words)} words")
            words.append(w)
        fr = _Frame(words)
        hdr_crc = (first >> 24) & 0xFF
        exp_crc = crc8_rohc(bytes([fr.seq, fr.resp_id, fr.payload_len]))
        exp_len = 1 + fr.payload_len + (1 if fr.payload_len else 0)
        if hdr_crc != exp_crc or len(words) != exp_len:
            raise AssertionError(f"malformed response frame {fr.text()}")
        if fr.payload_len:
            body = b"".join(w.to_bytes(4, "little") for w in fr.payload)
            if words[-1] != crc32c(body):
                raise AssertionError(f"response frame payload CRC-32C mismatch {fr.text()}")
        return fr

    # --- resets ---------------------------------------------------------------------
    async def _wait_sep_reset_release(self) -> None:
        for _ in range(SEP_RESET_BOUND):
            await RisingEdge(cocotb.top.clk_i)
            await ReadOnly()
            if self.rd(cocotb.top.dbg_sep_reset_n_o, allow_unknown=True):
                return
        raise AssertionError(
            f"dbg_sep_reset_n_o did not read 1 within {SEP_RESET_BOUND} clocks; the KM "
            "release would be lost"
        )

    async def _warm(self, what: str) -> None:
        """Warm reset: SW_RESET_N bit 0 low, then high, the other bits at 1."""
        await self._graded(False)
        await self.swrst.park("km")
        await self.swrst.release("km")
        self.km.reset_host_seq()
        await self.km.wait_km_ready()
        self.logger.info("LOG warm boot (%s) SW_RESET_N=0x%08x", what, self.swrst.value)

    # --- key setup ------------------------------------------------------------------
    async def _key_load(self, words: list[int], dest: int) -> int:
        """CMD_KEY_LOAD through the FIFO-paced writer; returns the handle."""
        seq = self.km.seq_num
        payload = [len(words) - 1, dest] + list(words)
        await self._post(self.km.build_frame(KM_CMD_KEY_LOAD, seq, payload))
        self.km.seq_num = (seq + 1) & 0xFF
        rc, arg = await self.km.recv_resp_cmd(KM_CMD_KEY_LOAD, seq, require_arg=True)
        handle = arg & 0xFF
        if rc != KM_RC_SUCCESS or handle == 0:
            raise AssertionError(
                f"precondition: CMD_KEY_LOAD of {len(words)} words dest=0x{dest:02x} "
                f"rc={rc} arg={_hx(arg)}"
            )
        return handle

    async def _load_and_transfer(self, keys, plan_keys) -> int:
        """Load each key and transfer it to its DEST_VALID; the OR of the completed masks."""
        done = 0
        for words, (n, dest) in zip(keys, plan_keys, strict=True):
            assert len(words) == n
            handle = await self._key_load(words, dest)
            rc, arg = await self.km.key_transfer(handle=handle, dest=dest)
            got = (arg >> 8) & 0xFF
            if rc != KM_RC_SUCCESS or got != dest:
                raise AssertionError(
                    f"precondition: CMD_KEY_TRANSFER handle=0x{handle:02x} dest=0x{dest:02x} "
                    f"rc={rc} completed=0x{got:02x}"
                )
            done |= got
            self.logger.info(
                "LOG key words=%d slots=%d handle=0x%02x dest=0x%02x completed=0x%02x",
                n,
                md.slots_of(n),
                handle,
                dest,
                got,
            )
        return done

    async def _kem_wait(self, mask: int, expect: int, what: str) -> int:
        for _ in range(KEM_POLLS):
            st = await self.kem.rd32(MLKEM_STATUS)
            if st & KEM_ST_ERROR:
                raise AssertionError(f"precondition: {what}: ML-KEM STATUS.ERROR (0x{st:08x})")
            if (st & mask) == expect:
                return st
            await ClockCycles(cocotb.top.clk_i, KEM_GAP)
        raise AssertionError(f"precondition: {what}: ML-KEM STATUS never 0x{expect:x}")

    async def _kem_keygen(self) -> list[int]:
        """Register KEYGEN of the directed seed; returns the encapsulation key."""
        await self._kem_wait(KEM_ST_READY, KEM_ST_READY, "keygen READY")
        await self.kem.write_words(MLKEM_SEED_D, list(_KEM_D))
        await self.kem.write_words(MLKEM_SEED_Z, list(_KEM_Z))
        await self.kem.wr32(MLKEM_CTRL, KEM_CMD_KEYGEN)
        await self._kem_wait(KEM_ST_VALID, KEM_ST_VALID, "keygen VALID")
        ek = await self.kem.read_words(MLKEM_ENCAPS_KEY, KEM_EK_WORDS)
        if not any(ek):
            raise AssertionError("precondition: the ML-KEM encapsulation key reads all zero")
        await self.kem.wr32(MLKEM_CTRL, KEM_CTRL_ZEROIZE)
        await self._kem_wait(KEM_ST_VALID, 0, "zeroize VALID clear")
        return ek

    async def _kem_encaps_pending(self, ek: list[int]) -> None:
        """ENCAPS with the message from the KM message bank and the shared key
        written back to the KM; then read RESP_ABR_SHARED_KEY_READY."""
        await self._kem_wait(KEM_ST_READY, KEM_ST_READY, "encaps READY")
        await self.kem.wr32(MLKEM_KV_MSG_RD_CTRL, KV_READ_EN)
        await self.kem.wr32(MLKEM_KV_SK_WR_CTRL, KV_WRITE_EN)
        await self.kem.write_words(MLKEM_ENCAPS_KEY, list(ek))
        await self.kem.wr32(MLKEM_CTRL, KEM_CMD_ENCAPS)
        await self._kem_wait(KEM_ST_VALID, KEM_ST_VALID, "encaps VALID")
        notify = await self.km.recv_unsolicited(KM_RESP_ABR_SHARED_KEY_READY)
        self.logger.info("LOG RESP_ABR_SHARED_KEY_READY frame=%s", [_hx(w) for w in notify])

    # --- load legs --------------------------------------------------------------------
    async def _good_load(self) -> None:
        """Step 2: a good spin image of n1 words, then step 3."""
        p = self.plan
        seq = await self.km.send_command(KM_CMD_SRAM_LOAD_EXEC, [p.n1])
        rc, arg = await self.km.recv_resp_cmd(KM_CMD_SRAM_LOAD_EXEC, seq)
        # Control of CHK-SIZE-REJ: the accepted size gets the confirmation.
        self.chk.ctrl("SIZE-REJ-ACCEPT", rc == KM_RC_SUCCESS, words=p.n1, code=rc)
        # The boot flush left FLUSHED_BY_KM set; clear it so that only the
        # handover flush sets it again. The flush follows the store of the image
        # size (firmware.adoc, "SRAM Firmware Handover"), so the warm reset of
        # step 3 waits for it.
        await self.km.write_irq_status(1 << KM_IRQ_FLUSHED_BY_KM)
        irq = await self.km.read_irq_status()
        if irq & (1 << KM_IRQ_FLUSHED_BY_KM):
            raise AssertionError(f"FLUSHED_BY_KM still set after its W1C (0x{irq:08x})")
        await self._post(imgh.stream_words(p.good_image))
        for _ in range(FLUSH_POLLS):
            irq = await self.km.read_irq_status()
            if irq & (1 << KM_IRQ_FLUSHED_BY_KM):
                break
            await ClockCycles(cocotb.top.clk_i, POLL)
        else:
            raise AssertionError(
                f"the handover flush (FLUSHED_BY_KM) never followed the good stream of {p.n1} words"
            )
        frames: list[_Frame] = []
        high = 0
        for _ in range(GOOD_WINDOW_CLKS // 64):
            high += await self._quiet_pic30(16)
            if not (await self._status() & (1 << KM_STATUS_OUTBOUND_EMPTY)):
                fr = await self._read_frame(FRAME_POLLS)
                if fr is not None:
                    frames.append(fr)
            await ClockCycles(cocotb.top.clk_i, 32)
        self.chk.obs(
            "LOAD-GOOD",
            control=1,
            n=p.n1,
            first_resp=0,
            first_code=rc,
            first_arg=_hx(arg),
            frames_after_stream=len(frames),
            frame_ids=[f"0x{f.resp_id:02x}" for f in frames] or "-",
        )
        # Control of CHK-FWCRC: the good load raises no fault.
        fault = any(f.resp_id == KM_RESP_UNRECOVERABLE_FAULT for f in frames)
        self.chk.ctrl("FWCRC-GOOD", high == 0 and not fault, pic30_high=high, fault_frame=fault)

        # Step 3: CMD_SRAM_EXEC after a warm reset (a cell of sep_km_handover_test).
        await self._warm("after the good load")
        seq = await self.km.send_command(KM_CMD_SRAM_EXEC, [])
        rc, _ = await self.km.recv_resp_cmd(KM_CMD_SRAM_EXEC, seq)
        self.chk.obs("EXEC-AFTER-LOAD", control=1, code=rc)
        await self._warm("after CMD_SRAM_EXEC")

    async def _fwcrc_leg(self) -> None:
        """Step 5: the corrupted image; step 6: the warm reset after the fault."""
        p = self.plan
        high = await self._quiet_pic30(QUIET_CLKS)
        self.chk.ctrl("FWCRC-QUIET", high == 0, pic30_high=high, clks=QUIET_CLKS)
        await self._graded(True)
        seq = await self.km.send_command(KM_CMD_SRAM_LOAD_EXEC, [p.n2])
        rc, _ = await self.km.recv_resp_cmd(KM_CMD_SRAM_LOAD_EXEC, seq)
        if rc != KM_RC_SUCCESS:
            raise AssertionError(f"precondition: CMD_SRAM_LOAD_EXEC n2={p.n2} rc={rc}")
        frame, orig, flipped = p.corrupt_stream()
        if flipped == orig:
            raise AssertionError("the flipped word equals the original word")
        self.logger.info(
            "LOG fwcrc stream pos=%s bit=%d original=%s flipped=%s",
            p.flip_pos,
            p.flip_bit,
            _hx(orig),
            _hx(flipped),
        )
        watch = _RiseHold(self)
        watch.start()
        await self._post(frame)
        watch.mark_trailer()
        first = await self._read_frame(FRAME_POLLS)
        extra: list[_Frame] = []
        while not watch.done.is_set():
            await ClockCycles(cocotb.top.clk_i, 64)
            if not (await self._status() & (1 << KM_STATUS_OUTBOUND_EMPTY)):
                fr = await self._read_frame(FRAME_POLLS)
                if fr is not None:
                    extra.append(fr)
        await watch.done.wait()
        if not (await self._status() & (1 << KM_STATUS_OUTBOUND_EMPTY)):
            fr = await self._read_frame(FRAME_POLLS)
            if fr is not None:
                extra.append(fr)
        await self._graded(False)
        code = first.payload[0] if first is not None and first.payload_len == 1 else None
        ok_frame = (
            first is not None
            and first.resp_id == KM_RESP_UNRECOVERABLE_FAULT
            and code == md.FW_CRC_CODE
        )
        held = watch.rise is not None and watch.low_samples == 0 and watch.held_samples > 0
        rise_ok = watch.rise_clk is not None and watch.rise_clk > 0
        self.chk.ok(
            "FWCRC",
            ok_frame and not extra and held and rise_ok and not watch.timed_out,
            n=p.n2,
            pos=p.flip_pos,
            bit=p.flip_bit,
            code="none" if code is None else _hx(code),
            first_frame="none" if first is None else first.text(),
            err_o=int(watch.rise is not None),
            held=int(held),
            rise_clk="none" if watch.rise_clk is None else watch.rise_clk,
            hold_clk=watch.hold,
            low_in_hold=watch.low_samples,
            second_resp=len(extra),
        )

        # Step 6. A warm reset ends the fatal halt.
        await self._warm("after the fw_crc fault")
        self.chk.obs("FWCRC-RESET", control=1, pic30=self._pic30())

    async def _size_rej(self, words: int, *, zero: bool, boot: bool) -> None:
        """Steps 7 and 8: a refused FW_WORDS, then CMD_STAT as the next frame."""
        if not 0 <= words <= imgh.FW_WORDS_MAX:
            raise AssertionError(f"FW_WORDS {words} sets a reserved bit")
        if boot:
            await self._warm(f"FW_WORDS={words}")
        await self._graded(True)
        seq = await self.km.send_command(KM_CMD_SRAM_LOAD_EXEC, [words])
        fr = await self._read_frame(FRAME_POLLS)
        rc, arg = (None, None) if fr is None else fr.resp_cmd(KM_CMD_SRAM_LOAD_EXEC, seq)
        stat_seq = await self.km.send_command(KM_CMD_STAT, [])
        fr2 = await self._read_frame(FRAME_POLLS)
        src, _ = (None, None) if fr2 is None else fr2.resp_cmd(KM_CMD_STAT, stat_seq)
        stat_next = int(src == KM_RC_SUCCESS)
        await self._graded(False)
        fields = {
            "words": words,
            "arg": "none" if arg is None else arg,
            "stat_next": stat_next,
            "frame": "none" if fr is None else fr.text(),
            "stat_frame": "none" if fr2 is None else fr2.text(),
        }
        if zero:
            # The code of FW_WORDS 0 is a cell of sep_km_handover_test (control).
            ok = rc is not None and arg == 0 and stat_next == 1
            self.chk.ok("SIZE-REJ", ok, control_code=rc, **fields)
        else:
            ok = rc == KM_RC_INVALID_ARG and arg == 0 and stat_next == 1
            self.chk.ok("SIZE-REJ", ok, code=rc, **fields)

    async def _mid_size(self) -> None:
        """Step 9: the mid size, logged and not graded."""
        p = self.plan
        await self._warm(f"FW_WORDS={p.mid}")
        seq = await self.km.send_command(KM_CMD_SRAM_LOAD_EXEC, [p.mid])
        fr = await self._read_frame(FRAME_POLLS)
        rc, arg = (None, None) if fr is None else fr.resp_cmd(KM_CMD_SRAM_LOAD_EXEC, seq)
        self.chk.obs(
            "SIZE-MID",
            words=p.mid,
            code="none" if rc is None else rc,
            arg="none" if arg is None else arg,
            frame="none" if fr is None else fr.text(),
        )

    # --- state leg ---------------------------------------------------------------------
    def _staged_val0(self, fields) -> dict[str, int]:
        return {_OTP_REPORT_NAME[f]: self.plan.fuse[f][0] for f in fields}

    async def _handover_pass(self, exp: md.PassExp, *, via_load: bool, junk: list[int]) -> None:
        """Steps 12 to 14 (pass 1) or step 16 (pass 2), and the checks of the pass."""
        image = imgh.read_image()
        bus = _KeyBusWatch(self)
        await self._graded(True)
        if via_load:
            seq = await self.km.send_command(KM_CMD_SRAM_LOAD_EXEC, [len(image)])
            rc, arg = await self.km.recv_resp_cmd(KM_CMD_SRAM_LOAD_EXEC, seq)
            await self._wmap_clear()
            base = self._sram_writes()
            bus.start()
            await self._post(imgh.stream_words(image))
            if junk:
                await self._post(junk)
        else:
            # The handover begins when the ROM sends the confirmation, so the
            # baseline and the bus record start before the command.
            await self._wmap_clear()
            base = self._sram_writes()
            bus.start()
            seq = await self.km.send_command(KM_CMD_SRAM_EXEC, [])
            rc, arg = await self.km.recv_resp_cmd(KM_CMD_SRAM_EXEC, seq)
        confirm_ok = rc == KM_RC_SUCCESS
        self.logger.info(
            "LOG pass=%d confirmation code=%d arg=%s write_count_base=%d",
            exp.no,
            rc,
            _hx(arg),
            base,
        )

        first = await self._read_word(IMG_FIRST_POLLS)
        if first is None:
            raise AssertionError(
                f"CHK-HO-FIRST FAIL: pass {exp.no}: no outbound word within "
                f"{IMG_FIRST_POLLS} polls after the handover command"
            )
        sk_words = self._sk_words()
        await bus.stop()
        ok, f = md.grade_first(first, confirm_ok, exp)
        self.chk.ok("HO-FIRST", ok, **f)
        if exp.shared_before:
            ok, f = md.grade_sk_words(sk_words, exp)
            self.chk.ok("HO-SK-WORDS", ok, **f)
        self.logger.info(
            "OBS-HO-SK-WORDS LOG pass=%d seed=%d words=%s",
            exp.no,
            self.plan.seed,
            ",".join(_hx(w) for w in sk_words),
        )
        skipped: list[int] = []
        while first != imgh.MAGIC:
            if len(skipped) >= 64:
                raise AssertionError(
                    f"pass {exp.no}: no IMG-H MAGIC in the first 64 outbound words {skipped}"
                )
            skipped.append(first)
            first = await self._read_word(IMG_WORD_POLLS)
            if first is None:
                raise AssertionError(f"pass {exp.no}: the outbound words stopped before MAGIC")
        if skipped:
            self.logger.info("LOG pass=%d words before MAGIC %s", exp.no, [_hx(w) for w in skipped])
        rest, st = await self._read_words(imgh.REPORT_WORDS - 1, f"IMG-H pass {exp.no}")
        if not st & (1 << KM_STATUS_OUTBOUND_SEPARATOR):
            raise AssertionError(
                f"pass {exp.no}: the separator is not on IMG-H word {imgh.REPORT_WORDS - 1} "
                f"(SEP_STATUS=0x{st:08x})"
            )
        rep = imgh.decode_report([first] + rest)
        writes_end = self._sram_writes()
        delta = (writes_end - base) & md.WORD
        wmap_end = self._wmap_regions()
        jump_seen, jump_wr, wmap = self._wmap_jump()
        self.logger.info(
            "LOG pass=%d KM-WMAP-JUMP seen=%d r30_jump=%d r30_end=%d writes_after_jump=%d",
            exp.no,
            jump_seen,
            wmap[30],
            wmap_end[30],
            (writes_end - jump_wr) & md.WORD,
        )
        await self._graded(False)

        self.logger.info(
            "LOG pass=%d slots ctrl=%s word0=%s bus_err=%s free_slot=%s free_words=%s",
            exp.no,
            ",".join(f"{s.ctrl:x}" for s in rep.slots),
            ",".join(_hx(s.word0) for s in rep.slots if not s.lock_use),
            ",".join(f"{s.bus_err:x}" for s in rep.slots),
            rep.free_slot,
            ",".join(_hx(w) for w in rep.free_words),
        )
        self.logger.info(
            "LOG pass=%d otp secret_val0=%s public_val0=%s staged_public_val0=%s control=1",
            exp.no,
            {k: _hx(v) for k, v in rep.secret_val0.items()},
            {k: _hx(v) for k, v in rep.public_val0.items()},
            {k: _hx(v) for k, v in exp.staged_public_val0.items()},
        )
        self.logger.info(
            "LOG pass=%d key_ctrl=%s bus_writes=%d",
            exp.no,
            {k: _hx(v) for k, v in rep.key_ctrl.items()},
            bus.count,
        )
        for name, grade, args in (
            ("HO-REGS", md.grade_regs, (rep, exp)),
            ("HO-NOIRQ", md.grade_noirq, (rep, exp)),
            ("HO-ENTRY", md.grade_entry, (rep, exp)),
            ("HO-OTP", md.grade_otp, (rep, exp)),
            ("HO-KPV-LOCK", md.grade_kpv_lock, (rep, exp)),
            ("HO-SIDELOAD", md.grade_sideload, (rep, exp)),
            ("HO-SIDELOAD-BUS", md.grade_sideload_bus, (bus.writes, exp)),
            ("HO-SRAM", md.grade_sram, (rep, exp, delta, wmap, jump_seen, wmap_end)),
            ("HO-MBOX", md.grade_mbox, (rep, exp)),
        ):
            ok, f = grade(*args)
            self.chk.ok(name, ok, **f)

    async def _state_pass(self, no: int) -> None:
        """Pass 1 (steps 10 to 14) or pass 2 (steps 15 and 16)."""
        p = self.plan
        if no == 1:
            ek = await self._kem_keygen()
            keys, plan_keys = p.keys1, md.PASS1_KEYS
        else:
            await self._warm("pass 2 pre-state")
            keys, plan_keys = p.keys2, md.PASS2_KEYS
        done = await self._load_and_transfer(keys, plan_keys)
        if no == 1:
            await self._kem_encaps_pending(ek)
        shared = self._sk_valid()
        sk_before = self._sk_words()
        if no == 1:
            # Pass 1 hands over with the shared key pending.
            self.chk.ctrl(
                "HO-SHARED-PENDING",
                shared == 1 and any(sk_before),
                shared_before=shared,
                words_before_nonzero=sum(1 for w in sk_before if w),
            )
        registered = sum(md.slots_of(n) for n, _ in plan_keys)
        exp = md.PassExp(
            no=no,
            registered=registered,
            keyvalid_before=done,
            shared_before=shared,
            sk_words_before=sk_before,
            junk=md.JUNK_WORDS if no == 1 else 0,
            sram_lock=md.image_lock_mask(len(imgh.read_image())),
            staged_secret_val0=self._staged_val0(OTP_DUAL_RAIL_FIELDS[:4]),
            staged_public_val0=self._staged_val0(OTP_DUAL_RAIL_FIELDS[4:]),
        )
        self.logger.info(
            "LOG pass=%d pre-state completed=0x%02x tap_bank_valid=0x%02x shared=%d "
            "registered_slots=%d staged_secret_val0=%s",
            no,
            done,
            self._bank_valid(),
            shared,
            registered,
            {k: _hx(v) for k, v in exp.staged_secret_val0.items()},
        )
        await self._handover_pass(exp, via_load=(no == 1), junk=p.junk if no == 1 else [])

    # --- scenario -------------------------------------------------------------------------
    async def run_scenario(self) -> None:
        seed = self.random_seed()
        self.logger.info("SEED seed=%d", seed)
        self.chk = SepChkLog(self, TEST, seed)
        self.plan = md.draw_plan(
            seed, {f: SepEfuseImage.field(f).n_words for f in OTP_DUAL_RAIL_FIELDS}
        )
        for line in self.plan.draw_lines():
            self.logger.info(line)

        # Step 1: stage the fuse image (non-zero secret and public words), cold
        # bring-up with real fuse sense and entropy, release the KM.
        image = self.select_efuse_image(lc_raw=LC_PROD, fixed={"SIP_DIS": 0, "SYS_DIS": 0})
        for name, words in self.plan.fuse.items():
            image.set_words(name, list(words))
        zero = [n for n in OTP_DUAL_RAIL_FIELDS if any(w == 0 for w in self.plan.fuse[n])]
        if zero:
            raise AssertionError(f"staged OTP field(s) with a zero word: {zero}")
        self.write_efuse_image(image)
        await self.bring_up_no_cpu(park=("otbn", "aes", "hmac", "kmac"))
        self.suppress_host_axi_transaction_info()

        self.km = SepKmMailbox(self)
        self.kem = SepAbrMlkem(self)
        await self.bring_up_entropy(strict=True, score_km="observe")
        assert await self.wait_genbits(), "CSRNG CTR_DRBG never produced genbits"
        self.start_fifo_drain(log_batches=False)

        await self._wait_sep_reset_release()
        await self.swrst.release("km")
        await self.km.wait_km_ready()
        # Every handover and the fatal handler write all eight banks, so every
        # engine is out of reset before the first load.
        await self.swrst.release("aes", "hmac", "kmac", "otbn")
        await SepAes(self).wait_idle("post-release")
        await SepHmac(self).wait_idle("post-release")
        await SepKmac(self).wait_idle("post-release")
        await SepOtbn(self).wait_idle("post-release")

        self.logger.info(
            "FW-PROVENANCE img_h=cocotb/tests/%s sha256=%s words=%d",
            imgh.IMAGE_PATH.name,
            hashlib.sha256(imgh.IMAGE_PATH.read_bytes()).hexdigest(),
            len(imgh.read_image()),
        )
        await self._good_load()  # steps 2 and 3
        await self._fwcrc_leg()  # steps 5 and 6
        # Step 7: the warm boot of step 6 serves the first oversize value.
        oversize = (*md.OVERSIZE_FIXED, self.plan.oversize)
        for i, w in enumerate(oversize):
            await self._size_rej(w, zero=False, boot=i > 0)
        await self._size_rej(0, zero=True, boot=True)  # step 8
        await self._mid_size()  # step 9
        await self._warm("pass 1 pre-state")
        await self._state_pass(1)  # steps 10 to 14
        await self._state_pass(2)  # steps 15 and 16

        # Step 18: leave the leaf with km_sw_rst_n high.
        await self._warm("end of leaf")
        await self.stop_fifo_drain()
        self.chk.finish()
