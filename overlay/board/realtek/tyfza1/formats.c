// SPDX-License-Identifier: GPL-2.0-only
#include "formats.h"
#include <string.h>

static uint64_t le64(const unsigned char *p)
{
	uint64_t n = 0;
	unsigned int i;
	for (i = 0; i < 8; i++)
		n |= (uint64_t)p[i] << (8 * i);
	return n;
}

static int zeros(const unsigned char *p, size_t size)
{
	while (size--)
		if (*p++) return 0;
	return 1;
}

int tyf_parse_fip(const void *data, size_t size, struct tyf_fip *out)
{
	static const unsigned char ids[3][16] = {
		{0x5f,0xf9,0xec,0x0b,0x4d,0x22,0x3e,0x4d,0xa5,0x44,0xc3,0x9d,0x81,0xc7,0x3f,0x0a},
		{0x47,0xd4,0x08,0x6d,0x4c,0xfe,0x98,0x46,0x9b,0x95,0x29,0x50,0xcb,0xbd,0x5a,0x00},
		{0xd6,0xd0,0xee,0xa7,0xfc,0xea,0xd5,0x4b,0x97,0x82,0x99,0x34,0xf2,0x34,0xb6,0xe4},
	};
	struct tyf_payload *payloads[] = { &out->bl2, &out->bl31, &out->bl33 };
	const unsigned char *p = data;
	size_t toc, pos, prev;
	unsigned int i, found = 0;

	memset(out, 0, sizeof(*out));
	if (size < 56 || memcmp(p, "\x01\x00\x64\xaa", 4)) return -1;
	for (toc = 16; toc <= size - 40 && toc < 16 + 32 * 40; toc += 40)
		if (zeros(p + toc, 16)) break;
	if (toc > size - 40 || toc >= 16 + 32 * 40) return -1;
	toc += 40;
	for (pos = 16; pos < toc - 40; pos += 40) {
		uint64_t off = le64(p + pos + 16), len = le64(p + pos + 24);
		if (!len || off < toc || off > size || len > size - off) return -1;
		for (prev = 16; prev < pos; prev += 40) {
			uint64_t old = le64(p + prev + 16), count = le64(p + prev + 24);
			if (!memcmp(p + pos, p + prev, 16) ||
			    (off < old + count && old < off + len)) return -1;
		}
		for (i = 0; i < 3; i++) {
			if (memcmp(p + pos, ids[i], 16)) continue;
			found |= 1U << i;
			payloads[i]->data = p + (size_t)off;
			payloads[i]->size = (size_t)len;
		}
	}
	return found == 7 ? 0 : -1;
}

int tyf_parse_loader(const void *data, size_t size, struct tyf_fip *out)
{
	const unsigned char *p = data;
	struct tyf_fip second;
	if (size != TYF_BOOT_SIZE || memcmp(p + 0x200, "EFI PART", 8) ||
	    memcmp(p + size - 512, "EFI PART", 8) ||
	    tyf_parse_fip(p + TYF_FIP0_OFFSET, TYF_FIP_SIZE, out) ||
	    tyf_parse_fip(p + TYF_FIP1_OFFSET, TYF_FIP_SIZE, &second)) return -1;
	if (out->bl2.size != second.bl2.size || out->bl31.size != second.bl31.size ||
	    out->bl33.size != second.bl33.size ||
	    memcmp(out->bl2.data, second.bl2.data, out->bl2.size) ||
	    memcmp(out->bl31.data, second.bl31.data, out->bl31.size) ||
	    memcmp(out->bl33.data, second.bl33.data, out->bl33.size)) return -1;
	return 0;
}

static int octal(const unsigned char *p, size_t size, uint64_t *value)
{
	size_t i = 0;
	uint64_t n = 0;
	while (i < size && p[i] == ' ') i++;
	for (; i < size && p[i] >= '0' && p[i] <= '7'; i++) {
		if (n > (UINT64_MAX - 7) / 8) return -1;
		n = n * 8 + p[i] - '0';
	}
	for (; i < size; i++)
		if (p[i] && p[i] != ' ') return -1;
	*value = n;
	return 0;
}

int tyf_parse_sysupgrade(const void *data, size_t size, struct tyf_firmware *out)
{
	const unsigned char *p = data;
	size_t pos = 0, i;
	char directory[101] = {0};
	int finished = 0;
	memset(out, 0, sizeof(*out));
	while (pos <= size && size - pos >= 512) {
		const unsigned char *h = p + pos;
		const char *name = (const char *)h, *slash;
		uint64_t len, check, sum = 0;
		size_t dirlen, padded;
		struct tyf_payload *target = NULL;
		if (zeros(h, 512)) {
			if (size - pos >= 1024 && zeros(h + 512, 512)) finished = 1;
			break;
		}
		if (!memchr(name, 0, 100) || memcmp(h + 257, "ustar", 5) ||
		    h[345] || octal(h + 124, 12, &len) || octal(h + 148, 8, &check)) return -1;
		for (i = 0; i < 512; i++) sum += i >= 148 && i < 156 ? ' ' : h[i];
		if (sum != check || len > size - pos - 512 || len > SIZE_MAX - 511) return -1;
		slash = strchr(name, '/');
		if (!slash) return -1;
		dirlen = slash - name;
		if (dirlen >= sizeof(directory)) return -1;
		if (!directory[0]) {
			if (!((dirlen == strlen("sysupgrade-tianyi_tyfza1") &&
			       !memcmp(name, "sysupgrade-tianyi_tyfza1", dirlen)) ||
			      (dirlen == strlen("sysupgrade-tianyi_tyfza1-2p5g") &&
			       !memcmp(name, "sysupgrade-tianyi_tyfza1-2p5g", dirlen)))) return -1;
			memcpy(directory, name, dirlen);
		}
		if (strlen(directory) != dirlen || memcmp(directory, name, dirlen)) return -1;
		if (!strcmp(slash + 1, "kernel")) target = &out->kernel;
		else if (!strcmp(slash + 1, "root")) target = &out->root;
		else if (strcmp(slash + 1, "CONTROL") && !(h[156] == '5' && !slash[1])) return -1;
		if (target) {
			if ((h[156] && h[156] != '0') || !len || target->data) return -1;
			target->data = h + 512;
			target->size = (size_t)len;
		} else if (len || (h[156] != '5' && h[156] && h[156] != '0')) {
			/* CONTROL is a regular non-empty file; all other entries are directories. */
			if (strcmp(slash + 1, "CONTROL") || (h[156] && h[156] != '0')) return -1;
		}
		padded = ((size_t)len + 511) & ~(size_t)511;
		if (padded > size - pos - 512) return -1;
		pos += 512 + padded;
	}
	if (!finished || !out->kernel.data || !out->root.data || out->kernel.size > 0x600000 ||
	    out->kernel.size < 40 || memcmp(out->kernel.data, "\xd0\x0d\xfe\xed", 4) ||
	    out->root.size < 96 || memcmp(out->root.data, "hsqs", 4) ||
	    le64(out->root.data + 40) < 96 || le64(out->root.data + 40) > out->root.size) return -1;
	return 0;
}
