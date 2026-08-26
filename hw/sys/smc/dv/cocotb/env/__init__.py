# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS PyUVM environment package."""

from .smc_memory_model import SmcMemoryModel, SmcMemoryRegion

__all__ = ["SmcMemoryModel", "SmcMemoryRegion"]
