# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Check reader order and block ownership across the TRM publication sources."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ORDERS = {
    "sep": [
        "overview",
        "threat_model",
        "attack_countermeasures",
        "clk_rst",
        "cpu",
        "rom",
        "fabric",
        "interrupts",
        "periphs",
        "security",
        "crypto",
        "memory_map",
    ],
    "smc": [
        "overview",
        "clk_rst",
        "cpu",
        "rom",
        "fabric",
        "interrupts",
        "periphs",
        "dfd",
        "scan_protection",
        "memmap",
    ],
    "dtp": ["overview", "clk_rst", "jtag", "cross_trigger", "ip_reference", "reference"],
}
OWNERS = {
    "cpu": ["sep_cpu_ctrl", "sep_scratch"],
    "interrupts": ["el2_pic"],
    "reset_controller": ["sep_reset_ctrl"],
    "lifecycle_controller": ["sep_lifecycle_ctrl"],
    "otp_fuse_controller": ["sep_efuse_map"],
    "watchdog": ["aon_timer"],
    "aes": ["aes"],
    "hmac": ["hmac"],
    "kmac": ["kmac"],
    "otbn": ["otbn"],
    "trng": ["csrng", "edn"],
    "dma": ["secure_dma"],
    "spi": ["spi_controller"],
}


class Structure(unittest.TestCase):
    def test_common_reader_order(self):
        nav = (ROOT / "doc/trm/modules/ROOT/nav.adoc").read_text()
        pdf = (ROOT / "doc/trm/src/index.adoc").read_text()
        for module, expected in ORDERS.items():
            with self.subTest(module=module):
                actual = re.findall(rf"^\*{{4}} xref:{module}:([^.#]+)\.adoc", nav, re.M)
                self.assertEqual(actual, expected)
                landing = (ROOT / f"hw/sys/{module}/doc/index.adoc").read_text()
                actual = re.findall(r"^\* xref:(?:" + module + r":)?([^.#:]+)\.adoc", landing, re.M)
                self.assertEqual(actual, expected)
                actual = re.findall(
                    rf"include::../../../hw/sys/{module}/doc/([^./]+)\.adoc\[leveloffset=\+4\]", pdf
                )
                self.assertEqual(actual, expected)

    def test_shared_chapter_sections(self):
        outlines = {
            "rom": [
                "ROM Architecture",
                "Hardware Configuration and Integrity",
                "Boot Flow",
                "Firmware Reference",
            ],
            "interrupts": [
                "Controllers",
                "Sources and Routing",
                "Software Handling",
                "Register Reference",
            ],
            "fabric": [
                "Topology",
                "Interfaces",
                "Address Remapping",
                "Filtering and Protection",
                "Routing",
                "Register Reference",
            ],
        }
        for chapter, expected in outlines.items():
            for module in ("sep", "smc"):
                with self.subTest(module=module, chapter=chapter):
                    text = (ROOT / f"hw/sys/{module}/doc/{chapter}.adoc").read_text()
                    self.assertEqual(re.findall(r"^== (.+)$", text, re.M), expected)

    def test_rom_manuals_and_mailbox_navigation(self):
        nav = (ROOT / "doc/trm/modules/ROOT/nav.adoc").read_text()
        for module in ("sep", "smc"):
            manual = f"xref:{module}-bootrom-prod:index.adoc[Production ROM Manual]"
            self.assertIn(f"**** xref:{module}:rom.adoc[Boot ROM]\n***** {manual}", nav)
            landing = (ROOT / f"hw/sys/{module}/doc/index.adoc").read_text()
            self.assertIn(f"* xref:rom.adoc[Boot ROM]\n** {manual}", landing)
        self.assertIn("***** xref:sep:mailbox.adoc[Mailboxes]", nav)
        pdf = (ROOT / "doc/trm/src/index.adoc").read_text()
        self.assertIn("include::../../../hw/sys/sep/doc/mailbox.adoc[leveloffset=+5]", pdf)

    def test_register_owners(self):
        for page, maps in OWNERS.items():
            with self.subTest(page=page):
                text = (ROOT / f"hw/sys/sep/doc/{page}.adoc").read_text()
                for name in maps:
                    self.assertRegex(text, rf"include::[^\n]+/{name}\.html\[")
                    self.assertRegex(text, rf"include::[^\n]+/{name}\.adoc\[")
        summary = (ROOT / "hw/sys/sep/doc/memory_map.adoc").read_text()
        self.assertEqual(re.findall(r"include::[^\n]+/([^/]+)\.html\[", summary), ["sep_external"])
        km = (ROOT / "hw/ip/key_manager/doc/index.adoc").read_text()
        for name in [
            "key_manager",
            "km_csr",
            "km_kpv",
            "km_drbg_sampler",
            "km_mailbox_km",
            "km_mailbox_sep",
            "abr_wrapper_key",
            "aes_wrapper_key",
            "hmac_wrapper_key",
            "kmac_wrapper_key",
            "otbn_wrapper_key",
        ]:
            self.assertIn(f"/{name}.html[", km)

    def test_service_placement(self):
        nav = (ROOT / "doc/trm/modules/ROOT/nav.adoc").read_text()
        for module in ["sep", "smc"]:
            self.assertIn(f"***** xref:{module}:dma.adoc[", nav)
        self.assertIn("***** xref:smc:zeroer.adoc[", nav)
        self.assertIn("***** xref:smc:watchdog.adoc[", nav)
        cpu = (ROOT / "hw/sys/sep/doc/cpu.adoc").read_text()
        self.assertNotIn("== Direct Memory Access (DMA)", cpu)
        self.assertNotIn("== BL0 Secure Boot and BL1 Execution Unlock", cpu)


if __name__ == "__main__":
    unittest.main()
