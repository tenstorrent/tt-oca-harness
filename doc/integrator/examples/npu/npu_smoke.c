// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Minimal control-plane example. The caller supplies a valid descriptor and
// prepares/checks DMA buffers according to the selected NPU configuration.

#include <stddef.h>
#include <stdint.h>

#include "npu_platform.h"

#define NPU_CTRL             0x000u
#define NPU_STATUS           0x004u
#define NPU_CFG_PE           0x008u
#define NPU_DMA_EXT_BASE     0x014u
#define NPU_LAYER_DESC_PUSH  0x018u
#define NPU_LAYER_DESC_STS   0x01cu
#define NPU_INTR_STATE       0x020u
#define NPU_INTR_ENABLE      0x024u
#define NPU_INTR_TEST        0x028u
#define NPU_ERR_CAUSE        0x068u

#define NPU_CTRL_ENABLE      (1u << 0)
#define NPU_CTRL_START       (1u << 2)
#define NPU_STATUS_DONE      (1u << 1)
#define NPU_STATUS_ERROR     (1u << 2)
#define NPU_DESC_FULL        (1u << 5)
#define NPU_INTR_DONE        (1u << 0)
#define NPU_INTR_ERROR       (1u << 1)

static volatile uint32_t npu_irq_seen;
static volatile uint32_t npu_last_error_cause;

static volatile uint32_t *npu_reg(uint32_t offset)
{
    return (volatile uint32_t *)(PLATFORM_NPU_CSR_BASE + offset);
}

static uint32_t npu_read(uint32_t offset)
{
    return *npu_reg(offset);
}

static void npu_write(uint32_t offset, uint32_t value)
{
    *npu_reg(offset) = value;
}

// Replace these barriers and cache hooks with the adopter platform primitives.
static void platform_dma_prepare(uintptr_t address, size_t length)
{
    (void)address;
    (void)length;
    __asm__ volatile ("" ::: "memory");
}

static void platform_dma_complete(uintptr_t address, size_t length)
{
    __asm__ volatile ("" ::: "memory");
    (void)address;
    (void)length;
}

void npu_irq_handler(void)
{
    uint32_t state = npu_read(NPU_INTR_STATE) &
                     (NPU_INTR_DONE | NPU_INTR_ERROR);
    npu_irq_seen |= state;
    npu_write(NPU_INTR_STATE, state);  // W1C
}

static int npu_push_descriptor(const uint32_t *words, size_t word_count,
                               uint32_t timeout)
{
    for (size_t word = 0; word < word_count; ++word) {
        uint32_t remaining = timeout;
        while ((npu_read(NPU_LAYER_DESC_STS) & NPU_DESC_FULL) != 0u) {
            if (remaining-- == 0u) {
                return -1;
            }
        }
        npu_write(NPU_LAYER_DESC_PUSH, words[word]);
    }
    return 0;
}

int npu_run_polling_smoke(const uint32_t *descriptor, size_t descriptor_words,
                          uintptr_t buffer, size_t buffer_size,
                          uint32_t timeout)
{
    uint32_t remaining = timeout;

    if (!platform_npu_security_release_confirmed()) {
        return -5;
    }

    if (descriptor == NULL || descriptor_words == 0u ||
        buffer < PLATFORM_NPU_DMA_BASE ||
        buffer_size > PLATFORM_NPU_DMA_SIZE ||
        buffer > PLATFORM_NPU_DMA_BASE + PLATFORM_NPU_DMA_SIZE - buffer_size ||
        buffer > UINT32_MAX) {
        return -1;
    }

    platform_dma_prepare(buffer, buffer_size);
    npu_write(NPU_INTR_ENABLE, 0u);
    npu_write(NPU_INTR_STATE, NPU_INTR_DONE | NPU_INTR_ERROR);
    npu_write(NPU_DMA_EXT_BASE, (uint32_t)buffer);
    npu_write(NPU_CTRL, NPU_CTRL_ENABLE);
    if (npu_push_descriptor(descriptor, descriptor_words, timeout) != 0) {
        return -2;
    }
    npu_write(NPU_CTRL, NPU_CTRL_ENABLE | NPU_CTRL_START);

    while (remaining-- != 0u) {
        uint32_t status = npu_read(NPU_STATUS);
        if ((status & NPU_STATUS_ERROR) != 0u) {
            npu_last_error_cause = npu_read(NPU_ERR_CAUSE);
            return -4;
        }
        if ((status & NPU_STATUS_DONE) != 0u) {
            platform_dma_complete(buffer, buffer_size);
            npu_write(NPU_INTR_STATE, NPU_INTR_DONE);
            return 0;
        }
    }
    return -3;
}

int npu_interrupt_route_smoke(uint32_t timeout)
{
    if (!platform_npu_security_release_confirmed()) {
        return -2;
    }

    npu_irq_seen = 0u;
    npu_write(NPU_INTR_STATE, NPU_INTR_DONE | NPU_INTR_ERROR);
    npu_write(NPU_INTR_ENABLE, NPU_INTR_DONE | NPU_INTR_ERROR);

    // The platform must register npu_irq_handler and enable the assigned CPU IRQ
    // before this software-triggered event is issued.
    npu_write(NPU_INTR_TEST, NPU_INTR_DONE);
    while (timeout-- != 0u) {
        if ((npu_irq_seen & NPU_INTR_DONE) != 0u) {
            npu_write(NPU_INTR_ENABLE, 0u);
            return 0;
        }
    }
    npu_write(NPU_INTR_ENABLE, 0u);
    return -1;
}

uint32_t npu_configuration_probe(void)
{
    return npu_read(NPU_CFG_PE);
}
