# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Unit tests for the cocotb build fingerprint inputs and the stored build record.

The cocotb runner rebuilds a model only when a listed source is newer than it, and the
native runner lists no sources (they arrive through the filelist), so the runner's own
fingerprint has to notice an edited source, an edited include file, or an edited file-valued
argument, and the record beside the model has to turn that into a clean build.

Run from the repository root:

    python3 -m unittest discover tools/dv/tests
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runlib.stages import (  # noqa: E402
    BUILD_RECORD_NAME,
    _build_record_decision,
    _file_args_fingerprint,
    _filelist_sources,
    _filelist_sources_fingerprint,
    _write_build_record,
)


class FilelistSources(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="ocah-build-record-"))
        (self.root / "rtl").mkdir()
        (self.root / "rtl" / "dut.sv").write_text("module dut; endmodule\n")
        (self.root / "cov").mkdir()
        (self.root / "cov" / "fcov.sv").write_text("module fcov; endmodule\n")
        (self.root / "bender.f").write_text("// bender\nrtl/dut.sv\n")
        (self.root / "compile.f").write_text(
            "+incdir+hw/common/assert\n+define+UVM\n-f bender.f\ncov/fcov.sv\n# note\n"
        )

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_follows_includes_and_skips_options(self):
        sources = _filelist_sources(self.root, self.root / "compile.f")
        self.assertEqual(
            [source.relative_to(self.root).as_posix() for source in sources],
            ["rtl/dut.sv", "cov/fcov.sv"],
        )

    def test_missing_filelist_has_no_sources(self):
        self.assertEqual(_filelist_sources(self.root, self.root / "absent.f"), [])
        self.assertEqual(_filelist_sources_fingerprint(self.root, self.root / "absent.f"), [])

    def test_fingerprint_moves_on_any_named_source_edit(self):
        before = _filelist_sources_fingerprint(self.root, self.root / "compile.f")
        self.assertEqual(len(before), 1)
        self.assertTrue(before[0].startswith("filelist_sources=2:"))
        (self.root / "cov" / "fcov.sv").write_text("module fcov; logic x; endmodule\n")
        after_direct = _filelist_sources_fingerprint(self.root, self.root / "compile.f")
        self.assertNotEqual(before, after_direct)
        (self.root / "rtl" / "dut.sv").write_text("module dut; logic y; endmodule\n")
        after_included = _filelist_sources_fingerprint(self.root, self.root / "compile.f")
        self.assertNotEqual(after_direct, after_included)

    def test_file_args_fingerprint_reads_only_existing_files(self):
        scope = self.root / "scope.hier"
        scope.write_text("-tree top\n+tree top.u_dut\n")
        args = ["-cm", "line+tgl", "-cm_hier", str(scope), "-lca", "+define+X", "not/a/file"]
        before = _file_args_fingerprint(self.root, args)
        self.assertEqual(len(before), 1)
        self.assertTrue(before[0].startswith("file_args=1:"))
        scope.write_text("-tree top\n")
        self.assertNotEqual(before, _file_args_fingerprint(self.root, args))
        self.assertEqual(_file_args_fingerprint(self.root, ["-cm", "line"]), [])


class BuildRecordDecision(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="ocah-build-record-"))
        self.build = self.root / "build"
        self.record = self.build / BUILD_RECORD_NAME

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_requested_rebuild_wins(self):
        self.assertEqual(_build_record_decision(self.record, "fp-one", True), (True, "requested"))

    def test_no_build_dir_needs_no_forcing(self):
        self.assertEqual(_build_record_decision(self.record, "fp-one", False), (False, ""))

    def test_model_without_record_is_rebuilt_once(self):
        self.build.mkdir()
        self.assertEqual(
            _build_record_decision(self.record, "fp-one", False), (True, "no build record")
        )
        _write_build_record(self.record, "fp-one", "vcs X", False)
        self.assertEqual(_build_record_decision(self.record, "fp-one", False), (False, ""))
        payload = json.loads(self.record.read_text())
        self.assertEqual((payload["fingerprint"], payload["tool_version"]), ("fp-one", "vcs X"))
        self.assertIn("written_at", payload)

    def test_changed_inputs_force_a_clean_build(self):
        self.build.mkdir()
        _write_build_record(self.record, "fp-one", "vcs X", False)
        self.assertEqual(
            _build_record_decision(self.record, "fp-two", False), (True, "inputs changed")
        )

    def test_corrupt_record_is_treated_as_missing(self):
        self.build.mkdir()
        self.record.write_text("{not json")
        self.assertEqual(
            _build_record_decision(self.record, "fp-one", False), (True, "no build record")
        )


if __name__ == "__main__":
    unittest.main()
