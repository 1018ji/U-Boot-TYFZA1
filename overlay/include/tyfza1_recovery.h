/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef TYFZA1_RECOVERY_H
#define TYFZA1_RECOVERY_H
#include <linux/types.h>
int tyfza1_install_system(ulong address, size_t size, void (*poll)(void));
int tyfza1_install_loader(ulong address, size_t size, bool bl2, void (*poll)(void));
int tyfza1_rebuild_ubi(void (*poll)(void));
#endif
