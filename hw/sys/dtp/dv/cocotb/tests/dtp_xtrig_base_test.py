# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Base of the cross-trigger tests: the scenarios drive no JTAG, so no instruction loads."""

from dtp_base_test import dtp_base_test


class dtp_xtrig_base_test(dtp_base_test):
    """Cross-trigger scenario test; requires no JTAG scoreboard feature."""

    required_features: tuple[str, ...] = ()
