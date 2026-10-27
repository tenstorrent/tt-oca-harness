# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# OCA validator library sources and configuration. Code that decodes a manifest
# the ROM validated must be built with the same configuration as the ROM. The
# including Makefile defines OCAH_ROOT first.

OCA_CONFIG_MK_DIR := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
TT_OCA_MANIFEST_DIR ?= $(OCA_CONFIG_MK_DIR)/tools/tt-oca-manifest

OCA_LIB_DIR  := $(TT_OCA_MANIFEST_DIR)/validators/oca/lib
OCA_LIB_SRCS := $(wildcard $(OCA_LIB_DIR)/*.c)

# PQC enables OCAP geometry but not PQC signature verification; native PQC
# signatures remain unsupported. Disable it only to reduce ROM size.
OCA_SUPPORT_CLASSIC ?= 1
OCA_SUPPORT_PQC     ?= 1
OCA_TOC_MAX_IMAGES  ?= 32

OCA_CFLAGS := -I$(OCA_LIB_DIR) \
	-DOCA_SUPPORT_CLASSIC=$(OCA_SUPPORT_CLASSIC) -DOCA_SUPPORT_PQC=$(OCA_SUPPORT_PQC) \
	-DOCA_TOC_MAX_IMAGES=$(OCA_TOC_MAX_IMAGES)

# Reject an empty source glob so an uninitialized submodule cannot produce an image without validation.
ifeq ($(strip $(OCA_LIB_SRCS)),)
$(error the tt-oca-manifest submodule is not checked out: no sources under $(OCA_LIB_DIR). \
Run: git -C $(OCAH_ROOT) submodule update --init hw/sys/sep/bootrom/prod/tools/tt-oca-manifest)
endif
