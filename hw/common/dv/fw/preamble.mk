# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# Canonical OCAH_ROOT for open DV firmware subsystem makefiles: every
# hw/{ip,sys}/<name>/dv/fw/fw.mk includes this, so the path arithmetic to the repo
# root lives in one place. Resolved (:=) from this file's own location while it is
# being read; the ifndef guard honors an OCAH_ROOT from the dispatcher/cmdline.
ifndef OCAH_ROOT
OCAH_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))../../../..)
endif

ifndef UV
UV ?= uv
endif

ifndef PYTHON
PYTHON ?= $(UV) --directory "$(OCAH_ROOT)" run --locked
endif
