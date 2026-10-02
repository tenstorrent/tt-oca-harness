# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

import gzip
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fw_coverage.gen_sep_rom_coverage import (  # noqa: E402
    COVERVIEW_REVISION,
    INFO_PROCESS_REVISION,
    RENODE_REVISION,
    CoverageError,
    CoverageTools,
    coverage_cache_path,
    default_output_dir,
    discover_trace_inputs,
    group_trace_inputs,
    load_firmware_modes,
    main,
    prepare_tools,
    render_variant,
    validate_variant_groups,
    write_index,
)
from fw_coverage.renode_trace import RenodeTraceWriter  # noqa: E402


class RenodeTraceWriterTest(unittest.TestCase):
    def test_writes_header_and_unique_little_endian_pcs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "trace.bin.gz"
            with RenodeTraceWriter(path) as trace:
                trace.log_pc(0x1004_1234)
                trace.log_pc(0x1004_1234)
                trace.log_pc(0x1004_5678)
                self.assertEqual(trace.count, 2)

            with gzip.open(path, "rb") as stream:
                self.assertEqual(
                    stream.read(),
                    b"ReTrace\x04\x04\x00\x34\x12\x04\x10\x00\x78\x56\x04\x10\x00",
                )

    def test_rejects_pc_outside_selected_width(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "trace.bin.gz"
            with RenodeTraceWriter(path, pc_width_bytes=2) as trace:
                with self.assertRaisesRegex(ValueError, "does not fit"):
                    trace.log_pc(0x1_0000)


class TraceDiscoveryTest(unittest.TestCase):
    def _write_leaf(
        self,
        run_dir: Path,
        item: str,
        *,
        status: str = "PASS",
        elf: bytes = b"elf",
        valid_trace: bool = True,
        seed: int = 1,
        attempt: int = 0,
        debug_only: bool = False,
    ) -> Path:
        leaf = run_dir / item / f"seed_{seed}" / f"attempt_{attempt}"
        leaf.mkdir(parents=True)
        (leaf / "result.json").write_text(
            json.dumps(
                {
                    "flow": "sep",
                    "item": item,
                    "seed": seed,
                    "attempt": attempt,
                    "status": status,
                    "metadata": {"debug_only": debug_only},
                }
            ),
            encoding="utf-8",
        )
        (leaf / "boot_rom.elf").write_bytes(elf)
        trace = leaf / "sep_rom_pc_trace.bin.gz"
        if valid_trace:
            with RenodeTraceWriter(trace) as writer:
                writer.log_pc(0x1004_0000)
        else:
            trace.write_bytes(b"incomplete")
        return leaf

    def test_maps_testlist_items_to_firmware_modes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            testlist = Path(temp_dir) / "rom_fw.toml"
            testlist.write_text(
                """
[[tests]]
name = "default_test"
firmware = { name = "boot_rom", mode = "boot_rom" }

[[tests]]
name = "ot_test"
firmware = { name = "boot_rom_pio", mode = "boot_rom_pio" }
""",
                encoding="utf-8",
            )
            self.assertEqual(
                load_firmware_modes(testlist),
                {"default_test": "boot_rom", "ot_test": "boot_rom_pio"},
            )

    def test_discovers_flat_single_test_leaf(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir)
            leaf = run_dir / "single"
            leaf.mkdir()
            (leaf / "result.json").write_text(
                json.dumps(
                    {
                        "flow": "sep",
                        "item": "single",
                        "seed": 1,
                        "attempt": 0,
                        "status": "PASS",
                        "metadata": {"debug_only": False},
                    }
                ),
                encoding="utf-8",
            )
            (leaf / "boot_rom.elf").write_bytes(b"elf")
            with RenodeTraceWriter(leaf / "sep_rom_pc_trace.bin.gz") as writer:
                writer.log_pc(0x1004_0000)

            inputs, skipped = discover_trace_inputs(run_dir, {"single": "boot_rom"})

            self.assertEqual([entry.leaf_dir for entry in inputs], [leaf])
            self.assertEqual(skipped, [])

    def test_discovers_only_passing_complete_traces(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir)
            good = self._write_leaf(run_dir, "good")
            self._write_leaf(run_dir, "failed", status="FAIL")
            self._write_leaf(run_dir, "corrupt", valid_trace=False)

            inputs, skipped = discover_trace_inputs(
                run_dir,
                {"good": "boot_rom", "failed": "boot_rom", "corrupt": "boot_rom"},
            )

            self.assertEqual([entry.item for entry in inputs], ["good"])
            self.assertEqual(inputs[0].leaf_dir, good)
            self.assertEqual({entry.item for entry in skipped}, {"failed", "corrupt"})

    def test_skips_trace_with_header_but_no_retired_pc(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir)
            leaf = self._write_leaf(run_dir, "empty")
            with RenodeTraceWriter(leaf / "sep_rom_pc_trace.bin.gz"):
                pass

            inputs, skipped = discover_trace_inputs(run_dir, {"empty": "boot_rom"})

            self.assertEqual(inputs, [])
            self.assertEqual(skipped[0].reason, "trace contains no retired PCs")

    def test_uses_only_final_non_debug_attempt(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir)
            self._write_leaf(run_dir, "retried", status="PASS", attempt=0)
            self._write_leaf(run_dir, "retried", status="FAIL", attempt=1)

            inputs, skipped = discover_trace_inputs(run_dir, {"retried": "boot_rom"})

            self.assertEqual(inputs, [])
            self.assertEqual(len(skipped), 1)
            self.assertEqual(skipped[0].reason, "leaf status is FAIL")

    def test_ignores_later_wave_debug_attempt(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir)
            expected = self._write_leaf(run_dir, "debugged", attempt=0)
            self._write_leaf(run_dir, "debugged", attempt=1, debug_only=True)

            inputs, skipped = discover_trace_inputs(run_dir, {"debugged": "boot_rom"})

            self.assertEqual([entry.leaf_dir for entry in inputs], [expected])
            self.assertEqual(skipped, [])

    def test_malformed_final_attempt_invalidates_earlier_pass(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir)
            self._write_leaf(run_dir, "malformed", attempt=0)
            final_leaf = run_dir / "malformed/seed_1/attempt_1"
            final_leaf.mkdir(parents=True)
            (final_leaf / "result.json").write_text("{", encoding="utf-8")

            inputs, skipped = discover_trace_inputs(run_dir, {"malformed": "boot_rom"})

            self.assertEqual(inputs, [])
            self.assertIn("invalid result.json", skipped[0].reason)

    def test_structurally_invalid_final_attempt_invalidates_earlier_pass(self):
        for payload in ({}, {"item": "structural", "seed": 1, "attempt": 0}):
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as temp_dir:
                run_dir = Path(temp_dir)
                self._write_leaf(run_dir, "structural", attempt=0)
                final_leaf = run_dir / "structural/seed_1/attempt_1"
                final_leaf.mkdir(parents=True)
                (final_leaf / "result.json").write_text(
                    json.dumps(payload),
                    encoding="utf-8",
                )

                inputs, skipped = discover_trace_inputs(run_dir, {"structural": "boot_rom"})

                self.assertEqual(inputs, [])
                self.assertIn("does not match leaf path", skipped[0].reason)

    def test_rejects_different_elfs_within_one_variant(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir)
            self._write_leaf(run_dir, "one", elf=b"elf-one")
            self._write_leaf(run_dir, "two", elf=b"elf-two")
            inputs, _ = discover_trace_inputs(
                run_dir,
                {"one": "boot_rom_pio", "two": "boot_rom_pio"},
            )

            with self.assertRaisesRegex(CoverageError, "different ELF"):
                group_trace_inputs(inputs)


class ReportGenerationTest(unittest.TestCase):
    def test_default_output_is_scoped_by_run_name_under_tool_directory(self):
        root = Path("/work/repo")
        run_dir = Path("/scratch/sep-rom-fw-cov")

        self.assertEqual(
            default_output_dir(root, run_dir),
            root / "tools/dv/fw_coverage/output/sep-rom-fw-cov",
        )

    def test_partial_versioned_tool_cache_retries_npm_install(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_root = Path(temp_dir)
            install = coverage_cache_path(cache_root)
            bin_dir = install / "venv/bin"
            bin_dir.mkdir(parents=True)
            for name in ("python", "pip", "renode-retracer", "info-process"):
                (bin_dir / name).write_text("", encoding="utf-8")
            (install / "execution-tracer.complete").write_text(RENODE_REVISION, encoding="utf-8")
            (install / "info-process.complete").write_text(INFO_PROCESS_REVISION, encoding="utf-8")
            coverview = install / "coverview"
            (coverview / ".git").mkdir(parents=True)
            (coverview / "embed.py").write_text("", encoding="utf-8")
            (coverview / "package-lock.json").write_text("{}", encoding="utf-8")
            (coverview / "node_modules").mkdir()
            (coverview / "node_modules/partial").write_text("", encoding="utf-8")
            commands = []

            def run(command, **kwargs):
                commands.append((command, kwargs))
                if command == ["npm", "ci"]:
                    self.assertFalse((coverview / "node_modules").exists())
                    (coverview / "node_modules").mkdir()
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout=f"{COVERVIEW_REVISION}\n",
                )

            tools = prepare_tools(cache_root, run=run)

            self.assertEqual(tools.coverview, coverview)
            self.assertIn((["npm", "ci"], {"cwd": coverview, "check": True}), commands)

    def test_rejects_missing_selected_firmware_variant(self):
        with self.assertRaisesRegex(CoverageError, "boot_rom_pio"):
            validate_variant_groups(
                {"boot_rom": []},
                {"items": ["default_test", "ot_test"]},
                {"default_test": "boot_rom", "ot_test": "boot_rom_pio"},
            )

    def test_rejects_incomplete_run_before_collecting_traces(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir)
            (run_dir / "result.json").write_text(
                json.dumps(
                    {
                        "flow": "sep",
                        "status": "UNKNOWN",
                        "tests": {"completed": False, "leaves_run": 1, "leaves_planned": 3},
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(CoverageError, "incomplete"):
                main(["--run-dir", str(run_dir)])

    def test_render_variant_runs_retracer_info_process_and_coverview(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            coverview = root / "coverview"
            (coverview / "dist").mkdir(parents=True)
            (coverview / "dist" / "index.html").write_text("report", encoding="utf-8")
            elf = root / "boot_rom.elf"
            elf.write_bytes(b"elf")
            trace_a = root / "a.bin.gz"
            trace_b = root / "b.bin.gz"
            trace_a.write_bytes(b"a")
            trace_b.write_bytes(b"b")
            source = root / "rom_main.c"
            source.write_text("int main(void) {}", encoding="utf-8")
            entries = [
                self._entry("a", "boot_rom_pio", trace_a, elf),
                self._entry("b", "boot_rom_pio", trace_b, elf),
            ]
            commands = []

            def run(command, **kwargs):
                commands.append((command, kwargs))
                return subprocess.CompletedProcess(command, 0)

            outputs = render_variant(
                "boot_rom_pio",
                entries,
                root / "reports",
                [source],
                CoverageTools(
                    python=root / "venv/bin/python",
                    retracer=root / "venv/bin/renode-retracer",
                    info_process=root / "venv/bin/info-process",
                    coverview=coverview,
                ),
                run=run,
            )

            self.assertEqual(
                commands[0][0][:2], [str(root / "venv/bin/renode-retracer"), "coverage"]
            )
            self.assertIn(str(trace_a), commands[0][0])
            self.assertIn(str(trace_b), commands[0][0])
            self.assertIn(str(elf), commands[0][0])
            self.assertEqual(commands[1][0][0], str(root / "venv/bin/info-process"))
            self.assertEqual(commands[2][0], ["npm", "run", "build"])
            self.assertEqual(commands[2][1]["cwd"], coverview)
            self.assertEqual(commands[3][0][0], str(root / "venv/bin/python"))
            self.assertEqual(outputs.html_dir, root / "reports/boot_rom_pio/html")
            self.assertTrue((outputs.html_dir / "index.html").is_file())

    def test_index_links_each_generated_variant(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            write_index(
                output_dir,
                {
                    "boot_rom": ("boot_rom/html/index.html", 2),
                    "boot_rom_pio": ("boot_rom_pio/html/index.html", 7),
                },
            )
            text = (output_dir / "index.html").read_text(encoding="utf-8")
            self.assertIn('href="boot_rom/html/index.html"', text)
            self.assertIn("2 passing trace(s)", text)
            self.assertIn('href="boot_rom_pio/html/index.html"', text)

    @staticmethod
    def _entry(item: str, mode: str, trace: Path, elf: Path):
        from fw_coverage.gen_sep_rom_coverage import TraceInput

        return TraceInput(item, mode, trace.parent, trace, elf, "same")


if __name__ == "__main__":
    unittest.main()
