# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sv_comment_text import struct_field_clauses  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]


class StructFieldClausesTests(unittest.TestCase):
    def test_joins_continuation_lines(self):
        lines = [
            "  typedef struct packed {",
            "    logic [10:0] MFR_ID;  // JEDEC manufacturer ID in the",
            "                          // DTP IDCODE, and in the",
            "                            // SEP JTAG ID code.",
            "  } cfg_t;",
        ]
        self.assertEqual(
            struct_field_clauses(lines),
            {
                "cfg_t": {
                    "MFR_ID": "JEDEC manufacturer ID in the DTP IDCODE, and in the SEP JTAG ID code."
                }
            },
        )

    def test_banner_is_no_field_clause(self):
        lines = [
            "  typedef struct packed {",
            "    bit A;  // Enables A.",
            "    // JTAG enables",
            "    bit B;",
            "",
            "    // Cross-trigger",
            "    int unsigned C;  // Counts C.",
            "  } cfg_t;",
        ]
        self.assertEqual(
            struct_field_clauses(lines), {"cfg_t": {"A": "Enables A.", "C": "Counts C."}}
        )

    def test_field_without_clause_is_absent(self):
        lines = [
            "  typedef struct packed {",
            "    logic [XTRIG_INT_CT_MODE_WIDTH-1:0] MODE;",
            "    bit [255:0]  TOKEN;  // Token digest.",
            "  } cfg_t;",
        ]
        self.assertEqual(struct_field_clauses(lines), {"cfg_t": {"TOKEN": "Token digest."}})

    def test_two_structs(self):
        lines = [
            "  typedef struct packed {",
            "    logic valid;  // Request valid.",
            "  } req_t;",
            "",
            "  localparam int unsigned W = 4;  // Not a field.",
            "",
            "  typedef struct packed {",
            "    logic valid;  // Response valid.",
            "    logic [W-1:0] data;  // Response data.",
            "  } rsp_t;",
        ]
        self.assertEqual(
            struct_field_clauses(lines),
            {
                "req_t": {"valid": "Request valid."},
                "rsp_t": {"valid": "Response valid.", "data": "Response data."},
            },
        )

    def test_every_smu_cfg_field_has_a_clause(self):
        lines = (ROOT / "hw/sys/smu/rtl/smu_pkg.sv").read_text(encoding="utf-8").splitlines()
        end = next(i for i, line in enumerate(lines) if re.match(r"\s*\}\s*smu_cfg_t\s*;", line))
        start = max(i for i in range(end) if "typedef struct" in lines[i])
        code = " ".join(line.split("//", 1)[0] for line in lines[start + 1 : end])
        fields = re.findall(r"([A-Za-z_]\w*)\s*;", code)
        self.assertTrue(fields)
        self.assertEqual(list(struct_field_clauses(lines)["smu_cfg_t"]), fields)


if __name__ == "__main__":
    unittest.main()
