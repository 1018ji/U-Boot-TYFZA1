// SPDX-License-Identifier: GPL-2.0-only
/* NAND I/O boundary for executing the generated recovery script in real Hush. */
#include <command.h>
#include <env.h>
#include <malloc.h>
#include <mapmem.h>
#include <stdio.h>
#include <string.h>
#include <vsprintf.h>
#include "formats.h"

int tyfza1_loader_certificates(const void *data, size_t size);
static unsigned char *flash, *original;
static unsigned int erases, writes, order[2], fault;

static int do_ttlfixture(struct cmd_tbl *cmd, int flag, int argc, char *const argv[])
{
	const void *data;
	if (argc != 3) return CMD_RET_USAGE;
	free(flash); free(original);
	flash = malloc(TYF_BOOT_SIZE); original = malloc(TYF_BOOT_SIZE);
	if (!flash || !original) return CMD_RET_FAILURE;
	data = map_sysmem(hextoul(argv[1], NULL), TYF_BOOT_SIZE);
	memcpy(flash, data, TYF_BOOT_SIZE); memcpy(original, data, TYF_BOOT_SIZE);
	unmap_sysmem(data);
	fault = hextoul(argv[2], NULL); erases = writes = 0;
	env_set("mtdids", "original-ids"); env_set("mtdparts", "original-parts");
	return 0;
}

static int do_ttlnand(struct cmd_tbl *cmd, int flag, int argc, char *const argv[])
{
	const char *parts = env_get("mtdparts"), *name;
	size_t offset, size, capacity;
	void *data;
	int copy;
	if (!flash) return CMD_RET_FAILURE;
	if (argc == 3 && !strcmp(argv[1], "device") && !strcmp(argv[2], "0")) return 0;
	if (argc != 3 && argc != 5) return CMD_RET_USAGE;
	name = argv[argc == 3 ? 2 : 3];
	if (!strcmp(name, "boot") && parts && !strcmp(parts, "mtdparts=nand0:2m(boot)")) {
		offset = 0; capacity = TYF_BOOT_SIZE; copy = -1;
	} else if (parts && !strcmp(parts, "mtdparts=nand0:768k@0x40000(ttl_fip0),768k@0x100000(ttl_fip1)")) {
		if (!strcmp(name, "ttl_fip0")) copy = 0;
		else if (!strcmp(name, "ttl_fip1")) copy = 1;
		else return CMD_RET_FAILURE;
		offset = copy ? TYF_FIP1_OFFSET : TYF_FIP0_OFFSET; capacity = TYF_FIP_SIZE;
	} else return CMD_RET_FAILURE;
	if (argc == 3) {
		if (strcmp(argv[1], "erase.part") || copy < 0 || erases >= 2 ||
		    (erases == 0 && copy != 1) || (erases == 1 && copy != 0)) return CMD_RET_FAILURE;
		if (fault == 2 && copy == 1) return CMD_RET_FAILURE;
		order[erases++] = copy; memset(flash + offset, 0xff, capacity);
		return 0;
	}
	size = hextoul(argv[4], NULL);
	if (size != capacity) return CMD_RET_FAILURE;
	/* A full named-partition read cannot skip a bad block within its limit. */
	if (!strcmp(argv[1], "read") && fault == 1) return CMD_RET_FAILURE;
	data = map_sysmem(hextoul(argv[2], NULL), size);
	if (!strcmp(argv[1], "read")) {
		memcpy(data, flash + offset, size);
		if (fault == 4 && copy == 1 && writes) ((unsigned char *)data)[0] ^= 1;
	} else if (!strcmp(argv[1], "write") && copy >= 0) {
		if (fault == 3 && copy == 1) { unmap_sysmem(data); return CMD_RET_FAILURE; }
		memcpy(flash + offset, data, size); writes++;
	} else { unmap_sysmem(data); return CMD_RET_FAILURE; }
	unmap_sysmem(data);
	return 0;
}

static int do_ttlassert(struct cmd_tbl *cmd, int flag, int argc, char *const argv[])
{
	static const char *variants[] = { "4ge", "2p5g" };
	const unsigned char *bundle;
	struct tyf_payload next;
	unsigned int expected;
	int good, i, matches = 0;
	if (argc != 3 || !flash) return CMD_RET_USAGE;
	expected = hextoul(argv[2], NULL);
	good = erases == expected &&
		!memcmp(flash, original, TYF_FIP0_OFFSET) &&
		!memcmp(flash + 0x1c0000, original + 0x1c0000, TYF_BOOT_SIZE - 0x1c0000) &&
		env_get("mtdids") && !strcmp(env_get("mtdids"), "original-ids") &&
		env_get("mtdparts") && !strcmp(env_get("mtdparts"), "original-parts");
	if (!strcmp(argv[1], "unchanged")) good &= !memcmp(flash, original, TYF_BOOT_SIZE);
	else if (!strcmp(argv[1], "primary"))
		good &= !memcmp(flash + TYF_FIP0_OFFSET, original + TYF_FIP0_OFFSET, TYF_FIP_SIZE);
	else if (!strcmp(argv[1], "installed")) {
		good &= erases == 2 && writes == 2 && order[0] == 1 && order[1] == 0 &&
			!tyfza1_loader_certificates(flash, TYF_BOOT_SIZE);
		/* Independently select the intended payload with the production C gate. */
		bundle = map_sysmem(0x11020000, TYF_BUNDLE_HEADER + 2 * TYF_BOOT_SIZE);
		for (i = 0; i < 2; i++) {
			if (tyf_select_loader(bundle, TYF_BUNDLE_HEADER + 2 * TYF_BOOT_SIZE,
					      variants[i], &next) ||
			    tyf_loader_preserves_device(next.data, next.size, original, TYF_BOOT_SIZE)) continue;
			matches++;
			good &= !memcmp(flash + TYF_FIP0_OFFSET, next.data + TYF_FIP0_OFFSET, TYF_FIP_SIZE) &&
				!memcmp(flash + TYF_FIP1_OFFSET, next.data + TYF_FIP1_OFFSET, TYF_FIP_SIZE);
		}
		unmap_sysmem(bundle);
		good &= matches == 1;
	}
	else good = 0;
	printf("TTL ASSERT %s (erases=%u writes=%u)\n", good ? "OK" : "FAILED", erases, writes);
	return good ? 0 : CMD_RET_FAILURE;
}

U_BOOT_CMD(ttlfixture, 3, 0, do_ttlfixture, "set up modeled NAND for TTL recovery tests", "");
U_BOOT_CMD(nand, 5, 0, do_ttlnand, "modeled NAND for TTL recovery tests only", "");
U_BOOT_CMD(ttlassert, 3, 0, do_ttlassert, "check TTL recovery writes", "");
