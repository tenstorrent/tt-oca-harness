# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# Canonical OCAH_ROOT for hw/{ip,sys}/<block>/flow.mk: resolved from this
# file's own location while it is being read, so a flow.mk only needs a fixed
# relative path to include it, without already knowing OCAH_ROOT. Same
# bootstrap trick as hw/common/dv/fw/preamble.mk; the ifndef guard honors an
# OCAH_ROOT already forwarded by the top-level dispatcher.
ifndef OCAH_ROOT
OCAH_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))..)
endif
