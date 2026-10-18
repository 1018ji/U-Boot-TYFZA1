// SPDX-License-Identifier: GPL-2.0-only
#include <command.h>
#include <mapmem.h>
#include <stdio.h>
#include <vsprintf.h>
int tyfza1_loader_certificates(const void *loader, size_t size);
static int do_tyfcert(struct cmd_tbl *cmd, int flag, int argc, char *const argv[])
{
	const void *data;
	int ret;
	if (argc != 3) return CMD_RET_USAGE;
	data = map_sysmem(hextoul(argv[1], NULL), hextoul(argv[2], NULL));
	ret = tyfza1_loader_certificates(data, hextoul(argv[2], NULL));
	unmap_sysmem(data);
	printf("TYF CERT %s (%d)\n", ret ? "REJECT" : "OK", ret);
	return ret ? CMD_RET_FAILURE : CMD_RET_SUCCESS;
}
U_BOOT_CMD(tyfcert, 3, 0, do_tyfcert, "exercise production Taurus certificate verification", "");
