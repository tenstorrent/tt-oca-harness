# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Runnable example of named OCAH checker evidence."""

from __future__ import annotations

import logging

from ocah_checker import OcahChecker


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    checker = OcahChecker(
        name="register-example",
        required_ids={"CHK-REGISTER", "CHK-NONVAC"},
    )

    expected = 0xA5
    observed = 0xA5
    checker.expect_equal(
        "CHK-REGISTER",
        observed,
        expected,
        context="addr=0x1000",
    )
    checker.expect_true(
        "CHK-NONVAC",
        observed not in (0x00, 0xFF),
        context=f"observed={observed:#x}",
    )
    checker.finalize()


if __name__ == "__main__":
    main()
