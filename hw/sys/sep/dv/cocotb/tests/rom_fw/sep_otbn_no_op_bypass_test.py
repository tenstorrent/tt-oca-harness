# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""An OTBN that never executed must not report a verified signature (PyUVM).

FEATURE UNDER TEST. The OTBN RSA application uses ONE DMEM buffer for both the
signature it is given and the modexp result it produces (``inout``, DMEM
``0x600``). If the block never runs, that buffer still holds the signature, and
``verify_pkcs1_v15()`` compares the signature against itself. Nothing else the
ROM reads distinguishes the two cases: ``STATUS`` reads IDLE, which is the state
OTBN was already in, and ``ERR_BITS`` reads 0, because nothing ran to fail.

So a caller who authors the signature field as the literal PKCS#1 v1.5 block the
checker expects -- ``00 01 FF*330 00 || DigestInfo || SHA256(signed region)`` --
gets ``RSA_VERIFY_OK`` on an image whose signature was never checked. No private
key is needed: every byte of that block is public.

THIS TEST PLANTS EXACTLY THAT AND DROPS THE COMMAND. ``+sep_otbn_cmd_drop``
holds ``reg2hw.cmd.qe`` low so OTBN ignores every command while staying powered,
idle and error-free, and ``forge_pkcs1_signature()`` writes the block into both
slots. Against the ROM this testcase was written for, the run must refuse the
image; against the ROM before the fix, it boots it.

WHY THE FAULT IS WORTH INJECTING AT ALL, given it is a glitch in the abstract.
Strip the attacker out and the same state arrives by accident: clock or reset
mis-sequencing, an unseeded entropy chain, a block wedged during bring-up. Any
of those produce ``MANIFEST_OK`` on an unverified image, which is a false pass in
the one property the ROM exists to provide.

WHAT THE ROM MUST DO, and which layer is expected to catch it (SEP-ROM-SB-120).
``otbn_execute()`` clears ``INTR_STATE.done`` before writing ``CMD`` and requires
it afterwards, so it returns ``OTBN_ERR_NOT_STARTED`` and ``rsa_3072_verify()``
prints ``OTBN_NOT_STARTED`` then ``RSA_EXEC_FAIL``. ``rsa_verify.c`` carries a
second, independent refusal for the same condition -- the result buffer being
bit-identical to the signature it wrote (``RSA_INOUT_UNCHANGED``) -- which this
run does NOT reach, because the first layer returns before the read. It is not
forbidden below: reaching it would mean the done bit lied, and refusing there is
still correct. Only ``RSA_VERIFY_OK`` is forbidden, because that is the bypass.

The signature sits outside the signed region, so the manifest hash still matches
and the run reaches signature verification rather than being refused earlier by
a structural check -- the same reason ``flip_signature_byte()`` needs no rehash.

Both slots are forged, so the backup cannot rescue the boot and the run ends
terminal. ``SepBootScoreboard`` is not used: it requires ``fw_done`` with
``fw_pass``, and the expected outcome is ``fw_done`` with ``fw_pass == 0``.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import cocotb
import pyuvm
from cocotb.triggers import RisingEdge
from env import sep_manifest_mutate as mm
from env.sep_efuse_image import LC_TEST_DEV, SepEfuseImage
from env.sep_esrc_noise import esrc_noise_task
from env.sep_rom_console import log_scratch_cold, rom_console_task
from env.sep_verdict import decode_verdict
from sep_base_test import sep_base_test
from sep_reg_meta import sym

_SEP_ROOT = str(Path(__file__).resolve().parents[4])
_FW_DIR = os.path.join(_SEP_ROOT, "bootrom", "prod", "build_ot")
_SECURE_FLASH_IMAGE = os.path.join(_SEP_ROOT, "bootrom", "prod", "build", "oca_secure_boot.bin")
_ROM_BASE = sym("SEP_BOOT_ROM_MEM_BASE_ADDR")

# Must appear: the ROM reached the verifier, and the verifier refused because
# the block never started.
_RSA_EXEC = "RSA_EXEC"
_OTBN_NOT_STARTED = "OTBN_NOT_STARTED"
_RSA_EXEC_FAIL = "RSA_EXEC_FAIL"

# Must NOT appear: the signature was accepted. This single marker is the bypass.
_RSA_VERIFY_OK = "RSA_VERIFY_OK"
# Must NOT appear: the ROM went on to trust the manifest or hand off to BL1.
_DOWNSTREAM_MARKERS = ("MANIFEST_OK", "BL1_COPIED", "PRE_JUMP", "BL1_JUMP=")
# Must NOT appear: secure boot was skipped, so the verifier under test was never
# the thing deciding this boot.
_SBOOT_OFF = "SBOOT_OFF"

# Two slots, each refused before any modexp runs, so no RSA arithmetic happens
# at all -- but the ROM self-hash, both manifest hashes and the payload hashing
# still do. Same budget as the other two-slot terminal testcases.
_MAX_RUN_CYCLES = 24_000_000
_PROGRESS_EVERY = 500_000
_QUIESCE_CYCLES = 20_000


@pyuvm.test()
class sep_otbn_no_op_bypass_test(sep_base_test):
    """Forge a PKCS#1 block, drop OTBN's command, require the boot to refuse it."""

    build_env = False
    rom_build_dir = _FW_DIR
    flash_image = _SECURE_FLASH_IMAGE

    def mutate_flash_image(self, buf: bytearray) -> bytearray:
        """Plant the self-verifying signature in both slots."""
        for slot in ("primary", "backup"):
            block = mm.forge_pkcs1_signature(buf, slot)
            base = mm.slot_base(slot)
            digest = bytes(mm.manifest_hash_field(buf, base)[:32])
            # Show the planted block is the structure the ROM checks for, not
            # merely "some bytes we changed". Without this the test could pass
            # against a ROM that rejects the image for an unrelated reason.
            # 19 B of DigestInfo and the 32 B digest trail the 0x00 separator,
            # so the separator is at [-52] and DigestInfo occupies [-51:-32].
            assert block[:2] == b"\x00\x01", f"{slot}: PKCS#1 header not planted"
            assert block[-32:] == digest, f"{slot}: block does not carry the manifest hash"
            assert block[-52] == 0x00, f"{slot}: missing the DigestInfo separator"
            assert block[-51:-32] == bytes.fromhex("3031300d060960864801650304020105000420"), (
                f"{slot}: DigestInfo is not the SHA-256 OID the ROM checks for"
            )
            assert all(b == 0xFF for b in block[2:-52]), f"{slot}: padding is not all 0xFF"
            self.logger.info(
                "CHK-FORGERY PASS: %s signature replaced with a %d B PKCS#1 v1.5 "
                "block over manifest_hash=%s...",
                slot,
                len(block),
                digest[:8].hex(),
            )
        return buf

    async def run_scenario(self) -> None:
        dut = cocotb.top
        from ocah_spi_vip import OcahSpiFlash

        # The signature path calls ENTROPY_PREREQ() before OTBN, so the ROM
        # brings the real ESRC -> CSRNG -> EDN chain up; the ring oscillators do
        # not self-oscillate in simulation and the health test would stop the
        # boot before the verifier this testcase is about.
        cocotb.start_soon(esrc_noise_task(dut, logger=self.logger))

        # Guard the stimulus. Without the plusarg OTBN executes normally, the
        # forged signature fails the real modexp, and the run would end terminal
        # for a completely different reason while still looking green.
        assert cocotb.plusargs.get("sep_otbn_cmd_drop") is not None, (
            "+sep_otbn_cmd_drop is not set: OTBN would execute, and this testcase "
            "would prove nothing about a command that never landed"
        )

        # TEST_DEV, built explicitly rather than through select_efuse_image():
        # no preload plusarg is passed, and the fallback there is a seeded random
        # image. Secure boot is in force regardless of lifecycle because the
        # packed manifest sets secure_boot_control, which is what lets this
        # testcase reach the verifier without a PROD preload.
        efuse_img = SepEfuseImage()
        efuse_img.set_lc_state(LC_TEST_DEV)
        self.write_efuse_image(efuse_img)

        console: list[str] = []
        cocotb.start_soon(rom_console_task(self.logger, sink=console))

        for src, dst in (
            (os.path.join(self.rom_build_dir, "boot_rom.itcm.hex"), "sep_itcm.hex"),
            (os.path.join(self.rom_build_dir, "boot_rom.dtcm.hex"), "sep_dtcm.hex"),
        ):
            if not os.path.isfile(src):
                raise FileNotFoundError(f"ROM image not found: {src}")
            shutil.copyfile(src, os.path.join(os.getcwd(), dst))

        async def _load_tcm() -> None:
            dut.tcm_load_i.value = 1
            await RisingEdge(dut.clk_i)
            await RisingEdge(dut.clk_i)
            dut.tcm_load_i.value = 0

        with open(self.flash_image, "rb") as fh:
            img = bytearray(fh.read())
        flash = OcahSpiFlash(
            dut.spi_cs_n_o,
            dut.spi_sck_o,
            mosi=dut.spi_mosi_o,
            miso=dut.spi_miso_i,
            name="sep_otbn_no_op_flash",
        )
        flash.preload(bytes(self.mutate_flash_image(img)))
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
            await self.bring_up_cpu_boot(
                _ROM_BASE >> 1,
                pre_reset_hook=_load_tcm,
                run_pulse_cycles=40,
            )
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
                        "ROM signalled completion at cycle %d, pass=%d", cycle, fw_pass
                    )
                    break
                if cycle - last_log >= _PROGRESS_EVERY:
                    last_log = cycle
                    self.logger.info(
                        "otbn no-op poll cyc=%d status=0x%08x retired=%d lines=%d",
                        cycle,
                        status,
                        retired,
                        len(console),
                    )

            if fw_done:
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
            log_scratch_cold(self.logger)

        status_hex = [hex(v) for v in status_seq]
        self.logger.info("cold_scratch[1] sequence: %s", status_hex)
        self.logger.info("ROM console: %s", console)

        assert retired, "core retired no instructions; the ROM never ran"

        # CHK-OTBN-REACHED: the ROM got as far as asking OTBN to run. Without
        # this the refusal below could be any earlier rejection, and the
        # verifier would be untested.
        assert any(_RSA_EXEC in line for line in console), (
            f"ROM never printed {_RSA_EXEC}: it never reached the modexp, so this "
            f"run says nothing about an OTBN that did not start. Console: {console}"
        )
        assert not any(_SBOOT_OFF in line for line in console), (
            f"ROM printed {_SBOOT_OFF}: secure boot was skipped, so the signature "
            f"was never going to be checked. Console: {console}"
        )
        self.logger.info("CHK-OTBN-REACHED PASS: %s emitted, secure boot in force", _RSA_EXEC)

        # CHK-OTBN-NOT-STARTED: the driver noticed the command never landed.
        # STATUS and ERR_BITS cannot show this; INTR_STATE.done is the only
        # signal that separates "finished" from "never ran".
        assert any(_OTBN_NOT_STARTED in line for line in console), (
            f"ROM never printed {_OTBN_NOT_STARTED}: otbn_execute() accepted a "
            f"command OTBN never ran. Console: {console}"
        )
        assert any(_RSA_EXEC_FAIL in line for line in console), (
            f"ROM never printed {_RSA_EXEC_FAIL}: the failed execution did not "
            f"propagate out of rsa_3072_verify(). Console: {console}"
        )
        self.logger.info("CHK-OTBN-NOT-STARTED PASS: %s then %s", _OTBN_NOT_STARTED, _RSA_EXEC_FAIL)

        # CHK-OTBN-NO-BYPASS: the whole point. A forged PKCS#1 block sat in the
        # shared inout buffer and the ROM did not report it as a verified
        # signature.
        assert not any(_RSA_VERIFY_OK in line for line in console), (
            f"ROM printed {_RSA_VERIFY_OK} with OTBN commands dropped: it verified "
            f"the attacker's own bytes against themselves. Console: {console}"
        )
        for marker in _DOWNSTREAM_MARKERS:
            assert not any(marker in line for line in console), (
                f"ROM printed {marker}: it trusted a manifest whose signature was "
                f"never checked. Console: {console}"
            )
        self.logger.info(
            "CHK-OTBN-NO-BYPASS PASS: no %s, none of %s",
            _RSA_VERIFY_OK,
            ", ".join(_DOWNSTREAM_MARKERS),
        )

        # CHK-OTBN-TERMINAL: both slots refused, and the ROM stopped.
        assert fw_done, (
            f"ROM never signalled completion within {_MAX_RUN_CYCLES} cycles; "
            f"cold_scratch[1] observed {status_hex}"
        )
        assert not fw_pass, "ROM signalled PASS on an image whose signature was never verified"
        assert not post_status_moved, (
            "cold_scratch[1] moved on after the terminal verdict, so the ROM "
            "reported the failure and then continued"
        )
        assert not post_console, f"ROM kept printing after the verdict: {post_console}"
        self.logger.info(
            "CHK-OTBN-TERMINAL PASS: mailbox FAIL (fw_pass=0), quiet for %d cycles",
            _QUIESCE_CYCLES,
        )
