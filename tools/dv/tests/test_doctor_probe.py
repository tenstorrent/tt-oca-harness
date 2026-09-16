# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Unit tests for the --doctor import probe: batching, timeout retry, and the budget knob.

Run from the repository root:

    python3 -m unittest discover tools/dv/tests
"""

from __future__ import annotations

import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runlib import cli  # noqa: E402
from runlib.cli import _probe_imports, doctor_probe_timeout  # noqa: E402
from runlib.models import ConfigError  # noqa: E402


def write_module(root: Path, name: str, body: str) -> None:
    (root / f"{name}.py").write_text(textwrap.dedent(body), encoding="utf-8")


class ProbeImportsTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        write_module(self.root, "probe_ok", "VALUE = 1\n")
        write_module(self.root, "probe_bad", 'raise ImportError("boom")\n')
        write_module(
            self.root,
            "probe_slow",
            """
            import time

            time.sleep(5)
            """,
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_reports_each_module_from_its_own_import(self) -> None:
        results = _probe_imports([self.root], ["probe_ok", "probe_bad"])
        self.assertEqual(results["probe_ok"], (True, "import OK"))
        self.assertFalse(results["probe_bad"][0])
        self.assertIn("ImportError: boom", results["probe_bad"][1])

    def test_timeout_fails_only_its_own_batch(self) -> None:
        results = _probe_imports([self.root], ["probe_slow", "probe_ok"], timeout=0.2, batch_size=1)
        self.assertEqual(results["probe_ok"], (True, "import OK"))
        self.assertFalse(results["probe_slow"][0])
        self.assertIn("timed out twice", results["probe_slow"][1])
        self.assertIn("OCAH_DOCTOR_PROBE_TIMEOUT", results["probe_slow"][1])

    def test_retry_recovers_a_batch_that_is_slow_once(self) -> None:
        marker = self.root / "warm.marker"
        write_module(
            self.root,
            "probe_cold",
            f"""
            import pathlib
            import time

            marker = pathlib.Path({str(marker)!r})
            if not marker.exists():
                marker.touch()
                time.sleep(5)
            """,
        )
        results = _probe_imports([self.root], ["probe_cold"], timeout=0.5, batch_size=1)
        self.assertEqual(results["probe_cold"], (True, "import OK"))

    def test_empty_module_list_probes_nothing(self) -> None:
        self.assertEqual(_probe_imports([self.root], []), {})


class DoctorProbeTimeoutTest(unittest.TestCase):
    def test_default_when_unset(self) -> None:
        with mock.patch.object(cli, "DOCTOR_PROBE_TIMEOUT_ENV", ""):
            self.assertEqual(doctor_probe_timeout(), cli.DOCTOR_PROBE_TIMEOUT_DEFAULT)

    def test_positive_number_is_used(self) -> None:
        with mock.patch.object(cli, "DOCTOR_PROBE_TIMEOUT_ENV", " 300 "):
            self.assertEqual(doctor_probe_timeout(), 300.0)

    def test_rejects_non_numeric_and_non_positive(self) -> None:
        for raw in ("abc", "0", "-5"):
            with (
                self.subTest(raw=raw),
                mock.patch.object(cli, "DOCTOR_PROBE_TIMEOUT_ENV", raw),
                self.assertRaises(ConfigError),
            ):
                doctor_probe_timeout()


if __name__ == "__main__":
    unittest.main()
