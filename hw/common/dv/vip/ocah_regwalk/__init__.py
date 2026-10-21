# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""ocah_regwalk — register model and access classifier over generated Python headers.

cocotb/     the model, classifier and exclusion bookkeeping; its ``__all__`` is
            re-exported at the package root, so ``ocah_regwalk`` and
            ``ocah_regwalk.cocotb`` name the same objects
tests/      unittest suite: a hand-written header fixture plus the committed
            SMC and SEP header inventories
"""

from .cocotb import *  # noqa: F401,F403
from .cocotb import __all__  # noqa: F401
