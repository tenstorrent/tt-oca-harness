# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# Resolve OCAH_ROOT from this file's own location so a flow.mk can include it
# with only a fixed relative path, without already knowing OCAH_ROOT.
ifndef OCAH_ROOT
OCAH_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))..)
endif
