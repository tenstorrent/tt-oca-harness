# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""On the EDN lane adapter, an AR between AW and W waits for the write, and both retire.

Target: drbg.sv u_edn_axil_adapter. Run mode: no_cpu with +skip_fuse_sense.
One (lane x ordering) per leaf so a wedge cannot contaminate a later cell. See
sep_drbg_axil_concurrent_base for the checks.

AW handshakes first, then AR arrives while W is still outstanding: the
partially-committed aw_pending_q=1 / w_pending_q=0 state.
"""

from __future__ import annotations

import pyuvm

from tests.system.sep_drbg_axil_concurrent_base import sep_drbg_axil_concurrent_base


@pyuvm.test()
class sep_drbg_axil_concurrent_edn_aw_then_ar_test(sep_drbg_axil_concurrent_base):
    """An AR after AW and before W is held until both write halves handshake; the write lands."""

    LANE = "edn"
    ORDER = "aw-then-ar"
