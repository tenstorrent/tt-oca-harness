# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sv_comment_text import struct_field_clauses  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
