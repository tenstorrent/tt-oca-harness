# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""No key material stays in DCCM after an exit from the payload decryption stage.

rom.adoc, Payload Decryption:

    [SEP-ROM-PL-080] All key material (class key, derived key, KDF inputs) shall be zeroized
    (`explicit_memzero`) on every exit path from the decryption stage, success or failure. The
    `CLASS_KEY` shadow register is read-locked before hand-off (<<sec:handoff>>).

rom.adoc, Payload Decryption and the security inventory, which name the steps of the stage and
the ways it fails:

    * *Key derivation:* the AES-256 key (32 bytes) is derived from the `CLASS_KEY` fuse secret
      (`0x10930064`, 32 bytes) and the manifest's `encryption_kdf_input`.
    [SEP-ROM-PL-070] Decryption shall require a non-zero programmed `CLASS_KEY`; an all-zero
    (unprogrammed) class key shall fail the decryption stage.
    * *Padding:* PKCS#7, removed after decryption; a malformed pad is a decryption failure.
    |Payload decryption |CLASS_KEY (non-zero), KDF input, IV |KDF + AES-256-CBC + PKCS#7 OK;
    keys zeroized |`OCA_FAIL_DECRYPT` |Only after ciphertext hash. PL-030/-070/-080

The exits are success and a failure of the class-key check, the key derivation, the AES-256-CBC
cipher or the pad. Each testlist entry takes one exit, chosen by +sep_rom_decrypt_exit:

* success: no fault.
* kdf_fail: the HMAC message FIFO (the PRF of the KDF) stops draining from the stage entry to its
  return.
* aes_init_fail: the entropy complex (ESRC, CSRNG, EDN) is held in reset from the stage entry, and
  a short AES reset pulse follows, so the AES must reseed its masking PRNG from an EDN that never
  answers before it reports idle; the cipher never starts.
* aes_dec_fail: the entropy complex is held in reset from the stage entry; the AES is idle then,
  and stalls at the key load, which reseeds its PRNG.

All faults are released when the stage returns. The backup slot carries a broken magic.

The stage boundary is an observation choice based on the implementation: from the first retirement
at the ROM decrypt callback (`plat_decrypt_payload`, ELF symbol) to the first retirement at the
call site + 4 after a 32-bit `ret` inside that function. DCCM content is rebuilt from the PR-TCM
write beats recorded from before the first retirement; every DCCM read of the run hits a word
written earlier in the run. The key material is the test class key (the eFuse CLASS_KEY), the
AES-256 key derived from it and the primary's `encryption_kdf_input`, and that 64-byte KDF input
(PL-080 lists "KDF inputs"). The derived key
comes from a model of the implementation's KDF (`sep_payload_mutate.oca_aes256_key`, mirroring
`kdf.c`): the spec marks the KDF PROVISIONAL, and its two descriptions of the KDF input disagree
("Full 64-byte field is the KDF context" in the manifest table, `info = encryption_kdf_input[0:16]`,
`salt = encryption_kdf_input[16:32]` in the KDF note). A residue is any 16-byte window of one of
them (every byte offset of the material), in byte order or with each 32-bit word reversed, at any
byte offset of DCCM. The check is that the material is not found, not that its bytes were written
to zero. The primary is re-encrypted under an IV that shares no 16-byte window with the key
material.

* CHK-NO-KEY-RESIDUE: when the stage returns, DCCM holds no residue. The snapshot holds the writes
  of every store retired before the first retirement after the return and no write of a later
  store.
* CHK-NO-KEY-RESIDUE-AT-END: at the hand-off mret (success) or at the FAIL verdict (failures), DCCM
  holds no residue.
* CTRL-EXIT-TAKEN: the intended exit, by the status words DECRYPTION_START and DECRYPTION_END or
  DECRYPTION_FAILED (registry names; when and at which severity the ROM emits them is ROM
  behaviour) and by the ROM console marker of the failure kind.
* CTRL-FAULT-APPLIED: the fault was in force over the stage (the gated reset probes, the WARN
  HMAC_FIFO_TIMEOUT word, the ROM's AES idle-timeout line), or no fault pin moved (success).
* CTRL-KEY-WAS-PRESENT: during the stage, a snapshot searched with the grading search shows each
  material that must exist before that exit: all three (success, aes_dec_fail), the class key and
  KDF input (kdf_fail), the class key (aes_init_fail). It shows that the rebuilt DCCM and the
  grading search find each listed material while the stage runs, and in which byte order.
* CTRL-DECRYPT-CALL, CTRL-DCCM-GEOMETRY, CTRL-DCCM-COMPLETE, CTRL-STORE-LAG, CTRL-SNAPSHOT-CUT,
  CTRL-EFUSE, CTRL-STIMULUS, CTRL-PUBLIC-DISJOINT: the stage boundaries, the reconstruction, the
  snapshot cut, the stimulus and the separation of the searched windows from public manifest
  bytes.

Partial coverage. Not graded: the all-zero class key exit (an all-zero key leaves no searchable
residue), the malformed-pad exit, copies outside DCCM (AES and HMAC key registers, SRAM, CPU
registers), a copy of fewer than 16 contiguous bytes of a material, and the CLASS_KEY read lock.
"""

from __future__ import annotations

import os
from bisect import bisect_left
from pathlib import Path

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from cocotb.utils import get_sim_time
from env import sep_aes_golden as aes
from env import sep_manifest_mutate as mm
from env import sep_payload_mutate as pm
from env.sep_chk_log import SepChkLog
from env.sep_efuse_image import LC_TEST_DEV
from env.sep_esrc_noise import esrc_noise_task
from env.sep_fabric_tap import SepFabricTap
from env.sep_rom_observer import STORE_LAG_MAX_CYCLES, SepRomObserver, load_rom_syms
from env.sep_rv32_trace_decode import INSN_MRET, funct3, is_store, opcode, rd_of
from env.sep_tcm_flip import DATA_BITS, DCCM_BASE, DCCM_BYTES
from ocah_spi_vip import OcahSpiFlash
from rom_fw.sep_rom_observe_base import ROM_BASE, RUN_PULSE_CYCLES, sep_rom_observe_base

_SEP_ROOT = Path(__file__).resolve().parents[4]
_IMAGE = _SEP_ROOT / "bootrom" / "prod" / "build" / "oca_encrypted_boot.bin"
_EFUSE_PRELOAD = (
    Path(__file__).resolve().parents[3]
    / "tb"
    / "efuse_preloads"
    / "efuse_configurations"
    / "sep_efuse_class_key.toml"
)

_EXITS = ("success", "aes_init_fail", "kdf_fail", "aes_dec_fail")
_MARKERS = {
    "success": "DECRYPT_OK",
    "aes_init_fail": "AES_INIT_BUSY",
    "kdf_fail": "KDF_FAIL",
    "aes_dec_fail": "AES_DEC_FAIL",
}
_AES_TIMEOUT_LINE = "AES_IDLE_TIMEOUT="
_DECRYPT_FN = "plat_decrypt_payload"

_BL0 = 1 << 16
_WARN = 0x08
_MSG_DECRYPTION_START = 0x0040
_MSG_DECRYPTION_END = 0x0042
_MSG_DECRYPTION_FAILED = 0x001A
_MSG_HMAC_FIFO_TIMEOUT = 0x022A
_VERDICT_FAIL = 0xDEADBEEF

_TRNG_HOLD = "jtag_trng_rst_hold_i"
_AES_HOLD = "jtag_aes_rst_hold_i"
_HMAC_STALL = "hmac_fifo_drain_stall_i"
_TRNG_RST = "trng_gated_rst_n_probe_o"
_AES_RST = "aes_gated_rst_n_probe_o"
_PINS = (_TRNG_HOLD, _AES_HOLD, _HMAC_STALL)
# Clocks of the AES reset pulse; the override crosses a 2-flop synchronizer each way.
_AES_PULSE_CYCLES = 8
# Stimulus polling step in clocks.
_STIM_STEP = 16
_PROGRESS_STEP = 2_000_000

# PR-TCM DCCM geometry: 2 banks, bank = byte offset bit 2, row = byte offset bits 16:3.
_BANKS = 2
_AW = 14
_SEG = 16
# IV for the re-encrypted primary; shares no 16-byte window with the key material.
_IV = bytes.fromhex("f0e1d2c3b4a5968778695a4b3c2d1e0f")
_ORDER_NAMES = ("byte_order", "word_reversed")
_MIN_PROBES = 16
_INSN_RET = 0x0000_8067
_OP_JAL = 0x6F
_OP_JALR = 0x67
_RA = 1

# Materials that must exist in DCCM during the stage before each exit.
_MUST_EXIST = {
    "success": ("class_key", "derived_key", "kdf_input"),
    "kdf_fail": ("class_key", "kdf_input"),
    "aes_init_fail": ("class_key",),
    "aes_dec_fail": ("class_key", "derived_key", "kdf_input"),
}

_RUN_CYCLES = {"success": 8_000_000, "kdf_fail": 8_000_000}
_RUN_CYCLES_AES = 48_000_000
# Clocks without a retirement inside the stage that mean the CPU waits on a bus read for ever.
_STALL_CYCLES = 100_000


def _hex(v: int | None) -> str:
    return "none" if v is None else f"0x{v:08x}"


def _ps(t: int | None) -> int:
    return -1 if t is None else int(t)


def _word_swap(b: bytes) -> bytes:
    return b"".join(b[i : i + 4][::-1] for i in range(0, len(b), 4))


def _orders(b: bytes) -> tuple[bytes, bytes]:
    return b, _word_swap(b)


def _code_words(status: list[tuple[int, int]], code: int) -> list[tuple[int, int]]:
    return [(t, w) for t, w in status if w & 0x00FF_FFFF == _BL0 | code]


def _off(slot: tuple[int, int]) -> int:
    bank, row = slot
    return (row << 3) | (bank << 2)


def _slot(addr: int) -> tuple[int, int]:
    off = addr - DCCM_BASE
    return (off >> 2) & (_BANKS - 1), off >> 3


def _in_dccm(addr: int | None) -> bool:
    return addr is None or DCCM_BASE <= addr < DCCM_BASE + DCCM_BYTES


class _Observer(SepRomObserver):
    """Also pairs each entry of the decrypt callback with its call site and its return."""

    def __init__(self, test, entry: int, fn_end: int, watch: tuple[str, ...]) -> None:
        super().__init__(test, keep=is_store, watch=watch, pc_watch=frozenset({entry}))
        self._entry = entry
        self._fn_end = fn_end
        self._prev: tuple[int, int] | None = None
        self.calls: list[dict] = []
        self.last_retire_cycle = 0

    def record(self, t: int, pc: int, insn: int, exc: bool, ecause: int, interrupt: bool):
        prev, self._prev = self._prev, (pc, insn)
        live = self.calls[-1] if self.calls and self.calls[-1]["ret_t"] is None else None
        if pc == self._entry and live is None:
            self.calls.append(
                {
                    "entry_t": t,
                    "call_pc": None if prev is None else prev[0],
                    "call_insn": None if prev is None else prev[1],
                    "ret_t": None,
                    "ret_insn": None,
                }
            )
        elif (
            live is not None
            and prev is not None
            and live["call_pc"] is not None
            and pc == live["call_pc"] + 4
            and self._entry <= prev[0] < self._fn_end
        ):
            live["ret_t"] = t
            live["ret_insn"] = prev[1]
        self.last_retire_cycle = self.cycle
        return super().record(t, pc, insn, exc, ecause, interrupt)


class _Dccm:
    """DCCM content rebuilt from PR-TCM write beats, in time order."""

    def __init__(self, tcm: SepFabricTap, end_t: int) -> None:
        self.writes: list[tuple[int, int, int]] = []
        self.by_slot: dict[tuple[int, int], tuple[list[int], list[int]]] = {}
        self.written: set[tuple[int, int]] = set()
        self.reads = self.unwritten_reads = self.unknown = 0
        for b in tcm.beats:
            if b.ch != "dccm" or b.t_ps > end_t:
                continue
            for bank in range(_BANKS):
                en = b.lane("clken", bank, 1)
                if not en:
                    self.unknown += en is None
                    continue
                we = b.lane("wren", bank, 1)
                row = b.lane("addr", bank, _AW)
                data = b.lane("wdata", bank, DATA_BITS) if we else 0
                if we is None or row is None or data is None:
                    self.unknown += 1
                    continue
                slot = (bank, row)
                if we:
                    self.writes.append((int(b.t_ps), _off(slot), data))
                    self.written.add(slot)
                    times, datas = self.by_slot.setdefault(slot, ([], []))
                    times.append(int(b.t_ps))
                    datas.append(data)
                else:
                    self.reads += 1
                    self.unwritten_reads += slot not in self.written

    def write_of(self, addr: int, t_ps: int, data: int | None) -> int | None:
        """Time of the first write to addr's word at or after t_ps, matching data when given."""
        times, datas = self.by_slot.get(_slot(addr), ((), ()))
        for i in range(bisect_left(times, t_ps), len(times)):
            if data is None or datas[i] == data:
                return times[i]
        return None

    def image(self, cut: int, inclusive: bool) -> bytearray:
        img = bytearray(DCCM_BYTES)
        for t, off, data in self.writes:
            if t > cut or (t == cut and not inclusive):
                break
            img[off : off + 4] = data.to_bytes(4, "little")
        return img


@pyuvm.test()
class sep_rom_decrypt_exit_zeroize_test(sep_rom_observe_base):
    """Encrypted SPI boot, one decryption exit per entry; DCCM holds no key material after it."""

    required_evidence = ("CHK-NO-KEY-RESIDUE", "CHK-NO-KEY-RESIDUE-AT-END")

    # --- stimulus ------------------------------------------------------------
    def build_efuse_image(self):
        assert os.path.isfile(_EFUSE_PRELOAD), (
            f"eFuse preload missing: {_EFUSE_PRELOAD}; restore it from git, it is the TEST_DEV "
            f"image that carries the test CLASS_KEY"
        )
        image = self.select_efuse_image(default_preload=_EFUSE_PRELOAD)
        key = image.field_int("CLASS_KEY").to_bytes(pm.OCA_AES_KEY_BYTES, "little")
        self.chk.ctrl(
            "EFUSE",
            image.lc_raw() == LC_TEST_DEV and key == pm.OCA_TEST_CLASS_KEY,
            lc_raw=f"0x{image.lc_raw():x}",
            class_key=key.hex(),
        )
        return image

    def _flash_image(self) -> bytes:
        buf = bytearray(_IMAGE.read_bytes())
        pm.verify_sealed(buf, "primary")
        kdf_input = pm.manifest_kdf_input(buf, "primary")
        key = pm.oca_aes256_key(pm.OCA_TEST_CLASS_KEY, kdf_input)
        self.material = {
            "class_key": pm.OCA_TEST_CLASS_KEY,
            "derived_key": key,
            "kdf_input": kdf_input,
        }
        packed_iv = pm.golden_iv(buf, "primary")
        decrypts, padded = pm.rom_view_decrypt(buf, "primary")
        assert decrypts, f"{_IMAGE} primary does not decrypt under the test CLASS_KEY; rebuild it"
        pm.set_encryption_iv(buf, "primary", _IV)
        p, n = pm.payload_base(buf, "primary"), pm.manifest_payload_length(buf, "primary")
        buf[p : p + n] = aes.aes_cbc_encrypt(key, _IV, padded)
        pm.reseal(buf, "primary", check_toc=False)
        pm.verify_sealed(buf, "primary")
        self.iv = pm.golden_iv(buf, "primary")
        enc_type = pm.encryption_type(buf, "primary")
        manifest = bytes(
            buf[mm.slot_base("primary") : mm.slot_base("primary") + mm.SIGNED_REGION_END]
        )
        mm.break_magic(buf, "backup")
        backup_magic = bytes(buf[mm.BACKUP_MANIFEST_OFFSET : mm.BACKUP_MANIFEST_OFFSET + 4])
        self.chk.ctrl(
            "STIMULUS",
            pm.is_encrypted(buf, "primary")
            and enc_type == mm.K.OcaEncryptionType.AES_256_CBC.value
            and self.iv == _IV
            and backup_magic != mm.MANIFEST_MAGIC,
            exit=self.exit_kind,
            encryption_type=enc_type,
            kdf_input=kdf_input.hex(),
            derived_key=key.hex(),
            packed_iv=packed_iv.hex(),
            iv=self.iv.hex(),
            backup_magic=backup_magic.hex(),
        )
        self._public_disjoint(manifest)
        return bytes(buf)

    def _public_disjoint(self, manifest: bytes) -> None:
        """No searched window equals a window of the IV, and no class-key or derived-key window
        equals a window of the signed primary manifest."""
        iv_win = {self.iv[i : i + _SEG] for i in range(len(self.iv) - _SEG + 1)}
        man_win = {manifest[i : i + _SEG] for i in range(len(manifest) - _SEG + 1)}
        segs = self._segments()
        iv_hits = sum(seg in iv_win for v in segs.values() for seg in v)
        man_hits = sum(seg in man_win for n in ("class_key", "derived_key") for seg in segs[n])
        self.chk.ctrl(
            "PUBLIC-DISJOINT",
            iv_hits == 0 and man_hits == 0,
            searched=sum(len(v) for v in segs.values()),
            iv_window_hits=iv_hits,
            secret_manifest_window_hits=man_hits,
            manifest_bytes=len(manifest),
        )

    async def stimulus(self, obs: _Observer) -> None:
        dut = cocotb.top
        while not obs.calls:
            await ClockCycles(dut.clk_i, _STIM_STEP)
        if self.exit_kind == "success":
            return
        call = obs.calls[0]
        if self.exit_kind == "kdf_fail":
            self._set_pin(dut, _HMAC_STALL, 1)
        else:
            self._set_pin(dut, _TRNG_HOLD, 1)
        if self.exit_kind == "aes_init_fail":
            await ClockCycles(dut.clk_i, _AES_PULSE_CYCLES)
            self._set_pin(dut, _AES_HOLD, 1)
            await ClockCycles(dut.clk_i, _AES_PULSE_CYCLES)
            self._set_pin(dut, _AES_HOLD, 0)
        next_log = obs.cycle + _PROGRESS_STEP
        while call["ret_t"] is None:
            await ClockCycles(dut.clk_i, _STIM_STEP)
            if obs.cycle >= next_log:
                next_log += _PROGRESS_STEP
                self.logger.info(
                    "decrypt stage still open: cycle=%d retired=%d", obs.cycle, obs.retired
                )
        for pin in _PINS:
            self._set_pin(dut, pin, 0)
        self.released_ps = int(get_sim_time("ps"))

    # --- run -----------------------------------------------------------------
    async def run_scenario(self) -> None:
        self.exit_kind = cocotb.plusargs.get("sep_rom_decrypt_exit", "")
        assert self.exit_kind in _EXITS, (
            f"+sep_rom_decrypt_exit={self.exit_kind!r} is not one of {_EXITS}; set it in the testlist entry"
        )
        self.max_run_cycles = _RUN_CYCLES.get(self.exit_kind, _RUN_CYCLES_AES)
        self.released_ps: int | None = None
        self.stalled = False
        self.chk = SepChkLog(self, self.get_type_name(), self.random_seed())
        syms = load_rom_syms()
        entry = syms[_DECRYPT_FN]
        self.fn = (entry, min(a for a in syms.values() if a > entry))
        dut = cocotb.top
        cocotb.start_soon(esrc_noise_task(dut, logger=self.logger))
        self.write_efuse_image(self.build_efuse_image())
        flash = OcahSpiFlash(
            dut.spi_cs_n_o,
            dut.spi_sck_o,
            mosi=dut.spi_mosi_o,
            miso=dut.spi_miso_i,
            name="sep_rom_boot_flash",
        )
        flash.preload(self._flash_image())
        await flash.start()
        self.tap_start_ps = int(get_sim_time("ps"))
        self.tcm = SepFabricTap("PR-TCM").start()
        self.obs = _Observer(self, entry, self.fn[1], (_TRNG_RST, _AES_RST) + _PINS).start()
        stim = cocotb.start_soon(self.stimulus(self.obs))
        try:
            await self.bring_up_cpu_boot(ROM_BASE >> 1, run_pulse_cycles=RUN_PULSE_CYCLES)
            reached = await self.obs.run_until(self.done, self.max_run_cycles)
        finally:
            stim.cancel()
            await ClockCycles(dut.clk_i, 2 * STORE_LAG_MAX_CYCLES)
            await self.obs.stop()
            self.tap_stop_ps = int(get_sim_time("ps"))
            await self.tcm.stop()
            await flash.stop()
        self.chk.ctrl("RUN-REACHED", reached, cycles=self.obs.cycle, retired=self.obs.retired)
        self.chk.ctrl(
            "CPU-LIVE",
            not self.stalled,
            cycle=self.obs.cycle,
            last_retire_cycle=self.obs.last_retire_cycle,
            stall_bound=_STALL_CYCLES,
        )
        self.grade(self.obs, self.chk)
        self.chk.finish()

    # --- grading -------------------------------------------------------------
    def _segments(self) -> dict[str, list[bytes]]:
        """Every 16-byte window of each material, in both word orders."""
        return {
            name: sorted(
                {o[i : i + _SEG] for o in _orders(data) for i in range(len(data) - _SEG + 1)}
            )
            for name, data in self.material.items()
        }

    def _residue(self, img: bytearray) -> list[str]:
        hits = []
        for name, segs in self._segments().items():
            for seg in segs:
                at = img.find(seg)
                if at >= 0:
                    hits.append(f"{name}:{seg[:4].hex()}..@{_hex(DCCM_BASE + at)}")
        return hits

    def _first_whole(self, dccm: _Dccm, lo: int, hi: int) -> dict[str, tuple[int, str] | None]:
        """First write between lo and hi after which each whole material is in DCCM, with the
        byte order it was found in."""
        full = {n: _orders(d) for n, d in self.material.items()}
        first: dict[str, tuple[int, str] | None] = dict.fromkeys(full)
        img = bytearray(DCCM_BYTES)
        for t, off, data in dccm.writes:
            img[off : off + 4] = data.to_bytes(4, "little")
            if not lo <= t <= hi:
                continue
            win = img[max(0, off - 68) : off + 72]
            for name, pats in full.items():
                if first[name] is None:
                    hit = next((o for o, pat in zip(_ORDER_NAMES, pats) if pat in win), None)
                    if hit is not None:
                        first[name] = (t, hit)
        return first

    def _lag(self, obs: _Observer, dccm: _Dccm, clk_ps: int) -> tuple[int | None, int | None, int]:
        """Store-retirement to DCCM-write lag over word stores of known nonzero data."""
        win = STORE_LAG_MAX_CYCLES * clk_ps
        stores = [r for r in obs.retires if not (r.exc or r.interrupt)]
        by_word: dict[int, list[int]] = {}
        for r in stores:
            if r.mem_addr is not None:
                by_word.setdefault(r.mem_addr & ~3, []).append(r.t_ps)
        lags = []
        for r in stores:
            if not (
                funct3(r.insn) == 2
                and r.mem_data
                and r.mem_addr is not None
                and r.mem_addr % 4 == 0
                and DCCM_BASE <= r.mem_addr < DCCM_BASE + DCCM_BYTES
            ):
                continue
            # Another store to the same word inside the window could take this write.
            if any(t != r.t_ps and abs(t - r.t_ps) <= win for t in by_word[r.mem_addr]):
                continue
            w = dccm.write_of(r.mem_addr, r.t_ps - win, r.mem_data)
            if w is not None and abs(w - r.t_ps) <= win:
                lags.append(w - r.t_ps)
        return (min(lags), max(lags), len(lags)) if lags else (None, None, 0)

    def _cut(self, obs, dccm: _Dccm, t_b: int, lag_lo: int, clk_ps: int) -> dict:
        """Snapshot bound at boundary t_b: before the write of the first store retired at t_b
        or later, after the write of every store retired before t_b."""
        win = STORE_LAG_MAX_CYCLES * clk_ps
        stores = [
            r
            for r in obs.retires
            if t_b - win < r.t_ps < t_b + win
            and not (r.exc or r.interrupt)
            and _in_dccm(r.mem_addr)
        ]
        pre = [r for r in stores if r.t_ps < t_b]
        post = [r for r in stores if r.t_ps >= t_b]
        unknown = [r for r in stores if r.mem_addr is None]

        def write_t(r) -> int | None:
            data = r.mem_data if funct3(r.insn) == 2 else None
            return dccm.write_of(r.mem_addr, r.t_ps + lag_lo, data)

        pre_w = [write_t(r) for r in pre if r.mem_addr is not None]
        post_w = [write_t(r) for r in post if r.mem_addr is not None]
        t_pre = max((w for w in pre_w if w is not None), default=t_b)
        t_post = post_w[0] if post_w else None
        ok = (
            not unknown
            and None not in pre_w
            and (not post or (t_post is not None and None not in post_w))
            and (t_post is None or (t_pre < t_post and min(post_w) >= t_post))
        )
        cut = t_post if t_post is not None else t_b + win
        return {
            "ok": ok,
            "reason": "unresolved store address" if unknown else ("none" if ok else "store order"),
            "cut": cut,
            "inclusive": t_post is None,
            "pre_stores": len(pre),
            "post_stores": len(post),
            "unknown_addr": len(unknown),
            "last_pre_write_ps": t_pre,
            "first_post_write_ps": _ps(t_post),
        }

    def done(self, obs: _Observer) -> bool:
        in_stage = bool(obs.calls) and obs.calls[-1]["ret_t"] is None
        if in_stage and obs.cycle - obs.last_retire_cycle > _STALL_CYCLES:
            self.stalled = True
            return True
        return super().done(obs)

    def grade(self, obs: _Observer, chk: SepChkLog) -> None:
        clk_ps = int(round(self.cfg.sys_clk_period_ns * 1000))
        status = obs.status
        verdict_t, verdict_w = obs.verdict[-1] if obs.verdict else (None, None)
        mret = obs.pre_mret[-1] if obs.pre_mret else None
        handoff = mret is not None and mret.insn == INSN_MRET and obs.post_mret is not None
        end_t = obs.post_mret.t_ps if self.exit_kind == "success" and handoff else verdict_t
        end_ok = (
            (handoff and obs.verdict_pass() is True)
            if self.exit_kind == "success"
            else (verdict_w == _VERDICT_FAIL and not handoff)
        )

        calls = obs.calls
        call_ok = bool(calls) and all(
            c["ret_t"] is not None
            and c["ret_insn"] == _INSN_RET
            and c["call_insn"] is not None
            and opcode(c["call_insn"]) in (_OP_JAL, _OP_JALR)
            and rd_of(c["call_insn"]) == _RA
            for c in calls
        )
        chk.ctrl(
            "DECRYPT-CALL",
            call_ok and len(calls) == 1 and end_ok and end_t is not None,
            fn=f"{_DECRYPT_FN}[{_hex(self.fn[0])},{_hex(self.fn[1])})",
            calls=[f"{_hex(c['call_pc'])}:{_ps(c['entry_t'])}..{_ps(c['ret_t'])}" for c in calls],
            end=("handoff" if self.exit_kind == "success" else "fail_verdict"),
            end_ps=_ps(end_t),
            verdict=_hex(verdict_w),
        )
        call = calls[0] if calls else {"entry_t": None, "ret_t": None}
        t_in, t_out = call["entry_t"], call["ret_t"]
        lag_ps = STORE_LAG_MAX_CYCLES * clk_ps

        def within(t: int) -> bool:
            return None not in (t_in, t_out) and t_in <= t <= t_out + lag_ps

        starts = [t for t, _ in _code_words(status, _MSG_DECRYPTION_START) if within(t)]
        ends = [t for t, _ in _code_words(status, _MSG_DECRYPTION_END) if within(t)]
        failed = [
            (t, w)
            for t, w in _code_words(status, _MSG_DECRYPTION_FAILED)
            if t_out is not None and t >= t_out
        ]
        lines = [(t, line) for t, line in obs.console if within(t)]
        marks = {k: any(m in line for _, line in lines) for k, m in _MARKERS.items()}
        if self.exit_kind == "success":
            exit_ok = bool(ends) and not failed
        else:
            exit_ok = (
                not ends and bool(failed) and failed[0][1] >> 24 == _WARN and failed[0][0] < end_t
            )
        exit_ok = exit_ok and bool(starts) and marks[self.exit_kind] and sum(marks.values()) == 1
        chk.ctrl(
            "EXIT-TAKEN",
            exit_ok,
            exit=self.exit_kind,
            decryption_start=len(starts),
            decryption_end=len(ends),
            decryption_failed=[f"{_hex(w)}@{t}" for t, w in failed[:2]] or "none",
            markers=[k for k, v in marks.items() if v] or "none",
        )
        self._grade_fault(obs, t_in, t_out, lines, clk_ps)

        dccm = _Dccm(self.tcm, self.tap_stop_ps)
        sample = next((b for b in self.tcm.beats if b.ch == "dccm" and b.raw), None)
        geometry = (
            sample is not None
            and len(sample.raw["clken"]) == _BANKS
            and len(sample.raw["addr"]) == _BANKS * _AW
            and len(sample.raw["wdata"]) == _BANKS * DATA_BITS
            and DCCM_BYTES == _BANKS * (1 << _AW) * 4
        )
        chk.ctrl(
            "DCCM-GEOMETRY",
            geometry,
            banks=_BANKS,
            row_bits=_AW,
            dccm_bytes=DCCM_BYTES,
            clken_bits=len(sample.raw["clken"]) if sample else -1,
            addr_bits=len(sample.raw["addr"]) if sample else -1,
            wdata_bits=len(sample.raw["wdata"]) if sample else -1,
        )
        first_t = obs.first[0].t_ps if obs.first else None
        complete = (
            first_t is not None
            and self.tap_start_ps <= first_t
            and end_t is not None
            and self.tap_stop_ps >= end_t + lag_ps
            and bool(dccm.writes)
            and dccm.reads > 0
            and dccm.unknown == 0
            and dccm.unwritten_reads == 0
        )
        chk.ctrl(
            "DCCM-COMPLETE",
            complete,
            tap_ps=f"{self.tap_start_ps}..{self.tap_stop_ps}",
            first_retire_ps=_ps(first_t),
            writes=len(dccm.writes),
            reads=dccm.reads,
            unwritten_reads=dccm.unwritten_reads,
            unknown=dccm.unknown,
        )
        lag_lo, lag_hi, probes = self._lag(obs, dccm, clk_ps)
        lag_ok = probes >= _MIN_PROBES and lag_lo is not None and 0 <= lag_lo <= lag_hi < lag_ps
        chk.ctrl(
            "STORE-LAG",
            lag_ok,
            probes=probes,
            lag_lo_ps=_ps(lag_lo),
            lag_hi_ps=_ps(lag_hi),
            bound_ps=lag_ps,
        )

        first = self._first_whole(dccm, t_in, t_out) if None not in (t_in, t_out) else {}
        found = {}
        for name in _MUST_EXIST[self.exit_kind]:
            hit = first.get(name)
            hits = [] if hit is None else self._residue(dccm.image(hit[0], True))
            found[name] = (hit, any(h.startswith(f"{name}:") for h in hits))
        chk.ctrl(
            "KEY-WAS-PRESENT",
            bool(found) and all(ok for _, ok in found.values()),
            stage_ps=f"{_ps(t_in)}..{_ps(t_out)}",
            required=list(_MUST_EXIST[self.exit_kind]),
            **{f"{n}_snapshot_ps": _ps(h and h[0]) for n, (h, _) in found.items()},
            **{f"{n}_order": h[1] if h else "none" for n, (h, _) in found.items()},
            **{f"{n}_found": int(ok) for n, (_, ok) in found.items()},
            **{f"{n}_whole_seen": int(h is not None) for n, h in first.items()},
        )

        live = complete and lag_ok and call_ok and geometry
        for chk_name, t_b in (("NO-KEY-RESIDUE", t_out), ("NO-KEY-RESIDUE-AT-END", end_t)):
            if t_b is None or not live:
                chk.ok(chk_name, False, boundary_ps=_ps(t_b), reason="record not usable")
                continue
            cut = self._cut(obs, dccm, t_b, lag_lo, clk_ps)
            chk.ctrl("SNAPSHOT-CUT", cut["ok"], at=chk_name, boundary_ps=t_b, **cut)
            hits = self._residue(dccm.image(cut["cut"], cut["inclusive"]))
            chk.ok(
                chk_name,
                cut["ok"] and not hits,
                exit=self.exit_kind,
                boundary_ps=t_b,
                snapshot_ps=cut["cut"],
                residue=hits[:8] or "none",
                residue_count=len(hits),
            )

    def _grade_fault(self, obs: _Observer, t_in, t_out, lines, clk_ps: int) -> None:
        """The fault held over the stage, or no fault pin moved."""
        w = obs.watched

        def level(name: str, t: int) -> int | None:
            v = None
            for tw, val in w[name]:
                if tw > t:
                    break
                v = val
            return v

        def changes(name: str, lo: int, hi: int) -> list[tuple[int, int]]:
            return [(t, v) for t, v in w[name] if lo < t <= hi]

        moved = {p: [v for _, v in w[p] if v] for p in _PINS}
        aes_line = next((line for _, line in lines if _AES_TIMEOUT_LINE in line), None)
        aes_status = None
        if aes_line is not None:
            tail = aes_line.split(_AES_TIMEOUT_LINE, 1)[1].split()
            try:
                aes_status = int(tail[0], 16) if tail else None
            except ValueError:
                aes_status = None
        fields = {
            "released_ps": _ps(self.released_ps),
            "aes_idle_timeout_status": _hex(aes_status),
            **{f"{p}_high": len(v) for p, v in moved.items()},
        }
        if None in (t_in, t_out):
            self.chk.ctrl("FAULT-APPLIED", False, stage="no stage record", **fields)
            return
        mid = (t_in + t_out) // 2
        trng_low = level(_TRNG_RST, mid) == 0 and level(_TRNG_RST, t_out) == 0
        aes_moves = changes(_AES_RST, t_in, t_out)
        hmac_timeout = [
            t
            for t, wd in _code_words(obs.status, _MSG_HMAC_FIFO_TIMEOUT)
            if t_in <= t <= t_out + STORE_LAG_MAX_CYCLES * clk_ps and wd >> 24 == _WARN
        ]
        if self.exit_kind == "success":
            ok = not any(moved.values())
        elif self.exit_kind == "kdf_fail":
            ok = (
                level(_HMAC_STALL, t_out) == 1
                and bool(hmac_timeout)
                and not moved[_TRNG_HOLD]
                and not moved[_AES_HOLD]
            )
        elif self.exit_kind == "aes_init_fail":
            ok = (
                trng_low
                and [v for _, v in aes_moves] == [0, 1]
                and aes_line is not None
                and not moved[_HMAC_STALL]
            )
        else:
            ok = trng_low and not aes_moves and aes_line is not None and not moved[_HMAC_STALL]
        fields.update(
            trng_rst_mid=level(_TRNG_RST, mid),
            trng_rst_at_return=level(_TRNG_RST, t_out),
            aes_rst_changes=[f"{v}@{t}" for t, v in aes_moves] or "none",
            hmac_fifo_timeout_words=len(hmac_timeout),
        )
        self.chk.ctrl("FAULT-APPLIED", ok, exit=self.exit_kind, **fields)
