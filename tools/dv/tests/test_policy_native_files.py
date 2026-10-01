# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Tests for the digest a `[[native_files]]` policy entry may pin its file to.

Run from the repository root:

    python3 -m unittest discover tools/dv/tests
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import test_coverage_closure as closure  # noqa: E402
from runlib.coverage_policy import load_coverage_policy  # noqa: E402
from runlib.models import ConfigError  # noqa: E402

# The fixture's `[[native_files]]` entry ends with its argument list.
ENTRY_END = "args = []\n"


def add_native_fields(root: Path, fields: str) -> Path:
    """Append `fields` to the fixture's `[[native_files]]` entry."""
    policy = root / closure.POLICY_REL
    text = policy.read_text(encoding="utf-8")
    assert text.count(ENTRY_END) == 1
    policy.write_text(text.replace(ENTRY_END, ENTRY_END + fields, 1), encoding="utf-8")
    return policy


class PinnedDigest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        closure.stage_fixture(self.root)

    def load(self):
        return load_coverage_policy(self.root / closure.POLICY_REL, expected_dut=closure.DUT)

    def test_a_matching_digest_loads(self):
        digest = closure.sha256_of(self.root / closure.NATIVE_REL)
        add_native_fields(self.root, f'sha256 = "{digest}"\n')
        self.assertEqual(self.load().native_files[0].sha256, digest)

    def test_a_digest_other_than_the_files_is_refused(self):
        add_native_fields(self.root, f'sha256 = "{"0" * 64}"\n')
        with self.assertRaisesRegex(ConfigError, "sha256 does not match"):
            self.load()

    def test_a_malformed_digest_is_refused(self):
        add_native_fields(self.root, 'sha256 = "abc"\n')
        with self.assertRaisesRegex(ConfigError, "64 lowercase hexadecimal"):
            self.load()

    def test_a_key_outside_the_grammar_is_refused(self):
        add_native_fields(self.root, 'expires = "2027-01-01"\n')
        with self.assertRaisesRegex(ConfigError, r"unsupported key\(s\): expires"):
            self.load()


if __name__ == "__main__":
    unittest.main()
