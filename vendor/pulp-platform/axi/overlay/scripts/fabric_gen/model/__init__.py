# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Model module for fabric generator."""
from .protocol import Protocol
from .conversion import ConversionStep, ConversionType, ConversionChain

# Re-export from config for backwards compatibility
from ..config.schema import ProtocolType, PROTOCOL_HIERARCHY

__all__ = [
    'Protocol',
    'ProtocolType',
    'PROTOCOL_HIERARCHY',
    'ConversionStep',
    'ConversionType',
    'ConversionChain',
]
