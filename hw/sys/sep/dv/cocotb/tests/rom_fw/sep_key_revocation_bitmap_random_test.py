# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""TP074: constrained-random ``CHIPLET_PUBK_REVOKE`` bitmap x selected ROM key.

One row, one seed, one of four outcome classes. The seed derives a bitmap and the
two manifests' ROM key slots through the shared draw in
``env/sep_key_revocation_draw.py``; the class the stimulus lands in decides what
the ROM must do:

  * ``clean_proceed`` / ``noisy_proceed`` -- the primary boots. The noisy variant
    sets bits that are NOT the primary's, which is the arm an implementation that
    refused on ``revoke != 0`` would fail;
  * ``primary_failover`` -- the primary's slot is revoked, the backup's is not,
    and the backup boots;
  * ``both_revoked_terminal`` -- both slots are revoked, both are refused, and
    the retry loop exhausts. This is the class nothing else in this repository
    covers: it is the only evidence that the revocation check is applied on the
    BACKUP path too, rather than on the primary alone.

WHY THIS TESTCASE OWNS ITS SCENARIO INSTEAD OF EXTENDING A BASE. The three
outcome shapes have three different bases here -- ``sep_rom_ot_dma_boot_test``,
``sep_primary_fail_backup_boot_base`` and ``sep_backup_manifest_fail_base`` -- and
which one applies is not known until the seed is drawn, so no base can be chosen
at class-definition time. Picking one and tolerating the others would mean
accepting whichever outcome appeared, which is the vacuous pass this row exists
to avoid.

BOTH MANIFESTS ARE MADE GENUINELY BOOTABLE, WHICH IS WHAT MAKES THE RESULT MEAN
SOMETHING. Each slot is bound to its drawn ROM key -- selector, that key's
modulus, and a signature by that key -- so the fuse bitmap is the ONLY thing that
can refuse either one. A revocation check that did nothing would boot every class,
including the terminal one. The binding is proved offline before the simulation:
the shipped slot is fully sealed, the local signer reproduces the packer's
signature byte for byte, and the re-signed slot verifies against its own modulus.

THE EXPECTATION IS RECOMPUTED FROM THE ARTEFACTS, NOT FROM THE RNG. The bitmap is
read back out of ``out/sep_efuse.hex`` and the two slot indices out of the mutated
flash image written to disk. The outcome is then a two-boolean truth table over
those measured values: is the primary's bit set, is the backup's bit set.
``bitmap != 0`` is a third input used ONLY to label the coverage bin, never to add
a branch to the table. A stimulus that failed to land therefore fails loudly here
instead of passing against a prediction nothing checked.

WHICH OTP IMAGE THE DUT ACTUALLY SENSES, because two files hold one. The efuse
bank model's ``$readmemh`` is gated on reset -- ``wait (rst_ni)`` in
``hw/ip/efuse/dv/models/efuse_bank_model.sv`` -- and reset releases hundreds of ns
into the run, while ``write_efuse_image`` runs at 0 ns. So the image the DUT senses
is the GOLDEN this testcase writes, and the pre-sim hook's copy is overwritten
before it is ever read. The hook still matters, for a different reason: this
testcase loads its file first and asserts the golden reproduces it word for word,
which is what proves the two processes ran the SAME draw. A hand-duplicated
constraint in the prestage registry would diverge there instead of silently
staging a bitmap nothing predicted. The post-sense backdoor shadow compare in
``sep_base_test`` is the independent third channel: it checks what the DUT sensed
against that same golden.

ONE CHECK IS DELIBERATELY RELAXED RELATIVE TO THE DIRECTED ROWS. The twelve
``pubkey_rom_{0..5}_revoked_key`` rows assert the fuse word equals exactly one
bit, which a random bitmap cannot satisfy. Here the bitmap is READ instead, and
the strength that check carried is restored by deriving the outcome class from the
measured value and asserting the class in full -- token counts, per-slot
attribution and ordering included.

BITS 6 AND 7 ARE DRAWN AND MUST DO NOTHING. They are declared in
``CHIPLET_PUBK_REVOKE.select[7:0]`` but no ROM slot maps to them, so a set bit
there must never change a verdict.

Closure is a 27-bin model accumulated across regression seeds -- four classes x
six primary slots, plus ``backup == primary`` / ``backup != primary`` inside the
terminal class, plus one bin for bits 6/7 set with no ROM-slot bit. One seed
cannot close it, and this row records which bins it hit rather than claiming any.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import cocotb
import pyuvm
from cocotb.triggers import RisingEdge

from env import sep_key_revocation_draw as kr
from env import sep_manifest_mutate as mm
from env import sep_rom_key_slots as ks
from env import sep_spi_slot_evidence as ev
from env.sep_efuse_image import SepEfuseImage
from env.sep_rom_console import log_scratch_cold, rom_console_task
from env.sep_verdict import decode_verdict
from ocah_spi_vip import OcahSpiFlash
from rom_fw.sep_rom_ot_dma_boot_test import SECURE_FLASH_IMAGE
from sep_base_test import sep_base_test
from sep_reg_meta import sym

_ROM_BASE = sym("SEP_BOOT_ROM_MEM_BASE_ADDR")

# manifest.h. The only code this row's refusals may carry.
MANIFEST_ERR_KEY_REVOKED = 0x0003_0015
# manifest.h, MANIFEST_ERR_SIG_FAILED: the shared code every near-miss arm of
# validate_signature returns (BAD_SIG_TYPE, BAD_KEY_IDX, BAD_KEY_SEL,
# ROM_KEY_EMPTY, FUSE_KEY_EMPTY, PUBK_HASH_TIMEOUT, RSA_VERIFY_FAIL). Forbidding
# it forbids all of them at once.
MANIFEST_ERR_SIG_FAILED = 0x0003_000C

_PRIMARY_SRC = f"MANIFEST_SRC=0x{mm.PRIMARY_MANIFEST_OFFSET:08x}"
_BACKUP_SRC = f"MANIFEST_SRC=0x{mm.BACKUP_MANIFEST_OFFSET:08x}"
_LC_PROD = "LC=PROD"
_BOOT_SPI = "BOOT_SPI"
_RSA_START = "RSA_VERIFY_START"
_SIG_VALID = "SIG_VALID"
_CRYPTO_OK = "CRYPTO_VALIDATE_OK"
_MANIFEST_OK = "MANIFEST_OK"
_BL1_COPIED = "BL1_COPIED"
_BL1_JUMP = "BL1_JUMP="
_PRE_JUMP = "PRE_JUMP"
_ALL_FAILED = "MANIFEST_ALL_FAILED"
_REVOKED_ERR = f"MANIFEST_ERR=0x{MANIFEST_ERR_KEY_REVOKED:08x}"
_REVOKED_CRYPTO_FAIL = f"CRYPTO_FAIL=0x{MANIFEST_ERR_KEY_REVOKED:08x}"

# Never acceptable, in any class. Each one is a way for this row to look green
# while the revocation check was never the reason for what happened:
#   * SBOOT_OFF / the SBOOT_DIS fuse -- the crypto chain was skipped entirely;
#   * WAIT_SMC_MANIFEST -- the manifest came from SMC SRAM, not the flash device;
#   * the MANIFEST_ERR_SIG_FAILED code and its tokens -- a near-miss refusal
#     (empty slot, wrong digest, bad index) standing in for a revocation;
#   * VERSION_ROLLBACK -- the rollback check, which runs BEFORE key selection,
#     rejected a slot first.
_ALWAYS_FORBIDDEN = (
    "SBOOT_OFF", "FUSE: SBOOT_DIS: 1", "WAIT_SMC_MANIFEST",
    f"MANIFEST_ERR=0x{MANIFEST_ERR_SIG_FAILED:08x}",
    f"CRYPTO_FAIL=0x{MANIFEST_ERR_SIG_FAILED:08x}",
    "ROM_KEY_EMPTY", "FUSE_KEY_EMPTY", "PUBK_HASH_MISMATCH", "PUBK_HASH_TIMEOUT",
    "BAD_KEY_IDX", "BAD_KEY_SEL", "BAD_SIG_TYPE=", "RSA_VERIFY_FAIL",
    "VERSION_ROLLBACK", "PLD_HASH_FAIL=", "FLASH_REINIT_FAIL=",
)

_MAX_RUN_CYCLES = 24_000_000
_NO_BOOT_CYCLES = 200_000
_PROGRESS_EVERY = 200_000
# Watch window after a terminal verdict, matching sep_backup_manifest_fail_base:
# the ROM's terminal path ends in `for(;;) wfi`, and "it stopped" has to be an
# observation rather than a property of the noreturn attribute.
_QUIESCE_CYCLES = 20_000


def _archive(src, name: str) -> None:
    """Copy an artefact next to the results XML, where the run keeps its evidence."""
    results = os.environ.get("COCOTB_RESULTS_FILE")
    if results:
        shutil.copyfile(src, os.path.join(os.path.dirname(results), name))


@pyuvm.test()
class sep_key_revocation_bitmap_random_test(sep_base_test):
    """Random revocation bitmap x random ROM key slots; outcome derived, not assumed."""

    build_env = False
    flash_image = SECURE_FLASH_IMAGE

    # --- stimulus ----------------------------------------------------------
    def _stage_efuse(self, drawn) -> SepEfuseImage:
        """Read the pre-staged OTP file, then prove this run's golden reproduces it.

        Not a claim about what the DUT sensed -- the model's ``$readmemh`` waits
        for reset and the golden written at 0 ns has replaced this file by then.
        It is the cross-process check: the pre-sim hook and this testcase must
        have run the SAME draw, and a registry that duplicated the constraint by
        hand would diverge here instead of silently staging another bitmap.
        """
        assert "sep_efuse_preload" not in cocotb.plusargs, (
            "+sep_efuse_preload is set for this test, which makes "
            "select_efuse_image load a fixed file and ignore the drawn bitmap. "
            "This row must run the randomized path on both readers"
        )
        staged_path = Path(os.getcwd()) / "out" / "sep_efuse.hex"
        assert staged_path.is_file(), (
            f"no pre-staged OTP image at {staged_path}: dv_sim_prestage.stage() "
            f"did not run for this test, so nothing cross-checks the draw this "
            f"testcase made"
        )
        staged = SepEfuseImage().load_hex(staged_path)
        # Archive the hook's file before write_efuse_image() overwrites it, so the
        # cross-process comparison stays reproducible after the run.
        _archive(staged_path, "sep_efuse.staged.hex")

        image = self.select_efuse_image(
            lc_raw=kr.LC_RAW_PROD, fixed=kr.efuse_fixed(drawn.bitmap)
        )
        assert image.words == staged.words, (
            "the golden OTP image and the pre-staged one differ, so the prestage "
            "hook and this testcase did not derive the same stimulus from the "
            "seed. First differing word: "
            + str(next((i, hex(a), hex(b)) for i, (a, b)
                       in enumerate(zip(image.words, staged.words)) if a != b))
        )

        # From the golden, which is what the DUT senses and what the post-sense
        # backdoor compare in sep_base_test checks the sensed shadow against.
        bitmap = image.field_int("CHIPLET_PUBK_REVOKE")
        lc = image.lc_raw()
        sboot_dis = image.field_int("SBOOT_DIS") & 0x1
        bl1_ver = image.field_int("BL1_VERSION")
        assert lc == kr.LC_RAW_PROD, (
            f"LC_STATE raw is 0x{lc:x}, expected 0x{kr.LC_RAW_PROD:x} (PROD): "
            f"secure boot must be enforced by the lifecycle or key selection is "
            f"never reached on the production path"
        )
        assert sboot_dis == 0, (
            f"SBOOT_DIS is {sboot_dis}: the crypto chain would be skipped entirely"
        )
        assert bl1_ver == 0, (
            f"BL1_VERSION is 0x{bl1_ver:x}, expected 0: the rollback check runs "
            f"before key selection and would reject a slot first"
        )
        assert bitmap == drawn.bitmap, (
            f"the golden CHIPLET_PUBK_REVOKE is 0x{bitmap:02x} but this seed drew "
            f"0x{drawn.bitmap:02x}; the stimulus did not land"
        )
        self.logger.info(
            "CHK-STIMULUS-EFUSE: golden reproduces the pre-staged %s word for word; "
            "LC raw=0x%x (PROD), SBOOT_DIS=%d, BL1_VERSION=0x%x, "
            "CHIPLET_PUBK_REVOKE=0x%02x, SEP_SPI_CTRL_FIELD_EN=0x%08x (unpinned, "
            "read only at pll_init.c:49 which the bl0_pll_clk strap gates off)",
            staged_path, lc, sboot_dis, bl1_ver, bitmap,
            image.field_int("SEP_SPI_CTRL_FIELD_EN"),
        )
        self.write_efuse_image(image)
        return image

    def _stage_flash(self, drawn) -> bytes:
        """Bind both manifests to their drawn slots and write the image to disk.

        The returned bytes are re-read from the file, so the selectors the checker
        recomputes the expectation from come out of the artifact rather than out of
        the buffer the stimulus happened to build.
        """
        with open(self.flash_image, "rb") as fh:
            buf = bytearray(fh.read())
        info = {
            "primary": ks.bind_manifest_to_rom_slot(buf, "primary", drawn.primary_slot),
            "backup": ks.bind_manifest_to_rom_slot(buf, "backup", drawn.backup_slot),
        }
        out_dir = Path(os.getcwd()) / "out"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / "sep_key_revocation_flash.bin"
        path.write_bytes(bytes(buf))
        _archive(path, "sep_key_revocation_flash.bin")
        loaded = path.read_bytes()
        assert loaded == bytes(buf), f"{path} does not hold the image just written"
        for slot in ("primary", "backup"):
            self.logger.info(
                "CHK-STIMULUS-%s-BOUND: public_key_sel=0x%04x (ROM key slot %d, "
                "%s), modulus digest %s, re-signed with %s; TBS changed=%s",
                slot.upper(), info[slot]["selector"], info[slot]["index"],
                info[slot]["key_name"], info[slot]["digest"].hex()[:16],
                Path(info[slot]["key_path"]).name, info[slot]["tbs_changed"],
            )
            self.logger.info("CHK-STIMULUS-%s: %s", slot.upper(),
                             mm.describe(loaded, slot))
        return loaded

    def _measure(self, sensed_image, staged_flash, drawn):
        """Recompute the expected class from the artefacts this run will use."""
        bitmap = sensed_image.field_int("CHIPLET_PUBK_REVOKE")
        slots = {}
        for slot in ("primary", "backup"):
            sel = mm.get_public_key_sel(staged_flash, slot)
            selection = (sel >> 4) & 0x7
            assert selection == kr.PUBK_SEL_ROM_KEY, (
                f"{slot} public_key_sel 0x{sel:04x} selects key source "
                f"{selection}, not PUBK_SEL_ROM_KEY: this row's outcome table is "
                f"only defined on the ROM-key arm"
            )
            slots[slot] = sel & 0xF
        measured = kr.classify(bitmap, slots["primary"], slots["backup"])
        # The loud failure the procedure asks for: a stimulus that did not land in
        # the drawn class must not be graded against the class it reached.
        assert measured == drawn.expected_class, (
            f"the stimulus did not land: seed drew {drawn.describe()}, but the "
            f"artefacts hold bitmap=0x{bitmap:02x} primary_slot={slots['primary']} "
            f"backup_slot={slots['backup']}, which classifies as {measured}"
        )
        self.logger.info(
            "CHK-DRAW-CLASS: measured bitmap=0x%02x (bit[p=%d]=%d, bit[b=%d]=%d, "
            "bitmap!=0 is %s) -> class %s -> outcome %s",
            bitmap, slots["primary"], int(kr.bit_set(bitmap, slots["primary"])),
            slots["backup"], int(kr.bit_set(bitmap, slots["backup"])),
            bitmap != 0, measured, kr.outcome_of(measured),
        )
        return bitmap, slots["primary"], slots["backup"], measured

    # --- scenario ----------------------------------------------------------
    async def run_scenario(self) -> None:
        dut = cocotb.top
        seed = self.random_seed()
        drawn = kr.draw(seed)
        self.logger.info("CHK-DRAW: seed=%d -> %s", seed, drawn.describe())

        sensed_image = self._stage_efuse(drawn)
        staged_flash = self._stage_flash(drawn)
        bitmap, p_slot, b_slot, cls = self._measure(sensed_image, staged_flash, drawn)
        outcome = kr.outcome_of(cls)
        self._image_len = len(staged_flash)

        console: list[str] = []
        cocotb.start_soon(rom_console_task(self.logger, sink=console))

        flash = OcahSpiFlash(
            dut.spi_cs_n_o, dut.spi_sck_o, mosi=dut.spi_mosi_o, miso=dut.spi_miso_i,
            name="sep_key_revocation_flash",
        )
        flash.preload(staged_flash)
        await flash.start()

        status_seq: list[int] = []
        last_status = None
        fw_done = False
        fw_pass = 0
        retired = 0
        last_log = 0
        post_status_moved = False
        post_console: list[str] = []
        try:
            await self.bring_up_cpu_boot(_ROM_BASE >> 1, run_pulse_cycles=40)
            for cycle in range(_MAX_RUN_CYCLES):
                await RisingEdge(dut.clk_i)
                probe = self.rd(dut.scratch_cold_probe_o)
                status = (probe >> 32) & 0xFFFF_FFFF
                if status != last_status:
                    last_status = status
                    status_seq.append(status)
                if self.rd(dut.cpu_trace_valid_o):
                    retired += 1
                verdict = decode_verdict(probe)
                if verdict is not None:
                    fw_done = True
                    fw_pass = verdict[1]
                    self.logger.info(
                        "CHK-VERDICT: completion signalled at cycle %d via "
                        "cold_scratch[0], pass=%d", cycle, fw_pass,
                    )
                    break
                if cycle - last_log >= _PROGRESS_EVERY:
                    last_log = cycle
                    self.logger.info(
                        "revocation poll cyc=%d status=0x%08x retired=%d lines=%d",
                        cycle, status, retired, len(console),
                    )
                if cycle >= _NO_BOOT_CYCLES and retired == 0:
                    self.logger.error(
                        "core retired no instructions in %d cycles; aborting",
                        _NO_BOOT_CYCLES,
                    )
                    break
            if fw_done and outcome == kr.OUTCOME_TERMINAL:
                console_len_at_done = len(console)
                for _ in range(_QUIESCE_CYCLES):
                    await RisingEdge(dut.clk_i)
                    probe = self.rd(dut.scratch_cold_probe_o)
                    if ((probe >> 32) & 0xFFFF_FFFF) != last_status:
                        post_status_moved = True
                        break
                post_console = console[console_len_at_done:]
        finally:
            await flash.stop()
            self.logger.info("CHK-SPI-TXNS:\n%s",
                             ev.summarize(flash.get_transactions(), self._image_len))
            log_scratch_cold(self.logger)

        self._check(console, status_seq, fw_done, fw_pass, retired, flash,
                    bitmap=bitmap, p_slot=p_slot, b_slot=b_slot, cls=cls)
        if outcome == kr.OUTCOME_TERMINAL:
            self._check_quiesced(post_status_moved, post_console, last_status)
        self._record_coverage(seed, drawn, bitmap, p_slot, b_slot, cls)

    # --- checks ------------------------------------------------------------
    def _check(self, console, status_seq, fw_done, fw_pass, retired, flash, *,
               bitmap: int, p_slot: int, b_slot: int, cls: str) -> None:
        log = self.logger
        log.info("cold_scratch[1] sequence: %s", [hex(v) for v in status_seq])
        log.info("ROM console: %s", console)

        # Guard the guards: a dark console or a core that never ran makes every
        # marker check below vacuous.
        assert retired, "core retired no instructions; the ROM never ran"
        assert console, (
            "ROM console is empty, so no marker check below means anything (the "
            "virt console is DEBUG-build only -- check the ROM build)"
        )

        def idx(marker: str, after: int = -1) -> int:
            for i, line in enumerate(console):
                if i > after and marker in line:
                    return i
            return -1

        def hits(marker: str) -> list[int]:
            return [i for i, line in enumerate(console) if marker in line]

        for marker in _ALWAYS_FORBIDDEN:
            assert not hits(marker), (
                f"ROM printed {marker}, which means the run did not end on the "
                f"revocation check this row draws for. Console: {console}"
            )
        for marker in (_LC_PROD, _BOOT_SPI, _PRIMARY_SRC):
            assert hits(marker), (
                f"ROM never printed {marker}. Console: {console}"
            )

        outcome = kr.outcome_of(cls)
        sel_p = f"PUBK_SEL=0x{p_slot:08x}"
        sel_b = f"PUBK_SEL=0x{b_slot:08x}"
        revoke_echo = f"PUBK_REVOKE=0x{bitmap:08x}"
        revoked_p = f"KEY_REVOKED idx=0x{p_slot:08x}"
        revoked_b = f"KEY_REVOKED idx=0x{b_slot:08x}"

        # How many slot attempts reach the ROM-key arm of validate_signature. The
        # selector and the fuse word are echoed once per attempt, so these counts
        # are what say no slot this stimulus did not account for ran key selection.
        attempts = 1 if outcome == kr.OUTCOME_PROCEED else 2
        n_sel = len(hits("PUBK_SEL="))
        n_revoke_any = len(hits("PUBK_REVOKE="))
        assert n_sel == attempts and n_revoke_any == attempts, (
            f"key selection ran {n_sel} times and the fuse word was read "
            f"{n_revoke_any} times, expected {attempts} of each for a {outcome} "
            f"outcome. Console: {console}"
        )
        # The fuse word is echoed unconditionally before this slot's bit is tested,
        # so every attempt prints the SAME bitmap; only KEY_REVOKED idx= is
        # per-slot. A different value here would mean the DUT sensed some other
        # image than the golden this run wrote.
        assert len(hits(revoke_echo)) == attempts, (
            f"{revoke_echo} appeared {len(hits(revoke_echo))} times, expected "
            f"{attempts}: the ROM did not read this run's bitmap on every attempt. "
            f"Console: {console}"
        )
        i_psrc = idx(_PRIMARY_SRC)
        i_sel_p = idx(sel_p)
        revokes = hits(revoke_echo)
        assert 0 <= i_psrc < i_sel_p < revokes[0], (
            f"key selection is not attributable to the primary: {_PRIMARY_SRC}"
            f"@{i_psrc} -> {sel_p}@{i_sel_p} -> {revoke_echo}@{revokes}. "
            f"Console: {console}"
        )

        if outcome == kr.OUTCOME_PROCEED:
            self._check_proceed(console, idx, hits, fw_done, fw_pass, flash,
                                sel_p=sel_p, revoke_echo=revoke_echo,
                                i_psrc=i_psrc,
                                i_sel_p=i_sel_p, i_revoke=revokes[0],
                                bitmap=bitmap, p_slot=p_slot, cls=cls)
        elif outcome == kr.OUTCOME_FAILOVER:
            self._check_failover(console, idx, hits, fw_done, fw_pass, flash,
                                 sel_p=sel_p, sel_b=sel_b, revokes=revokes,
                                 revoked_p=revoked_p, revoked_b=revoked_b,
                                 i_sel_p=i_sel_p,
                                 p_slot=p_slot, b_slot=b_slot)
        else:
            self._check_terminal(console, idx, hits, status_seq, fw_done, fw_pass,
                                 flash, sel_p=sel_p, sel_b=sel_b, revokes=revokes,
                                 revoked_p=revoked_p, revoked_b=revoked_b,
                                 i_psrc=i_psrc, i_sel_p=i_sel_p,
                                 p_slot=p_slot, b_slot=b_slot)

    def _check_proceed(self, console, idx, hits, fw_done, fw_pass, flash, *,
                       sel_p, revoke_echo, i_psrc, i_sel_p, i_revoke,
                       bitmap, p_slot, cls) -> None:
        """The primary's slot is not revoked, so the primary boots."""
        for marker in ("KEY_REVOKED idx=", _REVOKED_ERR, _REVOKED_CRYPTO_FAIL,
                       _BACKUP_SRC, _ALL_FAILED, "MANIFEST_ERR="):
            assert not hits(marker), (
                f"ROM printed {marker}: the primary's slot {p_slot} is not revoked "
                f"under bitmap 0x{bitmap:02x}, so nothing may be refused. "
                f"Console: {console}"
            )
        i_rsa = idx(_RSA_START)
        i_sig = idx(_SIG_VALID)
        i_ok = idx(_CRYPTO_OK)
        i_mok = idx(_MANIFEST_OK)
        i_jump = idx(_BL1_JUMP)
        assert i_revoke < i_rsa < i_sig < i_ok < i_mok < i_jump, (
            f"the boot did not run key selection then the verifier in the "
            f"architected order: {revoke_echo}@{i_revoke} -> {_RSA_START}@{i_rsa} "
            f"-> {_SIG_VALID}@{i_sig} -> {_CRYPTO_OK}@{i_ok} -> "
            f"{_MANIFEST_OK}@{i_mok} -> {_BL1_JUMP}@{i_jump}. Console: {console}"
        )
        for marker in (_RSA_START, _SIG_VALID, _CRYPTO_OK, _BL1_COPIED, _PRE_JUMP):
            assert len(hits(marker)) == 1, (
                f"{marker} appeared {len(hits(marker))} times, expected exactly 1 "
                f"(the primary's). Console: {console}"
            )
        assert fw_done and fw_pass, (
            f"a {cls} seed must complete the boot: fw_done={fw_done} "
            f"fw_pass={fw_pass}"
        )
        # The channel the ROM cannot fake. A silent failover also reaches
        # MANIFEST_OK, and only the device's transaction record can rule it out.
        rds = ev.reads(flash.get_transactions())
        hit = ev.covering_read(rds, mm.PRIMARY_MANIFEST_OFFSET)
        assert hit is not None, (
            f"no SPI read covered the primary manifest address "
            f"0x{mm.PRIMARY_MANIFEST_OFFSET:x}: the boot did not come from the "
            f"primary"
        )
        backup_hits = ev.slot_read_indices(rds, "backup", self._image_len)
        assert not backup_hits, (
            f"device served {len(backup_hits)} read(s) inside the backup slot span "
            f"(read indices {backup_hits}): this is a failover, not a primary boot"
        )
        self.logger.info(
            "CHK-REVOKE-PROCEED: %s primary@%d -> %s@%d -> %s@%d (bit %d clear) -> "
            "%s@%d -> %s@%d -> %s@%d -> %s@%d, no KEY_REVOKED anywhere, and no read "
            "inside the backup span across %d reads",
            cls, i_psrc, sel_p, i_sel_p, revoke_echo, i_revoke, p_slot,
            _RSA_START, idx(_RSA_START), _SIG_VALID, idx(_SIG_VALID),
            _CRYPTO_OK, idx(_CRYPTO_OK), _BL1_JUMP, idx(_BL1_JUMP), len(rds),
        )

    def _check_failover(self, console, idx, hits, fw_done, fw_pass, flash, *,
                        sel_p, sel_b, revokes, revoked_p, revoked_b,
                        i_sel_p, p_slot, b_slot) -> None:
        """The primary's slot is revoked, the backup's is not, so the backup boots."""
        i_revoked_p = idx(revoked_p)
        i_crypto = idx(_REVOKED_CRYPTO_FAIL)
        i_err = idx(_REVOKED_ERR)
        i_bsrc = idx(_BACKUP_SRC)
        i_sel_b = idx(sel_b, after=i_bsrc)
        i_rsa = idx(_RSA_START)
        i_sig = idx(_SIG_VALID)
        i_ok = idx(_CRYPTO_OK)
        i_mok = idx(_MANIFEST_OK)
        i_jump = idx(_BL1_JUMP)

        # CHK-REVOKE-ATTRIBUTION: the ROM read the primary's selector, consulted
        # the fuse word, refused THAT index, and only then read the backup.
        assert i_sel_p < revokes[0] < i_revoked_p < i_crypto < i_err < i_bsrc, (
            f"the revocation verdict is not attributable to the primary's slot "
            f"{p_slot}: {sel_p}@{i_sel_p} -> PUBK_REVOKE@{revokes[0]} -> "
            f"{revoked_p}@{i_revoked_p} -> {_REVOKED_CRYPTO_FAIL}@{i_crypto} -> "
            f"{_REVOKED_ERR}@{i_err} -> backup@{i_bsrc}. Console: {console}"
        )
        assert len(hits("KEY_REVOKED idx=")) == 1, (
            f"KEY_REVOKED appeared {len(hits('KEY_REVOKED idx='))} times, expected "
            f"exactly 1 (the primary's, slot {p_slot}). Console: {console}"
        )
        assert not hits(revoked_b), (
            f"{revoked_b} appeared: the backup's slot {b_slot} is NOT revoked "
            f"under this bitmap, so a failover cannot refuse it. Console: {console}"
        )
        # The second fuse echo, after the backup read, is what proves the BOOTING
        # slot ran the revocation check and was permitted -- not that the check
        # was skipped for it.
        assert revokes[0] < i_bsrc < revokes[1], (
            f"the fuse echoes {revokes} do not straddle the backup read@{i_bsrc}: "
            f"the booting slot did not consult the revocation bitmap. "
            f"Console: {console}"
        )
        assert i_bsrc < i_sel_b < revokes[1] < i_rsa < i_sig < i_ok < i_mok < i_jump, (
            f"the booting slot's key selection is unattributed or out of order: "
            f"backup@{i_bsrc} -> {sel_b}@{i_sel_b} -> PUBK_REVOKE@{revokes[1]} -> "
            f"{_RSA_START}@{i_rsa} -> {_SIG_VALID}@{i_sig} -> {_CRYPTO_OK}@{i_ok} "
            f"-> {_MANIFEST_OK}@{i_mok} -> {_BL1_JUMP}@{i_jump}. Console: {console}"
        )
        # Revocation precedes rsa_3072_verify, so the refused primary must never
        # have driven the verifier: exactly one run, the backup's.
        for marker in (_RSA_START, _SIG_VALID, _CRYPTO_OK, _MANIFEST_OK):
            assert len(hits(marker)) == 1, (
                f"{marker} appeared {len(hits(marker))} times, expected exactly 1 "
                f"(the backup's); the refused primary must not reach the verifier. "
                f"Console: {console}"
            )
        assert i_rsa > i_bsrc, (
            f"{_RSA_START}@{i_rsa} came before the backup read@{i_bsrc}: the "
            f"refused primary reached the RSA verifier. Console: {console}"
        )
        assert not hits(_ALL_FAILED), (
            f"ROM printed {_ALL_FAILED}: the retry loop exhausted instead of "
            f"booting from the unrevoked backup slot {b_slot}. Console: {console}"
        )
        assert fw_done and fw_pass, (
            f"a failover seed must complete the boot from the backup: "
            f"fw_done={fw_done} fw_pass={fw_pass}"
        )
        rds = ev.reads(flash.get_transactions())
        p_hit = ev.covering_read(rds, mm.PRIMARY_MANIFEST_OFFSET)
        b_hit = ev.covering_read(rds, mm.BACKUP_MANIFEST_OFFSET)
        assert p_hit is not None and b_hit is not None and p_hit[0] < b_hit[0], (
            f"the device did not serve the primary address before the backup: "
            f"primary={p_hit} backup={b_hit}; the transaction order is not a "
            f"failover"
        )
        self.logger.info(
            "CHK-REVOKE-FAILOVER: primary slot %d %s@%d -> PUBK_REVOKE@%d -> %s@%d "
            "-> %s@%d -> backup@%d -> backup slot %d %s@%d -> PUBK_REVOKE@%d "
            "(permitted) -> %s@%d -> %s@%d; device served read[%d] then read[%d]",
            p_slot, sel_p, i_sel_p, revokes[0], revoked_p, i_revoked_p,
            _REVOKED_ERR, i_err, i_bsrc, b_slot, sel_b, i_sel_b, revokes[1],
            _SIG_VALID, i_sig, _BL1_JUMP, i_jump, p_hit[0], b_hit[0],
        )

    def _check_terminal(self, console, idx, hits, status_seq, fw_done, fw_pass,
                        flash, *, sel_p, sel_b, revokes, revoked_p, revoked_b,
                        i_psrc, i_sel_p, p_slot, b_slot) -> None:
        """Both slots are revoked, so both are refused and the retry loop exhausts."""
        i_bsrc = idx(_BACKUP_SRC)
        assert i_bsrc > i_psrc >= 0, (
            f"the backup slot was not read after the primary: primary@{i_psrc}, "
            f"backup@{i_bsrc}. Console: {console}"
        )
        # Nothing downstream of a refusal may run, in either slot. These are the
        # load-bearing forbids: both manifests are otherwise valid and correctly
        # signed, so a revocation check that did nothing would BOOT here.
        for marker in (_RSA_START, _SIG_VALID, _CRYPTO_OK, _MANIFEST_OK,
                       _PRE_JUMP, _BL1_COPIED, _BL1_JUMP):
            assert not hits(marker), (
                f"ROM printed {marker}: a slot got past a revocation refusal, so "
                f"both selected keys were not refused. Console: {console}"
            )
        # One refusal per slot, one on each side of the backup read. p == b is a
        # drawn case, and then one marker legitimately appears twice.
        revoked_hits = hits("KEY_REVOKED idx=")
        assert len(revoked_hits) == 2, (
            f"KEY_REVOKED appeared {len(revoked_hits)} times at {revoked_hits}, "
            f"expected exactly 2 -- one per manifest slot. One occurrence would "
            f"mean only one slot reached key selection. Console: {console}"
        )
        assert revoked_hits[0] < i_bsrc < revoked_hits[1], (
            f"the two KEY_REVOKED occurrences {revoked_hits} do not straddle the "
            f"backup read@{i_bsrc}: the refusals are not one per slot. "
            f"Console: {console}"
        )
        assert hits(revoked_p)[0] == revoked_hits[0], (
            f"the first refusal is not the primary's slot {p_slot} ({revoked_p}). "
            f"Console: {console}"
        )
        assert hits(revoked_b)[-1] == revoked_hits[1], (
            f"the second refusal is not the backup's slot {b_slot} ({revoked_b}). "
            f"Console: {console}"
        )
        i_sel_b = idx(sel_b, after=i_bsrc)
        assert i_sel_p < revokes[0] < revoked_hits[0] < i_bsrc < i_sel_b \
            < revokes[1] < revoked_hits[1], (
            f"the two refusals are not each attributable to their own slot: "
            f"{sel_p}@{i_sel_p} -> PUBK_REVOKE@{revokes[0]} -> "
            f"KEY_REVOKED@{revoked_hits[0]} -> backup@{i_bsrc} -> {sel_b}"
            f"@{i_sel_b} -> PUBK_REVOKE@{revokes[1]} -> "
            f"KEY_REVOKED@{revoked_hits[1]}. Console: {console}"
        )
        # The error code, once per slot, straddling the backup read: the console
        # marker says which check complained, the code says what the ROM converged
        # on, and the positions attribute one to each slot.
        for marker in (_REVOKED_CRYPTO_FAIL, _REVOKED_ERR):
            marker_hits = hits(marker)
            assert len(marker_hits) == 2 and marker_hits[0] < i_bsrc < marker_hits[1], (
                f"{marker} appeared at {marker_hits}, expected exactly 2 "
                f"straddling the backup read@{i_bsrc} -- one per refused slot. "
                f"Console: {console}"
            )
        assert hits(_ALL_FAILED), (
            f"ROM never printed {_ALL_FAILED}: the retry loop did not exhaust, so "
            f"this is not the both-slots-refused outcome. Console: {console}"
        )
        expected_status = 0x0F01_0000 | (MANIFEST_ERR_KEY_REVOKED & 0xFFFF)
        assert expected_status in status_seq, (
            f"cold_scratch[1] never held 0x{expected_status:08x} "
            f"(STATUS_ENCODE(ERROR, 0x{MANIFEST_ERR_KEY_REVOKED & 0xFFFF:04x})); "
            f"observed {[hex(v) for v in status_seq]}"
        )
        assert fw_done, (
            f"ROM never signalled completion within {_MAX_RUN_CYCLES} cycles; a "
            f"terminal run must converge on a FAIL verdict. cold_scratch[1]: "
            f"{[hex(v) for v in status_seq]}"
        )
        assert not fw_pass, "ROM signalled PASS: it booted an image it had refused"
        rds = ev.reads(flash.get_transactions())
        p_hit = ev.covering_read(rds, mm.PRIMARY_MANIFEST_OFFSET)
        b_hit = ev.covering_read(rds, mm.BACKUP_MANIFEST_OFFSET)
        assert p_hit is not None and b_hit is not None and p_hit[0] < b_hit[0], (
            f"the device did not serve both manifest addresses in order: "
            f"primary={p_hit} backup={b_hit}. Both slots must really be fetched "
            f"for 'both were refused' to mean anything"
        )
        self.logger.info(
            "CHK-REVOKE-TERMINAL: primary slot %d %s@%d -> PUBK_REVOKE@%d -> %s@%d "
            "-> backup@%d -> backup slot %d %s@%d -> PUBK_REVOKE@%d -> %s@%d -> "
            "%s, cold_scratch[1]=0x%08x, FAIL verdict; device served read[%d] then "
            "read[%d] and neither slot reached the verifier",
            p_slot, sel_p, i_sel_p, revokes[0], revoked_p, revoked_hits[0], i_bsrc,
            b_slot, sel_b, i_sel_b, revokes[1], revoked_b, revoked_hits[1],
            _ALL_FAILED, expected_status, p_hit[0], b_hit[0],
        )

    def _check_quiesced(self, post_status_moved, post_console, terminal_status) -> None:
        """CHK-HANG: the ROM stopped, rather than reporting and continuing."""
        assert not post_status_moved, (
            f"cold_scratch[1] moved on from 0x{terminal_status:08x} within "
            f"{_QUIESCE_CYCLES} cycles of the terminal verdict: the ROM reported "
            f"the terminal error and then kept running"
        )
        assert not post_console, (
            f"ROM printed {post_console} after the terminal verdict; a terminal "
            f"error path ends in `for(;;) wfi` and produces no further output"
        )
        self.logger.info(
            "CHK-HANG: cold_scratch[1] held 0x%08x and the console stayed silent "
            "for %d cycles after the terminal verdict",
            terminal_status, _QUIESCE_CYCLES,
        )

    def _record_coverage(self, seed, drawn, bitmap, p_slot, b_slot, cls) -> None:
        """Log and persist the bins this seed hit, out of the 27 closure needs.

        One seed cannot close the model, so this records what was covered and
        never claims closure; ``regression_stable`` is gated on the accumulated
        set across seeds.
        """
        bins = kr.coverage_bins(bitmap, p_slot, b_slot)
        record = {
            "testcase": "sep_key_revocation_bitmap_random_test",
            "seed": seed,
            "drawn": {
                "bitmap": drawn.bitmap,
                "primary_slot": drawn.primary_slot,
                "backup_slot": drawn.backup_slot,
                "expected_class": drawn.expected_class,
            },
            "measured": {
                "bitmap": bitmap,
                "primary_slot": p_slot,
                "backup_slot": b_slot,
                "class": cls,
                "outcome": kr.outcome_of(cls),
            },
            "bins_hit": list(bins),
            "bins_total": list(kr.all_bins()),
            # Travels with the artefact, so a closure claim assembled from these
            # files alone cannot miss what a full set does not prove.
            "closure_caveats": list(kr.CLOSURE_CAVEATS),
            "closure_claimed": False,
        }
        out = Path(os.getcwd()) / "out" / "sep_key_revocation_coverage.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        _archive(out, "sep_key_revocation_coverage.json")
        self.logger.info(
            "CHK-COVERAGE: seed %d hit %d of the 27 closure bins: %s (recorded in "
            "%s). Closure is accumulated across regression seeds and is NOT "
            "claimed by this run", seed, len(bins), ", ".join(bins), out,
        )
