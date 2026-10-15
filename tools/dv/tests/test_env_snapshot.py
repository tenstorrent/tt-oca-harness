# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Unit tests for the values the runner's environment snapshots redact.

Run from the repository root:

    python3 -m unittest discover tools/dv/tests
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runlib.stages import REDACTED_ENV_PATTERN, REDACTED_VALUE, write_env_snapshot  # noqa: E402

TOKEN_NAMES = ("PAT", "GITHUB_PAT", "MY_REPO_PAT", "PAT_TOKEN", "gh_pat")
PLAIN_NAMES = (
    "PATH",
    "MANPATH",
    "PYTHONPATH",
    "LD_LIBRARY_PATH",
    "GITHUB_PATH",
    "FOO_PATTERN",
    "PATCH",
    "PATTERN",
    "SPATIAL",
    "COMPAT",
)


class EnvSnapshotRedaction(unittest.TestCase):
    def test_a_personal_access_token_name_is_redacted(self):
        for name in TOKEN_NAMES:
            with self.subTest(name=name):
                self.assertIsNotNone(REDACTED_ENV_PATTERN.search(name))

    def test_path_and_pattern_names_keep_their_values(self):
        for name in PLAIN_NAMES:
            with self.subTest(name=name):
                self.assertIsNone(REDACTED_ENV_PATTERN.search(name))

    def test_the_snapshot_writes_the_redacted_value_in_place_of_a_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "env" / "sim.env"
            write_env_snapshot(path, {"GITHUB_PAT": "ghp_example", "PATH": "/usr/bin"}, False)
            text = path.read_text()
        self.assertIn(f"GITHUB_PAT={REDACTED_VALUE}\n", text)
        self.assertIn("PATH=/usr/bin\n", text)
        self.assertNotIn("ghp_example", text)


if __name__ == "__main__":
    unittest.main()
