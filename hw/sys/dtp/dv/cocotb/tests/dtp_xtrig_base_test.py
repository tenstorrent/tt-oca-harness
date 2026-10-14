# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Base of the cross-trigger tests: CSR readbacks are required, and no JTAG feature."""

from __future__ import annotations

from dtp_base_test import dtp_base_test
from env.dtp_types import DTP_FEATURE_XTRIG_CSR


class dtp_xtrig_base_test(dtp_base_test):
    """Cross-trigger scenario test.

    The scenarios drive no JTAG, so no instruction loads, and every one reads
    back the CSRs it programs.
    """

    required_features: tuple[str, ...] = (DTP_FEATURE_XTRIG_CSR,)
