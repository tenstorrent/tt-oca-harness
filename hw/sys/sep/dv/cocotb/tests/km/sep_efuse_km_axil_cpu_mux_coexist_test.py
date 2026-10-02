# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP dual-CPU eFuse AXI-lite mux coexistence test (PyUVM).

Two REAL CPUs contend at the SEP eFuse AXI-lite mux ``u_km_efuse_axi_lite_mux``:

  * the VeeR EL2 host boots ``km_efuse_coexist`` firmware: it senses CHIPLET_UID,
    releases the Key Manager (KM) from warm reset, handshakes with it over the
    KM<->SEP mailbox, then loops host CHIPLET_UID reads (integrity) plus KM-owned
    MMR reads (tag/ordering/monotonicity) while the KM contends; and
  * the KM PicoRV32 boots ``km_rom_coexist`` (the ``+km_rom_hex`` image) and
    free-runs eFuse MMR writes through the same mux.

Two independent verdicts are required:
  1. the EL2 firmware self-check (``fw_pass`` via the PASS/FAIL magic + banner,
     gated by ``SepBootScoreboard``); and
  2. an independent passive observer that backdoor-reads the SEP scratch-cold
     registers (the EL2 publishes its measured summary there). The scratch words
     are surfaced as the tb_top probe
     ``scratch_cold_probe_o`` (cocotb runs no AXI master while the EL2 owns the
     LSU bus). Plus the base test's automatic post-sense shadow compare proves the
     sensed CHIPLET_UID actually equals the staged image (0xDEADBEEF).

Delta vs the reference suite: its observer deposits a UVM_DONE marker to release a
waiting host loop; cocotb cannot deposit an internal register without a force
port, so here the host loop is a FIXED contended window and the observer is
read-only. Mutual non-starvation is proven by the host completing all
CONTENDED_LOOPS (final COUNT) AND the KM making progress (CHANGES > 0) in the same
window.
"""

from __future__ import annotations

import os
from pathlib import Path

import cocotb
import pyuvm
from env.sep_boot_scoreboard import SepBootScoreboard
from sep_base_test import sep_base_test
from sep_reg_meta import sym

_DV_ROOT = str(Path(__file__).resolve().parents[3])
_FW_DIR = os.path.join(_DV_ROOT, "fw", "build", "tests", "km_efuse_coexist")
_ITCM_HEX = os.path.join(_FW_DIR, "km_efuse_coexist.itcm.hex")
_DTCM_HEX = os.path.join(_FW_DIR, "km_efuse_coexist.dtcm.hex")
_KM_ROM_HEX = os.path.join(_DV_ROOT, "cocotb", "tests", "km_rom_coexist.parhex")

_ICCM_BASE = sym("SEP_ICCM_MEM_BASE_ADDR")
# Real fuse-sense + EL2 boot + the dual-CPU contended window; the run loop
# early-exits on fw_done, so this is an upper bound only.
_MAX_RUN_CYCLES = 6_000_000
_NO_BOOT_CYCLES = 80_000
_PROGRESS_EVERY = 20_000
_BANNER = "SEP KM-eFuse mux coexist test"

# Golden CHIPLET_UID word0 the host firmware integrity-checks (KNOWN_UID in
# km_efuse_coexist.c). The image carries it; the responder senses it.
_CHIPLET_UID_GOLDEN = 0xDEAD_BEEF
# Pin LC to a normal operational state for a deterministic, ungated run.
_LC_PROD = 0x1

# Scratch-cold word layout the EL2 firmware publishes (MUST match
# km_efuse_coexist.c). The observer reads these back via scratch_cold_probe_o.
_SCRATCH_READY = 0
_SCRATCH_COUNT = 2
_SCRATCH_BAD_UID = 3
_SCRATCH_CHANGES = 4
_SCRATCH_BACKWARD = 5
_SCRATCH_BAD_TAG = 6
_CPU_READY_MARKER = 0xE905_0001
# Must match CONTENDED_LOOPS in km_efuse_coexist.c (full completion = the host was
# not starved by the KM at the mux).
_CONTENDED_LOOPS = 512


@pyuvm.test()
class sep_efuse_km_axil_cpu_mux_coexist_test(sep_base_test):
    """Boot the EL2 host + KM and verify they coexist at the eFuse mux."""

    build_env = False

    def build_phase(self) -> None:
        super().build_phase()
        self.sb = SepBootScoreboard("sb", self)

    def _scratch(self, probe: int, idx: int) -> int:
        """Slice scratch-cold word ``idx`` (32b) out of the 256b probe."""
        return (probe >> (32 * idx)) & 0xFFFF_FFFF

    async def run_scenario(self) -> None:
        # Stage a real fuse image carrying the golden CHIPLET_UID so the host
        # read path integrity-check is meaningful. The base test auto-compares the
        # sensed shadow against this image after sense-done (independent proof the
        # sensed CHIPLET_UID == 0xDEADBEEF before the firmware ever reads it).
        image = self.select_efuse_image(lc_raw=_LC_PROD, fixed={"CHIPLET_UID": _CHIPLET_UID_GOLDEN})
        chiplet_uid_addr, chiplet_uid_word0 = image.expected_field("CHIPLET_UID")[0]
        self.logger.info(
            "coexist eFuse image: CHIPLET_UID[0] @ 0x%08x = 0x%08x",
            chiplet_uid_addr,
            chiplet_uid_word0,
        )
        assert chiplet_uid_word0 == _CHIPLET_UID_GOLDEN, (
            f"staged CHIPLET_UID[0]=0x{chiplet_uid_word0:08x}, expected 0x{_CHIPLET_UID_GOLDEN:08x}"
        )
        self.write_efuse_image(image)

        # Boot the EL2 (it releases + handshakes the KM, which boots from the
        # +km_rom_hex responder). fw_pass + banner are gated by SepBootScoreboard.
        assert os.path.exists(_KM_ROM_HEX), (
            f"missing KM ROM image {_KM_ROM_HEX}; run `make -C hw/sys/sep/dv/cocotb/tests/km_fw`"
        )
        self.logger.info("coexist KM ROM image: %s", _KM_ROM_HEX)
        self.sb.expected_line = _BANNER
        await self.boot_firmware(
            self.sb,
            _ITCM_HEX,
            _DTCM_HEX,
            rst_vec=_ICCM_BASE >> 1,
            max_run_cycles=_MAX_RUN_CYCLES,
            no_boot_cycles=_NO_BOOT_CYCLES,
            progress_every=_PROGRESS_EVERY,
        )

        # Independent passive observer: read the EL2-published summary out of the
        # scratch-cold probe and assert the coexistence verdict directly, rather
        # than relying only on the firmware's PASS magic.
        lanes = 0
        for idx in (
            _SCRATCH_READY,
            _SCRATCH_COUNT,
            _SCRATCH_BAD_UID,
            _SCRATCH_CHANGES,
            _SCRATCH_BACKWARD,
            _SCRATCH_BAD_TAG,
        ):
            lanes |= 0xFFFF_FFFF << (32 * idx)
        probe = self.rd(cocotb.top.scratch_cold_probe_o, mask=lanes)
        ready = self._scratch(probe, _SCRATCH_READY)
        count = self._scratch(probe, _SCRATCH_COUNT)
        bad_uid = self._scratch(probe, _SCRATCH_BAD_UID)
        changes = self._scratch(probe, _SCRATCH_CHANGES)
        backward = self._scratch(probe, _SCRATCH_BACKWARD)
        bad_tag = self._scratch(probe, _SCRATCH_BAD_TAG)
        self.logger.info(
            "coexist observer: ready=0x%08x count=%d changes=%d bad_uid=%d backward=%d bad_tag=%d",
            ready,
            count,
            changes,
            bad_uid,
            backward,
            bad_tag,
        )

        assert ready == _CPU_READY_MARKER, (
            f"EL2/KM handshake never completed (READY=0x{ready:08x} != "
            f"0x{_CPU_READY_MARKER:08x}) -- both CPUs did not come up at the mux"
        )
        assert count == _CONTENDED_LOOPS, (
            f"EL2 host did not complete the contended window "
            f"(COUNT={count} != {_CONTENDED_LOOPS}) -- possible starvation"
        )
        # A floor, not just non-zero: a mux that starved the Key Manager down to a
        # single write across 512 host iterations would otherwise pass. Half is well
        # under the ~511 a healthy run records.
        assert changes >= _CONTENDED_LOOPS // 2, (
            f"KM progress starved: {changes} payload changes across "
            f"{_CONTENDED_LOOPS} host iterations (expected >= {_CONTENDED_LOOPS // 2})"
        )
        assert bad_uid == 0, f"{bad_uid} corrupted host CHIPLET_UID reads under KM contention"
        assert backward == 0, f"KM counter went backward {backward} times (torn/stale mux response)"
        assert bad_tag == 0, (
            f"{bad_tag} KM MMR tag/ordering failures (cross-attribution at the mux)"
        )
        self.logger.info(
            "CHK-COEXIST PASS: both CPUs contended at the eFuse mux, host "
            "data uncorrupted, KM progress monotonic and correctly attributed"
        )
