# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Composed register tables must have unambiguous fragment destinations."""

import importlib.util
import re
import unittest
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / "scope_register_ids.py"


class RegisterLinks(unittest.TestCase):
    def test_composed_tables(self):
        spec = importlib.util.spec_from_file_location("scope_register_ids", PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        table = '<a href="#INTR_STATE">status</a><h3 id="INTR_STATE">Status</h3>'
        combined = module.scope_ids(table, "csrng") + module.scope_ids(table, "edn")
        ids = re.findall(r'id="([^"]+)"', combined)
        self.assertEqual(ids, ["csrng-INTR_STATE", "edn-INTR_STATE"])
        self.assertEqual(re.findall(r'href="#([^"]+)"', combined), ids)
        self.assertEqual(
            module.scope_ids('<a href="other.html#INTR_STATE">other</a>', "csrng"),
            '<a href="other.html#INTR_STATE">other</a>',
        )

    def test_regmap_ids_remain_unscoped(self):
        spec = importlib.util.spec_from_file_location("scope_register_ids", PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        html = '<h2 id="regmap-UART_CTRL">UART Controller</h2><a href="#regmap-UART_CTRL">link</a>'
        result = module.scope_ids(html, "testblock")
        self.assertIn('id="regmap-UART_CTRL"', result)
        self.assertIn('href="#regmap-UART_CTRL"', result)
        self.assertNotIn('testblock-regmap-', result)


if __name__ == "__main__":
    unittest.main()
