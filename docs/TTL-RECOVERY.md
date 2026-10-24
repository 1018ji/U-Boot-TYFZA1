# TTL 刷入 U-Boot 1.4

适用于本项目旧版 U-Boot：**能进入 `TYFZA1#`，但因 `Recovery PHY missing: port 4, MDIO 7` 等错误打不开恢复网页**。全千兆版、2.5G 版使用同一流程。

[Issue #4](https://github.com/LeoooChen/U-Boot-TYFZA1/issues/4#issuecomment-6382759516) 中修改 `board_variant`、`b_conf` 无效，是因为旧版网口初始化逻辑仍在运行，启动时也会重新读取硬件 strap。需要更新实际的 U-Boot。

用任意串口工具连接设备，参数为 **115200 / 8N1 / 无流控**，中断自动启动，进入 `TYFZA1#`。UART 电平须匹配，只接 GND、交叉 RX/TX，不接 VCC。文件传输使用 **Kermit**，可用终端自带功能或外部发送器；普通文本发送不能替代 Kermit。

> 能打开恢复网页时，直接使用网页更新。`TAURUS#`、Linux 命令行或无法进入 U-Boot 提示符的情况不适用本文。

## 1. 电脑准备恢复文件

将两个文件放在同一文件夹：

| 文件 | 下载 |
|---|---|
| `tyfza1-uboot-universal.bin` | [官方 1.4 通用包](https://github.com/LeoooChen/U-Boot-TYFZA1/releases/download/v1.4/tyfza1-uboot-universal.bin) |
| `prepare_ttl_recovery.py` | [准备脚本](https://raw.githubusercontent.com/LeoooChen/U-Boot-TYFZA1/main/scripts/prepare_ttl_recovery.py)，确认保存为 `.py`，不是 `.py.txt` |

在该文件夹执行，需要 Python 3，无第三方依赖：

```sh
python3 prepare_ttl_recovery.py tyfza1-uboot-universal.bin
```

Windows 可将 `python3` 换成 `py -3`。成功后生成 **`tyfza1-ttl-recovery.scr`**，长度应为 **4325392 字节（十六进制 `420010`）**，并打印 SHA256。

脚本固定校验官方 1.4 通用包，不接受 `.run` 安装器、系统镜像或本机备份。恢复时按本机已有 BL2/BL31 自动匹配镜像，**不根据外壳标识或 `board_variant` 手工选板型**。

<details>
<summary>1.4 通用包 SHA256（脚本自动核对）</summary>

```text
e340dc0ea985a6cfe5aa41b0815c9b8559e3ce554f9370783468a2cfc5df6b46
```

</details>

## 2. 串口接收文件

先确认以下命令存在；出现 `Unknown command` 时停止：

```text
version
help loadb
help source
help hash
help nand
help itest
help setexpr
```

执行：

```text
loadb 11000000
```

看到 `Ready for binary (kermit) download` 后，用 **Kermit** 发送 **`tyfza1-ttl-recovery.scr`**。等待传输完成并返回 `TYFZA1#`，确认输出长度：

```text
Total Size = 0x00420010 = 4325392 Bytes
```

此时文件仅在内存中。传输失败或长度不同，可以重新执行 `loadb 11000000` 再发送。**接收地址固定，不要修改；不要选择普通文本、XMODEM 或 YMODEM 发送。** [loadb 官方说明](https://docs.u-boot.org/en/stable/usage/cmd/loadb.html)

## 3. 只读检查

逐条执行：

```text
setenv verify yes
setenv ttl_action check
source 11000000
```

恢复脚本会检查通用包 SHA256、两份旧 FIP 的 BL2/BL31、GPT 布局及 CRC、FIP 容量和保留区，并在 boot 自身的 2 MiB 边界内完整读取。坏块导致需要越界、固件不匹配或数据异常时会拒绝继续。

**只有最终出现下面的结果才继续：**

```text
Matching early firmware: 4ge
TTL CHECK OK - no Flash changed
```

匹配结果也可能是 `2p5g`。识别时会比较两种模板，以最终 `TTL CHECK OK` 为准。出现 `TTL STOP` 或没有成功标志时，保存完整输出，不跳过校验。

<details>
<summary>没有本机 boot 备份时，可额外保留内存副本</summary>

检查成功后，旧 boot 的 2 MiB 副本位于 `0x10000000`。开启串口工具的日志记录，再执行：

```text
md.b 10000000 200000
```

等待完整输出并返回提示符，再停止日志。此操作只读内存，耗时较长；日志是十六进制文本，供后续还原分析，**不能当二进制镜像直接刷入**。内存副本断电会丢失。

</details>

## 4. 写入双份 FIP

确认检查通过、供电稳定后执行：

```text
setenv ttl_action write
source 11000000
```

脚本再次检查后，先更新 FIP1，读回一致后再更新 FIP0。每份 FIP 使用大小固定为 `0xc0000` 的临时分区，限制写入范围。

**必须完整看到：**

```text
FIP1 written and read back
FIP0 written and read back
TTL WRITE OK - U-Boot 1.4 installed; reset manually
```

只更新 `0x100000`、`0x40000` 起始的两份 FIP，GPT、保留区、env/env2 及系统数据保持原值。临时分区设置会恢复，整个流程不执行 `saveenv`，也不自动重启。

> 写入中保持供电，不拔线、不重启、不发送中断。失败时保持供电并保留日志，不重复刷写或手工擦除。不要将通用包直接 `nand write` 到 boot，不做整片擦除或清除坏块标记。

## 5. 重启并进入恢复网页

只有出现 `TTL WRITE OK` 后执行：

```text
reset
```

重新进入 `TYFZA1#`，执行 `version`，确认显示 **`TYFZA1 1.4`**。网线接健康的千兆口，电脑设为 **`192.168.0.2/24`**，再执行：

```text
setenv httpd_ipaddr 192.168.0.1
setenv httpd_netmask 255.255.255.0
setenv httpd_dhcp 0
tyfrecovery
```

打开 **[http://192.168.0.1/](http://192.168.0.1/)**，按 [README](../README.md#安装-openwrt) 安装或恢复系统。1.4 保留 2.5G 支持，单个 PHY 初始化失败时，其余正常网口仍可提供恢复网络。

## 异常处理

| 现象 | 处理 |
|---|---|
| 准备脚本提示 SHA256 不符 | 重新下载指定的官方 **1.4 通用包** |
| 接收未完成或长度不符 | 重新 `loadb`，按 Kermit 协议发送 `.scr` |
| 预检查 `TTL STOP` | 停止，保存完整输出，不执行写入步骤 |
| 写入阶段失败或没有 `TTL WRITE OK` | 保持供电，不重启、不重复擦除，保留日志求助 |
| 无提示符、命令缺失或 `TAURUS#` | 保存启动日志，单独诊断，不套用本教程 |

在原 issue 提供完整启动日志、`version`、`nand info`、`nand bad` 和检查/写入输出，并说明是否出现过 `TTL WRITE OK`。不要只截最后一行。

验证范围：真实 U-Boot 的脚本、哈希、内存命令配合模拟 NAND 做故障回归；尚未在该 issue 的具体设备上实刷验收。
