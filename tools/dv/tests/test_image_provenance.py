# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Unit tests for the image provenance a sim leaf stamps into its log and result.

Run from the repository root:

    python3 -m unittest discover tools/dv/tests
"""

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runlib.stages import _image_provenance, _stamp_provenance  # noqa: E402


class ImageProvenance(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "repo"
        assets = self.root / "hw" / "sys" / "smc" / "dv" / "assets"
        assets.mkdir(parents=True)
        self.rom = assets / "smc_rom_default.hex"
        self.rom.write_bytes(b"@00000000\n00000013\n")
        self.rom_sha = hashlib.sha256(self.rom.read_bytes()).hexdigest()
        self.outside = Path(self._tmp.name) / "fw.itcm.hex"
        self.outside.write_bytes(b"deadbeef\n")
        self.outside_sha = hashlib.sha256(self.outside.read_bytes()).hexdigest()

    def tearDown(self):
        self._tmp.cleanup()

    def rendered_args(self) -> list[str]:
        return [
            "+UVM_TESTNAME=smc_canonical_smoke_test",
            "+ntb_random_seed=7",
            f"+rom_hex={self.rom}",
            f"+sep_itcm_hex={self.outside}",
            "+skip_fuse_sense",
            "+sep_efuse_prog_fail_seed=7",
            f"+smc_scratch_ram_hex={self.root}/hw/sys/smc/dv/assets/missing.hex",
            f"+sep_sym={self.root}/hw/sys/smc/dv/assets",
            "+bare_flag_with_empty_value=",
            "--trace-fst",
        ]

    def test_file_valued_plusargs_are_digested(self):
        images = _image_provenance(self.root, self.rendered_args())
        self.assertEqual(
            images,
            {
                "rom_hex": {
                    "path": "hw/sys/smc/dv/assets/smc_rom_default.hex",
                    "sha256": self.rom_sha,
                },
                "sep_itcm_hex": {"path": str(self.outside), "sha256": self.outside_sha},
            },
        )
        self.assertEqual(len(images["rom_hex"]["sha256"]), 64)

    def test_non_file_plusargs_contribute_nothing(self):
        images = _image_provenance(
            self.root,
            ["+skip_fuse_sense", "+seed=3", "+rom_hex=", "-input", "run.tcl", "+sym=/nonexistent"],
        )
        self.assertEqual(images, {})

    def test_relative_value_resolves_against_sim_cwd_then_root(self):
        cwd = Path(self._tmp.name) / "leaf"
        cwd.mkdir()
        staged = cwd / "smu_sep_smoke.itcm.hex"
        staged.write_bytes(b"01\n")
        images = _image_provenance(
            self.root,
            [
                "+sep_itcm_hex=smu_sep_smoke.itcm.hex",
                "+rom_hex=hw/sys/smc/dv/assets/smc_rom_default.hex",
            ],
            cwd=cwd,
        )
        self.assertEqual(images["sep_itcm_hex"]["path"], str(staged))
        self.assertEqual(images["sep_itcm_hex"]["sha256"], hashlib.sha256(b"01\n").hexdigest())
        self.assertEqual(images["rom_hex"]["path"], "hw/sys/smc/dv/assets/smc_rom_default.hex")

    def test_stamp_writes_provenance_then_one_fw_line_per_image(self):
        log = Path(self._tmp.name) / "sim.log"
        log.write_text("UVM_INFO done\n", encoding="utf-8")
        metadata: dict = {}
        _stamp_provenance(
            self.root,
            log,
            metadata,
            fingerprint="fp123",
            filelist=None,
            dry_run=False,
            sim_args=self.rendered_args(),
        )
        lines = log.read_text(encoding="utf-8").splitlines()
        prov_index = next(i for i, line in enumerate(lines) if line.startswith("PROVENANCE "))
        self.assertIn("build_fingerprint=fp123", lines[prov_index])
        self.assertNotIn("images", lines[prov_index])
        self.assertEqual(
            lines[prov_index + 1 :],
            [
                f"FW-PROVENANCE rom_hex=hw/sys/smc/dv/assets/smc_rom_default.hex sha256={self.rom_sha}",
                f"FW-PROVENANCE sep_itcm_hex={self.outside} sha256={self.outside_sha}",
            ],
        )
        self.assertEqual(
            metadata["provenance"]["images"],
            {
                "rom_hex": {
                    "path": "hw/sys/smc/dv/assets/smc_rom_default.hex",
                    "sha256": self.rom_sha,
                },
                "sep_itcm_hex": {"path": str(self.outside), "sha256": self.outside_sha},
            },
        )

    def test_stamp_without_images_keeps_the_log_to_one_line(self):
        log = Path(self._tmp.name) / "sim.log"
        log.write_text("done\n", encoding="utf-8")
        metadata: dict = {}
        _stamp_provenance(
            self.root,
            log,
            metadata,
            fingerprint=None,
            filelist=None,
            dry_run=False,
            sim_args=["+skip_fuse_sense", "+seed=1"],
        )
        lines = [line for line in log.read_text(encoding="utf-8").splitlines() if line]
        self.assertEqual(lines[0], "done")
        self.assertTrue(lines[1].startswith("PROVENANCE "))
        self.assertEqual(len(lines), 2)
        self.assertEqual(metadata["provenance"]["images"], {})

    def test_dry_run_records_images_without_touching_the_log(self):
        log = Path(self._tmp.name) / "sim.log"
        log.write_text("done\n", encoding="utf-8")
        metadata: dict = {}
        _stamp_provenance(
            self.root,
            log,
            metadata,
            fingerprint=None,
            filelist=None,
            dry_run=True,
            sim_args=[f"+rom_hex={self.rom}"],
        )
        self.assertEqual(log.read_text(encoding="utf-8"), "done\n")
        self.assertEqual(metadata["provenance"]["images"]["rom_hex"]["sha256"], self.rom_sha)


if __name__ == "__main__":
    unittest.main()
