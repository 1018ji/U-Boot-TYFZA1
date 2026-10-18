// SPDX-License-Identifier: GPL-2.0-only
#include <stddef.h>
#include <stdint.h>
#include "loader-config.h"
#include "LzmaDec.h"

extern const unsigned char payload_start[], payload_end[];
extern void loader_sync_code(uintptr_t address, size_t size);
static unsigned char workspace[65536] __attribute__((aligned(16)));

void *memcpy(void *dest, const void *src, size_t size)
{
	unsigned char *to = dest;
	const unsigned char *from = src;
	while (size--) *to++ = *from++;
	return dest;
}

void *memset(void *dest, int value, size_t size)
{
	unsigned char *to = dest;
	while (size--) *to++ = value;
	return dest;
}

static void serial_puts(const char *s)
{
	volatile uint32_t *data = (void *)(uintptr_t)(UART_BASE + UART_DATA);
	volatile uint32_t *status = (void *)(uintptr_t)(UART_BASE + 0x18);
	while (*s) {
		unsigned int timeout = 1000000;
		while ((*status & UART_FULL) && --timeout) {}
		if (!timeout) return;
		*data = (unsigned char)*s++;
	}
}

static void *alloc_probs(ISzAllocPtr allocator, size_t size)
{
	(void)allocator;
	return size <= sizeof(workspace) ? workspace : NULL;
}

static void free_probs(ISzAllocPtr allocator, void *address)
{
	(void)allocator;
	(void)address;
}

static uint32_t crc32(const unsigned char *data, size_t size)
{
	uint32_t crc = 0xffffffff;
	unsigned int bit;
	while (size--) {
		crc ^= *data++;
		for (bit = 0; bit < 8; bit++)
			crc = (crc >> 1) ^ (0xedb88320U & -(crc & 1));
	}
	return ~crc;
}

static __attribute__((noreturn)) void failed(void)
{
	serial_puts("TYFZA1: BL33 integrity/decompression failed\r\n");
#if LOADER_QEMU
	unsigned long reason[] = { 0x20026, 1 };
	register unsigned long x0 __asm__("x0") = 0x20;
	register void *x1 __asm__("x1") = reason;
	__asm__ volatile("hlt #0xf000" : "+r"(x0) : "r"(x1) : "memory");
#endif
	for (;;) __asm__ volatile("wfe");
}

__attribute__((noreturn)) void loader_main(unsigned long a0, unsigned long a1,
					 unsigned long a2, unsigned long a3)
{
	const ISzAlloc allocator = { alloc_probs, free_probs };
	SizeT source_size = payload_end - payload_start;
	SizeT output_size = PLAIN_SIZE;
	ELzmaStatus status;
	unsigned int i;
	uint64_t recorded_size = 0;
	int ret;

	serial_puts("TYFZA1: BL33 loader started\r\n");
	if (source_size < 13 || payload_start[0] != 0x5d) failed();
	for (i = 0; i < 8; i++) recorded_size |= (uint64_t)payload_start[5 + i] << (8 * i);
	if (recorded_size != PLAIN_SIZE) failed();
	source_size -= 13;
	ret = LzmaDecode((void *)(uintptr_t)RUN_ADDR, &output_size, payload_start + 13,
			 &source_size, payload_start, 5, LZMA_FINISH_END, &status, &allocator);
	if (ret || status != LZMA_STATUS_FINISHED_WITH_MARK || output_size != PLAIN_SIZE ||
	    source_size != (SizeT)(payload_end - payload_start - 13) ||
	    crc32((void *)(uintptr_t)RUN_ADDR, output_size) != PLAIN_CRC) failed();
	loader_sync_code(RUN_ADDR, output_size);
	serial_puts("TYFZA1: BL33 decompressed and verified\r\n");
	((void (*)(unsigned long, unsigned long, unsigned long, unsigned long))
	 (uintptr_t)RUN_ADDR)(a0, a1, a2, a3);
	failed();
}
