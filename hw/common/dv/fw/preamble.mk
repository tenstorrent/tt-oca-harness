# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# Canonical OCAH_ROOT for open DV firmware subsystem makefiles: every
# hw/{ip,sys}/<name>/dv/fw/fw.mk includes this, so the path arithmetic to the repo
# root lives in one place. Resolved (:=) from this file's own location while it is
# being read; the ifndef guard honors an OCAH_ROOT from the dispatcher/cmdline.
ifndef OCAH_ROOT
OCAH_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))../../../..)
endif

# Keep uv's interpreter, cache and venv together under the gitignored local/ tree
# so the venv never outlives its interpreter when a runner clears /tmp but keeps
# the checkout. ?= yields to a caller-set location.
UV_PROJECT_ENVIRONMENT ?= $(OCAH_ROOT)/local/fw-venv
UV_PYTHON_INSTALL_DIR  ?= $(OCAH_ROOT)/local/uv-python
UV_CACHE_DIR           ?= $(OCAH_ROOT)/local/uv-cache
export UV_PROJECT_ENVIRONMENT UV_PYTHON_INSTALL_DIR UV_CACHE_DIR

ifndef UV
UV ?= uv
endif

ifndef PYTHON
PYTHON ?= $(UV) --directory "$(OCAH_ROOT)" run --locked
endif
