# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A JTAG-facing eFuse shadow write made during the boot stall reaches the production ROM.

One simulation, three cold resets on one TEST_DEV OTP image and one signed SPI image. The
image binds both manifest slots to the fused ``SEP_SIP_ID`` value A through the package
identity constraint (all 32 bytes selected). The control boot senses A and boots BL1. The
override boot holds ``ext_boot_seq_done_i`` low, waits for fuse sense, writes word 0 of the
``SEP_SIP_ID`` shadow through the JTAG AXI-Lite port and reads it back, then releases the
stall; the ROM must refuse both slots with ``OCA_FAIL_PACKAGE_ID`` and halt. A third cold
reset re-senses the OTP and the word reads A again.

Scope: the ``axil_sep_otp_jtag_req_i`` port to the shadow map to the production ROM; the
JTAG TAP, DTP and JTAG2AXI bridge are not part of this leaf.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ReadOnly, RisingEdge
from env import sep_manifest_mutate as mm
from env import sep_oca_console as oc
from env.sep_efuse_image import LC_TEST_DEV, SepEfuseImage
from env.sep_esrc_noise import esrc_noise_task
from env.sep_rom_console import log_scratch_cold, rom_console_task
from env.sep_verdict import decode_verdict
from ocah_spi_vip import OcahSpiFlash
from rom_fw.sep_rom_ot_dma_boot_test import SECURE_FLASH_IMAGE
from sep_base_test import sep_base_test
from sep_reg_meta import sym

_ROM_BASE = sym("SEP_BOOT_ROM_MEM_BASE_ADDR")
_ROM_END = _ROM_BASE + sym("SEP_BOOT_ROM_MEM_SIZE")
_SIP = SepEfuseImage.field("SEP_SIP_ID")
# Distinct bytes, none 0 or the manifest's unused byte; word 0 bit 0 is 1, so the override
# clears a bit and a set-only shadow would not pass the read-back.
_SIP_ID_A = bytes(range(0x11, 0x31))
_SLOTS = ("primary", "backup")

_OKAY = 0
_SLVERR = 2
_ERR_PACKAGE_ID = mm.boot_err("OCA_FAIL_PACKAGE_ID")
_STATUS_PACKAGE_ID = mm.rom_status_word("ERROR", mm.rom_status_name_for_result(_ERR_PACKAGE_ID))
_ERR_LINE = f"MANIFEST_ERR=0x{_ERR_PACKAGE_ID:08x}"
_SRCS = [mm.PRIMARY_MANIFEST_OFFSET, mm.BACKUP_MANIFEST_OFFSET]

_CONTROL_ORDER = (
    "OCA_BODY=",
    "MFST_VER=",
    "PUBK_AUTHORIZED",
    "RSA_VERIFY_OK",
    "MANIFEST_OK",
    "PAYLOAD_OK",
    "BL1_COPIED",
    "BL1_JUMP=",
    "PRE_JUMP",
)
# Key selection and the signature run after the identity check, so a refused slot prints none.
_PAST_IDENTITY = ("PUBK_SEL=", "PUBK_AUTHORIZED", "PUBK_REVOKE=", "FUSE_VER=", "RSA_EXEC")
_NO_BOOT = (
    "MANIFEST_OK",
    "PAYLOAD_OK",
    "BL1_COPIED",
    "BL1_JUMP=",
    "PRE_JUMP",
    "SBOOT_OFF",
    "BL0S@",
)

_MAX_RUN_CYCLES = 24_000_000
_NO_BOOT_CYCLES = 200_000
_PROGRESS_EVERY = 200_000
_QUIESCE_CYCLES = 20_000
# Environment bound on the sep_reset_n rise after the stall release (two-flop synchronizer).
_RELEASE_BOUND = 1_000


def _identity_mask() -> int:
    mask = 0
    for i in range(mm.IDENTITY_LEN):
        mask |= mm.selector_mask("package", i)
    return mask


@pyuvm.test()
class sep_boot_stall_efuse_shadow_override_test(sep_base_test):
    """Control boot on A, JTAG shadow override during the stall, re-sense restores A."""

    build_env = False
    verdict_source = "scratch0"
    required_evidence = (
        "CHK-EFUSE-OVERRIDE-CONTROL",
        "CHK-EFUSE-OVERRIDE-HELD",
        "CHK-EFUSE-OVERRIDE-SENSED",
        "CHK-EFUSE-OVERRIDE-WRITE",
        "CHK-EFUSE-OVERRIDE-ROM-USED",
        "CHK-EFUSE-OVERRIDE-NO-OTP-BURN",
    )

    # --- stimulus ----------------------------------------------------------
    def _efuse_image(self) -> SepEfuseImage:
        image = SepEfuseImage()
        image.set_lc_state(LC_TEST_DEV)
        image.set_int("SEP_SIP_ID", int.from_bytes(_SIP_ID_A, "little"))
        assert image.field_int("LOCKS") == 0 and image.field_int("LOCKS_SPARE") == 0, (
            "the image locks a field; SEP_SIP_ID must stay writable over JTAG"
        )
        return image

    def _flash_image(self) -> bytes:
        self.log_image_identity("flash", SECURE_FLASH_IMAGE)
        with open(SECURE_FLASH_IMAGE, "rb") as fh:
            buf = bytearray(fh.read())
        mask = _identity_mask()
        for slot in _SLOTS:
            assert mm.selector_bits(buf, slot) == mm.SHIPPED_SELECTOR_BITS, (
                f"{slot} already selects a usage constraint; rebuild the shipped image"
            )
            mm.set_identity(buf, slot, "package", _SIP_ID_A, mask)
            got = mm.identity(buf, slot, "package")
            assert mm.selector_bits(buf, slot) == mask and got == _SIP_ID_A, (
                f"{slot} package identity reads {got.hex()} with selector "
                f"0x{mm.selector_bits(buf, slot):x}; set_identity did not plant A"
            )
            self.logger.info("STIMULUS-IDENTITY: %s", mm.describe(buf, slot))
        return bytes(buf)

    # --- probes ------------------------------------------------------------
    def _levels(self) -> dict[str, int]:
        dut = cocotb.top
        return {
            "rst": self.rd(dut.rst_ni),
            "sense": self.rd(dut.sep_fuse_sense_done_o),
            "sep_rst": self.rd(dut.dbg_sep_reset_n_o),
            "cpu_rst": self.rd(dut.sep_cpu_reset_n_o),
            "ext": self.rd(dut.ext_boot_seq_done_i),
        }

    async def _watch_hold(self) -> dict:
        """Sample the reset taps, cold scratch and the trace port from the rst_ni release to the
        sep_reset_n rise."""
        dut = cocotb.top
        held = sensed = 0
        bad: list[tuple[int, int, int, int]] = []
        scratch: list[int] = []
        released = None
        while True:
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            lv = self._levels()
            retire = self.rd(dut.cpu_trace_valid_o)
            if not lv["ext"]:
                if lv["rst"]:
                    held += 1
                    sensed += lv["sense"]
                    if lv["sep_rst"] or lv["cpu_rst"] or retire:
                        bad.append((held, lv["sep_rst"], lv["cpu_rst"], retire))
                    probe = self.rd(dut.scratch_cold_probe_o)
                    if probe:
                        scratch.append(probe)
                continue
            released = 0 if released is None else released + 1
            if lv["sep_rst"] or released >= _RELEASE_BOUND:
                return {
                    "held": held,
                    "sensed": sensed,
                    "bad": bad,
                    "scratch": scratch,
                    "rise": released if lv["sep_rst"] else None,
                }

    async def _presense_read(self) -> dict:
        """One JTAG read of the SEP_SIP_ID word, issued one clock after the rst_ni release."""
        dut = cocotb.top
        await RisingEdge(dut.clk_i)
        while not self.rd(dut.rst_ni):
            await RisingEdge(dut.clk_i)
        issue = self.rd(dut.sep_fuse_sense_done_o)
        resp, data = await self.jtag_axil_op(write=False, addr=_SIP.shadow_addr)
        return {
            "resp": resp,
            "data": data,
            "issue": issue,
            "at_resp": self.rd(dut.sep_fuse_sense_done_o),
        }

    async def _held_cold_reset(self):
        """Cold reset with ext_boot_seq_done_i low; returns once fuse sense is done."""
        dut = cocotb.top
        await RisingEdge(dut.clk_i)
        watch = cocotb.start_soon(self._watch_hold())
        probe = cocotb.start_soon(self._presense_read())
        dut.ext_boot_seq_done_i.value = 0
        await self.resense()
        return watch, await probe

    async def _run_rom(self, console: list[str], *, quiesce: bool) -> dict:
        """Poll cold_scratch until the verdict; with ``quiesce``, watch the halt afterwards."""
        dut = cocotb.top
        status_seq: list[int] = []
        last_status = None
        first_pc = None
        outside: list[int] = []
        retired = 0
        verdict = None

        def sample() -> int:
            nonlocal last_status, first_pc, retired
            probe = self.rd(dut.scratch_cold_probe_o)
            status = (probe >> 32) & 0xFFFF_FFFF
            if status != last_status:
                last_status = status
                status_seq.append(status)
            if self.rd(dut.cpu_trace_valid_o):
                pc = self.rd(dut.cpu_trace_addr_o) & 0xFFFF_FFFF
                retired += 1
                if first_pc is None:
                    first_pc = pc
                if not _ROM_BASE <= pc < _ROM_END:
                    outside.append(pc)
            return probe

        for cycle in range(_MAX_RUN_CYCLES):
            await RisingEdge(dut.clk_i)
            verdict = decode_verdict(sample())
            if verdict is not None:
                self.logger.info(
                    "CHK-VERDICT: cold_scratch[0] verdict at cycle %d pass=%d", cycle, verdict[1]
                )
                break
            assert retired or cycle < _NO_BOOT_CYCLES, (
                f"the core retired nothing in {_NO_BOOT_CYCLES} cycles; the ROM never ran"
            )
            if cycle and cycle % _PROGRESS_EVERY == 0:
                self.logger.info(
                    "rom poll cyc=%d status=0x%08x retired=%d lines=%d",
                    cycle,
                    last_status,
                    retired,
                    len(console),
                )
        assert verdict is not None, (
            f"no verdict in cold_scratch[0] within {_MAX_RUN_CYCLES} cycles; "
            f"cold_scratch[1] sequence {[hex(v) for v in status_seq]}"
        )
        run = {
            "verdict": verdict[1],
            "status_seq": status_seq,
            "first_pc": first_pc,
            "retired": retired,
            "terminal": last_status,
            "lines_at_verdict": len(console),
        }
        if quiesce:
            moved = False
            for _ in range(_QUIESCE_CYCLES):
                await RisingEdge(dut.clk_i)
                sample()
                moved |= last_status != run["terminal"]
            run.update(moved=moved, late_lines=console[run["lines_at_verdict"] :])
        run["outside"] = outside
        return run

    # --- grading -----------------------------------------------------------
    def _grade_control(self, console: list[str], run: dict) -> None:
        attempts = oc.split_attempts(console)
        assert [a.src for a in attempts] == [mm.PRIMARY_MANIFEST_OFFSET], (
            f"control boot read slots {[hex(a.src) for a in attempts]}, expected the primary "
            f"only: the identity bound to A was refused. Console: {console}"
        )
        oc.assert_attempt(attempts[0], error=None, stage="accepted", ordered=_CONTROL_ORDER)
        assert oc.count(console, "BOOT_SPI") and not oc.count(console, "SBOOT_OFF"), (
            f"control boot did not take the enforced SPI secure-boot path. Console: {console}"
        )
        assert run["verdict"] == 1, (
            f"control boot verdict FAIL with the sensed SEP_SIP_ID equal to the manifest "
            f"identity; cold_scratch[1] {[hex(v) for v in run['status_seq']]}"
        )
        self.logger.info(
            "CHK-EFUSE-OVERRIDE-CONTROL PASS: sensed SEP_SIP_ID=%s, primary accepted after %s, "
            "BL1 verdict PASS",
            _SIP_ID_A.hex(),
            " -> ".join(_CONTROL_ORDER),
        )

    def _grade_override(self, console: list[str], run: dict, control_verdict: int) -> None:
        assert run["first_pc"] == _ROM_BASE, (
            f"first retirement after the stall release is "
            f"{run['first_pc'] and hex(run['first_pc'])}, expected the boot ROM reset vector "
            f"0x{_ROM_BASE:08x}"
        )
        attempts = oc.split_attempts(console)
        assert [a.src for a in attempts] == _SRCS, (
            f"override boot read slots {[hex(a.src) for a in attempts]}, expected "
            f"{[hex(s) for s in _SRCS]}. Console: {console}"
        )
        for att in attempts:
            oc.assert_attempt(
                att,
                error=_ERR_PACKAGE_ID,
                stage="manifest",
                ordered=("OCA_BODY=", "MFST_VER=", _ERR_LINE),
                absent=_PAST_IDENTITY,
            )
        i_all = [i for i, line in enumerate(console) if oc.count([line], "MANIFEST_ALL_FAILED")]
        assert len(i_all) == 1 and i_all[0] > attempts[-1].last, (
            f"MANIFEST_ALL_FAILED@{i_all} is not once after the backup refusal. Console: {console}"
        )
        printed = [m for m in _NO_BOOT if oc.count(console, m)]
        assert not printed, f"override boot printed {printed} after refusing both slots"
        assert _STATUS_PACKAGE_ID in run["status_seq"], (
            f"cold_scratch[1] never held 0x{_STATUS_PACKAGE_ID:08x} (ERROR "
            f"SEP_MSG_INVALID_PACKAGE_ID); sequence {[hex(v) for v in run['status_seq']]}"
        )
        assert run["verdict"] == 0 and control_verdict == 1, (
            f"override verdict pass={run['verdict']} against control pass={control_verdict}: "
            "the ROM did not use the overridden shadow word"
        )
        assert not run["moved"] and not run["late_lines"], (
            f"ROM kept running after the FAIL verdict: status moved={run['moved']} "
            f"console={run['late_lines']}"
        )
        assert not run["outside"], (
            f"override boot retired PCs outside the boot ROM: "
            f"{[hex(p) for p in run['outside'][:8]]}"
        )
        self.logger.info(
            "CHK-EFUSE-OVERRIDE-ROM-USED PASS: first_pc=0x%08x; primary and backup refused %s "
            "after OCA_BODY= and MFST_VER=, none of %s; MANIFEST_ALL_FAILED; cold_scratch[1] "
            "held 0x%08x; verdict FAIL (control PASS); halted at 0x%08x for %d cycles with "
            "every retired PC (%d) in the boot ROM",
            run["first_pc"],
            _ERR_LINE,
            ", ".join(_PAST_IDENTITY),
            _STATUS_PACKAGE_ID,
            run["terminal"],
            _QUIESCE_CYCLES,
            run["retired"],
        )

    # --- scenario ----------------------------------------------------------
    async def run_scenario(self) -> None:
        dut = cocotb.top
        # Without noise the repetition health test fails and the ROM refuses on entropy.
        cocotb.start_soon(esrc_noise_task(dut, logger=self.logger))
        image = self._efuse_image()
        self.write_efuse_image(image)
        a0 = image.words[_SIP.word]
        override = a0 ^ 0x1
        addr = _SIP.shadow_addr

        flash = OcahSpiFlash(
            dut.spi_cs_n_o,
            dut.spi_sck_o,
            mosi=dut.spi_mosi_o,
            miso=dut.spi_miso_i,
            name="sep_override_flash",
        )
        flash.preload(self._flash_image())
        await flash.start()
        try:
            # Control boot.
            console: list[str] = []
            con = cocotb.start_soon(rom_console_task(self.logger, sink=console))
            await self.bring_up_cpu_boot(_ROM_BASE >> 1, run_pulse_cycles=40)
            control = await self._run_rom(console, quiesce=False)
            con.cancel()
            self._grade_control(console, control)

            # Override boot: re-sense under the stall, write and read back the shadow word.
            watch, pre = await self._held_cold_reset()
            rd0_resp, rd0 = await self.jtag_axil_op(write=False, addr=addr)
            at_write = self._levels()
            wr_resp, _ = await self.jtag_axil_op(write=True, addr=addr, wdata=override)
            after_write = self._levels()
            rd1_resp, rd1 = await self.jtag_axil_op(write=False, addr=addr)

            assert pre["at_resp"] == 0, (
                "the pre-sense JTAG read completed after sense done; issue it earlier so it "
                "lands in the pre-sense window"
            )
            assert pre["resp"] == _SLVERR, (
                f"JTAG read of SEP_SIP_ID word 0 before sense done answered resp={pre['resp']}; "
                "the MAP window must answer SLVERR until sensing completes"
            )
            assert at_write["sense"] and after_write["sense"], (
                f"fuse sense done read {at_write['sense']}/{after_write['sense']} around the "
                "shadow write; the write must follow sensing or sensing overwrites it"
            )
            self.logger.info(
                "CHK-EFUSE-OVERRIDE-SENSED PASS: pre-sense JTAG read resp=SLVERR "
                "(done at issue=%d, at response=%d); sense_done=1 before and after the write",
                pre["issue"],
                pre["at_resp"],
            )

            assert rd0_resp == _OKAY and rd0 == a0, (
                f"JTAG read of the sensed SEP_SIP_ID word 0 gave resp={rd0_resp} "
                f"data=0x{rd0:08x}, expected OKAY 0x{a0:08x}"
            )
            assert wr_resp == _OKAY, (
                f"JTAG write of SEP_SIP_ID word 0 in TEST_DEV answered resp={wr_resp}; an "
                "unlocked general shadow field must be writable over JTAG in TEST_DEV"
            )
            assert rd1_resp == _OKAY and rd1 == override, (
                f"JTAG read-back of SEP_SIP_ID word 0 gave resp={rd1_resp} data=0x{rd1:08x}, "
                f"expected OKAY 0x{override:08x}"
            )
            self.logger.info(
                "CHK-EFUSE-OVERRIDE-WRITE PASS: @0x%08x sensed 0x%08x, write 0x%08x resp=OKAY, "
                "read-back 0x%08x resp=OKAY",
                addr,
                rd0,
                override,
                rd1,
            )

            console = []
            con = cocotb.start_soon(rom_console_task(self.logger, sink=console))
            await RisingEdge(dut.clk_i)
            dut.ext_boot_seq_done_i.value = 1
            run = await self._run_rom(console, quiesce=True)
            con.cancel()
            hold = await watch

            write_rst = (at_write["sep_rst"], at_write["cpu_rst"])
            write_rst += (after_write["sep_rst"], after_write["cpu_rst"])
            assert hold["sensed"] and not hold["bad"] and not any(write_rst), (
                f"sep_reset_n/sep_cpu_reset_n/retire left 0 while ext_boot_seq_done_i was low "
                f"after the rst_ni release: {hold['held']} samples, bad {hold['bad'][:8]}, "
                f"levels at the write {write_rst}"
            )
            assert not hold["scratch"], (
                f"cold scratch read 0x{hold['scratch'][0]:064x} in {len(hold['scratch'])} of "
                f"{hold['held']} held samples while sep_reset_n is low; it must stay clear so the "
                "override verdict cannot be the control verdict"
            )
            assert hold["rise"] is not None and run["first_pc"] is not None, (
                f"sep_reset_n did not rise within {_RELEASE_BOUND} clocks of the stall release "
                f"(rise={hold['rise']}) or nothing retired after it"
            )
            self.logger.info(
                "CHK-EFUSE-OVERRIDE-HELD PASS: %d held samples (%d after sense done) with "
                "sep_reset_n=0 sep_cpu_reset_n=0, no retirement and cold scratch 0; control: "
                "sep_reset_n rose %d clocks after ext_boot_seq_done_i and the core retired",
                hold["held"],
                hold["sensed"],
                hold["rise"],
            )
            self._grade_override(console, run, control["verdict"])

            # Final re-sense: the OTP keeps A, so the shadow returns to A.
            watch, _ = await self._held_cold_reset()
            final_resp, final = await self.jtag_axil_op(write=False, addr=addr)
            assert final_resp == _OKAY and final == a0, (
                f"after a re-sense SEP_SIP_ID word 0 reads resp={final_resp} data=0x{final:08x}, "
                f"expected OKAY 0x{a0:08x}: the shadow write reached the OTP"
            )
            self.logger.info(
                "CHK-EFUSE-OVERRIDE-NO-OTP-BURN PASS: re-sensed SEP_SIP_ID word 0=0x%08x "
                "(override was 0x%08x) and the whole shadow matches the staged OTP image",
                final,
                override,
            )
            watch.cancel()
        finally:
            await flash.stop()
            log_scratch_cold(self.logger)
