# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Constrained-random CHIPLET_PUBK_REVOKE bitmap x each manifest's ROM key slot.

The seed draws a bitmap and both slots' ROM keys; the expected outcome (primary boots,
failover, or both refused) is recomputed from the staged artefacts, not from the RNG.
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
from env import sep_oca_console as oc
from env import sep_rom_key_slots as ks
from env import sep_spi_slot_evidence as ev
from env.sep_efuse_image import SepEfuseImage
from env.sep_esrc_noise import esrc_noise_task
from env.sep_rom_console import log_scratch_cold, rom_console_task
from env.sep_verdict import decode_verdict
from ocah_spi_vip import OcahSpiFlash
from rom_fw.sep_rom_ot_dma_boot_test import SECURE_FLASH_IMAGE
from sep_base_test import sep_base_test
from sep_reg_meta import sym

_ROM_BASE = sym("SEP_BOOT_ROM_MEM_BASE_ADDR")

MANIFEST_ERR_KEY_REVOKED = mm.boot_err("OCA_FAIL_ROOT_KEY_REVOKED")

_LC_PROD = "LC=PROD"
_BOOT_SPI = "BOOT_SPI"
_ALL_FAILED = "MANIFEST_ALL_FAILED"
_REVOKED_ERR = f"MANIFEST_ERR=0x{MANIFEST_ERR_KEY_REVOKED:08x}"
_VERIFIED = (
    "FUSE_VER=",
    "RSA_EXEC",
    "RSA_CMP1",
    "RSA_CMP2",
    "RSA_VERIFY_OK",
    "FUSE_VER=",
    "MANIFEST_OK",
    "PAYLOAD_OK",
)
_BOOTED = ("BL1_COPIED", "BL1_JUMP=", "PRE_JUMP")

_ALWAYS_FORBIDDEN = (
    "SBOOT_OFF",
    "FUSE: SBOOT_DIS: 1",
    "WAIT_SMC_MANIFEST",
    "PUBK_SEL_AMBIGUOUS",
    "PUBK_SEL_EMPTY",
    "PUBK_SLOT_RESERVED",
    "PUBK_SLOT_UNPROVISIONED",
    "PUBK_UNAUTHORIZED",
    "PUBK_HASH_TIMEOUT",
    "RSA_EXEC_FAIL",
    "RSA_PKCS1_FAIL",
) + tuple(
    f"MANIFEST_ERR=0x{mm.boot_err(n):08x}"
    for n in (
        "OCA_FAIL_SIGNATURE",
        "OCA_FAIL_ROOT_KEY_UNAUTHORIZED",
        "OCA_FAIL_SECURITY_VERSION",
    )
)
oc.assert_known(
    _ALWAYS_FORBIDDEN + _VERIFIED + _BOOTED + (_LC_PROD, _BOOT_SPI, _ALL_FAILED, _REVOKED_ERR),
    __name__,
)

_MAX_RUN_CYCLES = 24_000_000
_NO_BOOT_CYCLES = 200_000
_PROGRESS_EVERY = 200_000
# The terminal path ends in `for(;;) wfi`; watch this long to observe that it stopped.
_QUIESCE_CYCLES = 20_000


def _archive(src, name: str) -> None:
    results = os.environ.get("COCOTB_RESULTS_FILE")
    if results:
        shutil.copyfile(src, os.path.join(os.path.dirname(results), name))


@pyuvm.test()
class sep_key_revocation_bitmap_random_test(sep_base_test):
    """Random revocation bitmap x random ROM key slots; outcome derived, not assumed."""

    build_env = False
    flash_image = SECURE_FLASH_IMAGE

    def _stage_efuse(self, drawn) -> SepEfuseImage:
        # $readmemh waits for reset, so the DUT senses the golden written below, not this file.
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
        # Archive before write_efuse_image() overwrites the hook's file.
        _archive(staged_path, "sep_efuse.staged.hex")

        image = self.select_efuse_image(lc_raw=kr.LC_RAW_PROD, fixed=kr.efuse_fixed(drawn.bitmap))
        assert image.words == staged.words, (
            "the golden OTP image and the pre-staged one differ, so the prestage "
            "hook and this testcase did not derive the same stimulus from the "
            "seed. First differing word: "
            + str(
                next(
                    (i, hex(a), hex(b))
                    for i, (a, b) in enumerate(zip(image.words, staged.words))
                    if a != b
                )
            )
        )

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
            "CHIPLET_PUBK_REVOKE=0x%02x",
            staged_path,
            lc,
            sboot_dis,
            bl1_ver,
            bitmap,
        )
        self.write_efuse_image(image)
        return image

    def _stage_flash(self, drawn) -> bytes:
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
                "%s), modulus digest %s, re-signed with %s; signed region changed=%s",
                slot.upper(),
                info[slot]["selector"],
                info[slot]["index"],
                info[slot]["key_name"],
                info[slot]["digest"].hex()[:16],
                Path(info[slot]["key_path"]).name,
                info[slot]["tbs_changed"],
            )
            self.logger.info("CHK-STIMULUS-%s: %s", slot.upper(), mm.describe(loaded, slot))
        return loaded

    def _measure(self, sensed_image, staged_flash, drawn):
        bitmap = sensed_image.field_int("CHIPLET_PUBK_REVOKE")
        slots = {}
        for slot in ("primary", "backup"):
            sel = mm.get_public_key_sel(staged_flash, slot)
            assert sel < kr.PUBK_SEL_NUM_ROM_KEYS, (
                f"{slot} public_key_select names slot {sel}, not a ROM key slot: this "
                f"row's outcome table is only defined on the ROM-key arm"
            )
            at = mm.slot_base(slot) + mm.K.OFF_PUBLIC_KEY_CLASSIC_REVOKE
            own = bytes(staged_flash[at : at + 16])
            assert not any(own), (
                f"{slot} public_key_classic_revoke is {own.hex()}: the validator ORs it "
                f"into the fuse bitmap, so the outcome would not follow from the draw"
            )
            slots[slot] = sel
        measured = kr.classify(bitmap, slots["primary"], slots["backup"])
        assert measured == drawn.expected_class, (
            f"the stimulus did not land: seed drew {drawn.describe()}, but the "
            f"artefacts hold bitmap=0x{bitmap:02x} primary_slot={slots['primary']} "
            f"backup_slot={slots['backup']}, which classifies as {measured}"
        )
        self.logger.info(
            "CHK-DRAW-CLASS: measured bitmap=0x%02x (bit[p=%d]=%d, bit[b=%d]=%d, "
            "bitmap!=0 is %s) -> class %s -> outcome %s",
            bitmap,
            slots["primary"],
            int(kr.bit_set(bitmap, slots["primary"])),
            slots["backup"],
            int(kr.bit_set(bitmap, slots["backup"])),
            bitmap != 0,
            measured,
            kr.outcome_of(measured),
        )
        return bitmap, slots["primary"], slots["backup"], measured

    async def run_scenario(self) -> None:
        dut = cocotb.top
        # An undriven entropy input trips the repetition health test (ESRC_HEALTH_FAIL).
        cocotb.start_soon(esrc_noise_task(dut, logger=self.logger))
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
            dut.spi_cs_n_o,
            dut.spi_sck_o,
            mosi=dut.spi_mosi_o,
            miso=dut.spi_miso_i,
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
                        "cold_scratch[0], pass=%d",
                        cycle,
                        fw_pass,
                    )
                    break
                if cycle - last_log >= _PROGRESS_EVERY:
                    last_log = cycle
                    self.logger.info(
                        "revocation poll cyc=%d status=0x%08x retired=%d lines=%d",
                        cycle,
                        status,
                        retired,
                        len(console),
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
            self.logger.info(
                "CHK-SPI-TXNS:\n%s", ev.summarize(flash.get_transactions(), self._image_len)
            )
            log_scratch_cold(self.logger)

        self._check(
            console,
            status_seq,
            fw_done,
            fw_pass,
            retired,
            flash,
            bitmap=bitmap,
            p_slot=p_slot,
            b_slot=b_slot,
            cls=cls,
        )
        if outcome == kr.OUTCOME_TERMINAL:
            self._check_quiesced(post_status_moved, post_console, last_status)
        self._record_coverage(seed, drawn, bitmap, p_slot, b_slot, cls)

    def _check(
        self,
        console,
        status_seq,
        fw_done,
        fw_pass,
        retired,
        flash,
        *,
        bitmap: int,
        p_slot: int,
        b_slot: int,
        cls: str,
    ) -> None:
        log = self.logger
        log.info("cold_scratch[1] sequence: %s", [hex(v) for v in status_seq])
        log.info("ROM console: %s", console)

        assert retired, "core retired no instructions; the ROM never ran"
        assert console, (
            "ROM console is empty, so no marker check below means anything (the "
            "virt console is DEBUG-build only -- check the ROM build)"
        )
        for marker in _ALWAYS_FORBIDDEN:
            assert oc.count(console, marker) == 0, (
                f"ROM printed {marker}, which means the run did not end on the "
                f"revocation check this row draws for. Console: {console}"
            )
        for marker in (_LC_PROD, _BOOT_SPI):
            assert oc.count(console, marker), f"ROM never printed {marker}. Console: {console}"

        outcome = kr.outcome_of(cls)
        revoke_echo = f"PUBK_REVOKE=0x{bitmap:08x}"
        plan = [("primary", mm.PRIMARY_MANIFEST_OFFSET, p_slot)]
        if outcome != kr.OUTCOME_PROCEED:
            plan.append(("backup", mm.BACKUP_MANIFEST_OFFSET, b_slot))
        attempts = oc.split_attempts(console)
        assert [a.src for a in attempts] == [src for _, src, _ in plan], (
            f"slot attempts read {[hex(a.src) for a in attempts]}, expected "
            f"{[hex(src) for _, src, _ in plan]} for a {outcome} outcome. Console: {console}"
        )

        def header_at(token: str) -> list[int]:
            return [i for i, line in enumerate(console) if line.strip() == token]

        i_ph = header_at("MANIFEST_PRIMARY")
        assert len(i_ph) == 1 and i_ph[0] < attempts[0].first, (
            f"MANIFEST_PRIMARY@{i_ph} is not once before the primary attempt@{attempts[0].first}"
        )
        i_bh = header_at("MANIFEST_BACKUP")
        if len(attempts) == 2:
            assert len(i_bh) == 1 and attempts[0].last < i_bh[0] < attempts[1].first, (
                f"MANIFEST_BACKUP@{i_bh} is not once between the two attempts"
            )
        else:
            assert not i_bh, f"MANIFEST_BACKUP@{i_bh} printed on a primary-only boot"

        verdicts = []
        for n, (att, (slot, _src, key)) in enumerate(zip(attempts, plan)):
            revoked = kr.bit_set(bitmap, key)
            last = n == len(plan) - 1
            head = ("OCA_BODY=", "MFST_VER=", f"PUBK_SEL=0x{key:08x}", "PUBK_AUTHORIZED")
            if revoked:
                ordered = head + (revoke_echo, _REVOKED_ERR)
                oc.assert_attempt(
                    att,
                    error=MANIFEST_ERR_KEY_REVOKED,
                    stage="manifest",
                    ordered=ordered,
                    absent=("FUSE_VER=", "RSA_EXEC", "MANIFEST_OK"),
                )
                tail = [line for _, line in att.markers][-2:]
                assert oc.count(tail[:1], revoke_echo) == 1, (
                    f"{slot}: the line before {_REVOKED_ERR} is not {revoke_echo} "
                    f"(attempt ends {tail}): the refusal is not the revocation check's"
                )
            else:
                assert last, f"{slot} slot {key} is not revoked but the run went on past it"
                ordered = head + (revoke_echo,) + _VERIFIED + _BOOTED
                oc.assert_attempt(
                    att, error=None, stage="accepted", ordered=ordered, absent=("MANIFEST_ERR=",)
                )
            verdicts.append(
                f"{slot}@{att.first}-{att.last} slot {key} "
                f"{'revoked' if revoked else 'permitted'}: {' -> '.join(ordered)}"
            )

        permitted = sum(1 for _, _, key in plan if not kr.bit_set(bitmap, key))
        for marker, want in (
            ("PUBK_SEL=", len(plan)),
            ("PUBK_REVOKE=", len(plan)),
            (revoke_echo, len(plan)),
            ("RSA_EXEC", permitted),
            ("RSA_VERIFY_OK", permitted),
            ("MANIFEST_OK", permitted),
            (_REVOKED_ERR, len(plan) - permitted),
        ):
            got = oc.count(console, marker)
            assert got == want, (
                f"{marker} appeared {got} times, expected {want} for a {cls} run "
                f"(bitmap=0x{bitmap:02x}, primary slot {p_slot}, backup slot {b_slot}). "
                f"Console: {console}"
            )

        if outcome == kr.OUTCOME_TERMINAL:
            i_all = [i for i, line in enumerate(console) if oc.count([line], _ALL_FAILED)]
            assert len(i_all) == 1 and attempts[-1].last < i_all[0], (
                f"{_ALL_FAILED}@{i_all} is not once after the backup's refusal: the "
                f"retry loop did not exhaust. Console: {console}"
            )
            status_msg = mm.rom_status_for_result(MANIFEST_ERR_KEY_REVOKED)
            expected_status = 0x0F01_0000 | status_msg
            assert expected_status in status_seq, (
                f"cold_scratch[1] never held 0x{expected_status:08x} "
                f"(STATUS_ENCODE(ERROR, 0x{status_msg:04x})); "
                f"observed {[hex(v) for v in status_seq]}"
            )
            assert fw_done, (
                f"ROM never signalled completion within {_MAX_RUN_CYCLES} cycles; a "
                f"terminal run must converge on a FAIL verdict"
            )
            assert not fw_pass, "ROM signalled PASS: it booted an image it had refused"
        else:
            assert oc.count(console, _ALL_FAILED) == 0, (
                f"ROM printed {_ALL_FAILED} on a {outcome} run. Console: {console}"
            )
            assert fw_done and fw_pass, (
                f"a {cls} seed must complete the boot: fw_done={fw_done} fw_pass={fw_pass}"
            )

        # A silent failover also reaches MANIFEST_OK; only the flash record rules it out.
        rds = ev.reads(flash.get_transactions())
        p_hit = ev.covering_read(rds, mm.PRIMARY_MANIFEST_OFFSET)
        assert p_hit is not None, (
            f"no SPI read covered the primary manifest address "
            f"0x{mm.PRIMARY_MANIFEST_OFFSET:x}: the primary was never fetched"
        )
        backup_hits = ev.slot_read_indices(rds, "backup", self._image_len)
        if outcome == kr.OUTCOME_PROCEED:
            assert not backup_hits, (
                f"device served {len(backup_hits)} read(s) inside the backup slot span "
                f"(read indices {backup_hits}): this is a failover, not a primary boot"
            )
        else:
            b_hit = ev.covering_read(rds, mm.BACKUP_MANIFEST_OFFSET)
            assert b_hit is not None and p_hit[0] < b_hit[0], (
                f"the device did not serve the primary address before the backup: "
                f"primary={p_hit} backup={b_hit}; the transaction order is not a failover"
            )
        log.info(
            "CHK-REVOKE-%s PASS: %s bitmap=0x%02x; %s",
            outcome.upper(),
            cls,
            bitmap,
            "; ".join(verdicts),
        )

    def _check_quiesced(self, post_status_moved, post_console, terminal_status) -> None:
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
            terminal_status,
            _QUIESCE_CYCLES,
        )

    def _record_coverage(self, seed, drawn, bitmap, p_slot, b_slot, cls) -> None:
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
            "claimed by this run",
            seed,
            len(bins),
            ", ".join(bins),
            out,
        )
