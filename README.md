# TYFZA1 U-Boot

本项目的恢复功能与网页前端参考 [pbs05/uboot-an758x](https://github.com/pbs05/uboot-an758x)，并针对天翼 TYFZA1 的全千兆版和 RTL8221B 2.5G 口版完成平台适配。感谢原项目提供的恢复功能、前端设计和开源实现。

[![Release](https://img.shields.io/github/v/release/LeoooChen/U-Boot-TYFZA1)](https://github.com/LeoooChen/U-Boot-TYFZA1/releases)
[![Build](https://github.com/LeoooChen/U-Boot-TYFZA1/actions/workflows/build.yml/badge.svg)](https://github.com/LeoooChen/U-Boot-TYFZA1/actions/workflows/build.yml)
[![License](https://img.shields.io/badge/license-GPL--2.0-blue)](COPYING)

基于 U-Boot 2026.07，为 TYFZA1 提供独立的启动与恢复环境。

- **一个通用包**：自动识别全千兆版和 2.5G 口版，选择对应的早期引导镜像。
- **网页恢复**：中英文界面，支持系统安装、U-Boot 更新、备份下载和内存启动。
- **原生 OpenWrt 引导**：自动选择板型及系统槽，支持 TYFZA1 sysupgrade 镜像。
- **双份引导更新**：先更新 FIP1，再更新 FIP0，每块写入后读回校验。
- **维护工具**：环境变量、串口命令、分区写入和分段整片恢复。

## 下载

从 [Releases](https://github.com/LeoooChen/U-Boot-TYFZA1/releases/latest) 下载 **`tyfza1-uboot-install.tar.gz`**。安装包包含静态刷写工具、通用镜像、校验文件和使用说明。

| 文件 | 用途 |
| --- | --- |
| `tyfza1-uboot-install.tar.gz` | 从原厂系统或 OpenWrt 安装 |
| `tyfza1-uboot-universal.bin` | 已安装本项目 U-Boot 后，通过恢复网页更新 |
| `tyfza1-flash-uboot` | ARM64 Linux 静态刷写工具 |
| `SHA256SUMS` | 发布文件 SHA-256 校验值 |

| 机型 | 硬件识别 | OpenWrt FIT 配置 |
| --- | --- | --- |
| 全千兆版 | GPIO113:111 = `001` | `conf-1` |
| RTL8221B 2.5G 口版 | GPIO113:111 = `000` | `conf-0` |

Linux 安装工具比对本机 GPT、BL2、BL31 和保留区域，选出匹配镜像；恢复网页先读取硬件 strap，再执行同样的镜像检查。两版共用同一份 U-Boot BL33。

## 从原厂系统安装：Telnet

### 1. 登录 root

电脑用网线连接 LAN 口，打开 [原厂 Telnet 开启页面](http://192.168.1.1:8080/CCOM/OpenTelnet.asp)，然后在电脑终端连接：

```sh
telnet 192.168.1.1
```

原厂默认用户名、密码均为 `telnetadmin`。登录后执行 `su`，再次输入 `telnetadmin`。地址或密码已修改时，使用实际配置。

### 2. 传入安装包

在电脑上下载并解压安装包，也可以用电脑提供 HTTP 下载，以兼容原厂 wget。在安装包所在目录运行：

```sh
python3 -m http.server 8000
```

在光猫的 root 终端中执行，把示例地址 `192.168.1.2` 换为电脑的 LAN 地址：

```sh
cd /tmp
wget -O tyfza1-uboot-install.tar.gz http://192.168.1.2:8000/tyfza1-uboot-install.tar.gz
mkdir tyfza1-uboot
cd tyfza1-uboot
tar -xzf ../tyfza1-uboot-install.tar.gz
sha256sum -c SHA256SUMS
```

也可将安装包复制到 U 盘，挂载后在 `/tmp/tyfza1-uboot` 中解压。

### 3. 校验并写入

```sh
chmod +x tyfza1-flash-uboot
./tyfza1-flash-uboot --check tyfza1-uboot-universal.bin
./tyfza1-flash-uboot tyfza1-uboot-universal.bin
```

工具显示识别的机型、选中镜像的 SHA-256，以及当前 boot 分区备份文件名。出现 `FIP1 written and read back.`、`FIP0 written and read back.` 和 `U-Boot installed.` 即完成。

将生成的 `tyfza1-boot-backup-*.bin` 保存到电脑，再执行 `reboot`。写入过程中保持供电。

## 从 OpenWrt 安装

使用支持 boot 分区更新的 [PonWRT 0.8.0-beta](https://github.com/LeoooChen/PonWRT-TYFZA1/releases/tag/v0.8.0-beta) 或后续版本。通过 SSH 登录 root：

```sh
ssh root@192.168.1.1
cd /tmp
wget -O tyfza1-uboot-install.tar.gz \
  https://github.com/LeoooChen/U-Boot-TYFZA1/releases/download/v1.0/tyfza1-uboot-install.tar.gz
mkdir tyfza1-uboot
cd tyfza1-uboot
tar -xzf ../tyfza1-uboot-install.tar.gz
sha256sum -c SHA256SUMS
chmod +x tyfza1-flash-uboot
./tyfza1-flash-uboot --check tyfza1-uboot-universal.bin
./tyfza1-flash-uboot tyfza1-uboot-universal.bin
```

保存生成的 boot 备份后重启。安装工具会在任何擦除之前检查机型、证书、分区几何参数、写权限和两个 FIP 区域的坏块。

## 进入恢复网页

1. 断开光猫电源，将电脑连接任意 LAN 口，电脑网卡设为自动获取地址。
2. **按住 Reset 键后接通电源**，保持按住，直到电脑获得地址并能打开恢复页面，然后松开。
3. 访问 **[http://192.168.0.1](http://192.168.0.1/)**。

恢复服务提供 DHCP。也可给电脑手动设置 `192.168.0.2/24`。若使用串口，参数为 **115200、8N1**；开机菜单选择 **Web recovery**，或在 `TYFZA1#` 提示符执行：

```text
httpd dhcp
```

Reset 在启动阶段检测；日常正常开机选择 **Start OpenWrt**。

## 刷入 OpenWrt

1. 下载 [PonWRT-TYFZA1](https://github.com/LeoooChen/PonWRT-TYFZA1/releases/latest) 的 `sysupgrade.bin`。
2. 在恢复网页的“刷机 → 刷写系统”中选择文件，点击“上传并刷写”。
3. 等待任务完成，再点击“启动系统”。
4. 电脑重新获取地址后，访问 **[http://192.168.1.1](http://192.168.1.1/)**。

首次安装选择原厂当前槽以外的系统槽，并记录为 OpenWrt 槽；后续恢复安装重复使用该槽。恢复安装校验镜像、写入并读回 kernel/rootfs，然后按实际系统镜像大小分配 rootfs，将系统槽余下空间分给 rootfs_data。以当前 beta 镜像为例，可写数据卷约 **41.6 MiB**，空白文件系统可用约 **34.6 MiB**。

恢复安装会初始化 OpenWrt 配置。之后日常升级可在 LuCI“系统 → 备份与更新”上传固件，或执行：

```sh
sysupgrade /tmp/sysupgrade.bin
```

## 备份与维护

| 页面功能 | 行为 |
| --- | --- |
| 刷写 U-Boot | 上传通用包，自动识别、校验并更新双份 FIP |
| 下载备份 | 下载选定 MTD、UBI 卷或整片 NAND 的主数据 |
| 内存启动 | 上传适用于 TYFZA1 的 FIT 镜像 并从 RAM 启动 |
| 环境变量 | 读取、修改并持久化 U-Boot 环境 |
| 命令控制台 | 执行 U-Boot 命令，显示返回值和输出 |
| 分区写入 | 按所选 MTD/UBI 目标写入并校验 |
| 恢复整片 Flash | 按 4 MiB 分段恢复备份，保留坏块偏移，最后更新引导区 |
| 重建 UBI | 重建系统卷，备份并恢复支持的本机出厂数据卷 |
| 清除坏块标记 | 擦除整片 NAND，包含出厂坏块标记，供维修使用 |

MTD 备份按物理偏移保存，坏块区域填充 `FF`，文件不包含 OOB。整片恢复需要与 Flash 容量相同的本机主数据备份。身份、认证和校准数据应使用本机备份。

系统安装保留原厂身份、光学及无线校准数据和另一系统槽。boot 分区为 2 MiB，更新范围仅包括 `0x40000` 和 `0x100000` 起始的两份 FIP，各占 `0xc0000`；GPT、保留区域、env/env2 和原厂配置卷保持原有内容。

## 构建

源码版本锁定在 [source-lock.json](source-lock.json)。Ubuntu 24.04 ARM64 可安装以下依赖：

```sh
sudo apt-get install build-essential gcc-aarch64-linux-gnu binutils-aarch64-linux-gnu \
  device-tree-compiler flex bison libssl-dev python3-cryptography python3-dev \
  python3-pyelftools python3-setuptools swig libgnutls28-dev uuid-dev qemu-system-arm
sh scripts/build.sh
```

将已校验的两版原厂 boot 基线放入 `inputs/4ge-boot.bin`、`inputs/2p5g-boot.bin`。官方自动构建从固定的 `build-inputs-v1` 资源获取并检查 SHA-256。然后执行：

```sh
sh scripts/package_release.sh
python3 -m unittest discover -s tests -p 'test_*.py'
python3 scripts/test_sandbox_crypto.py
```

产物位于 `output/release/`。提交到 `main` 自动构建并保存产物；推送与 `VERSION` 对应的 `v1.0` 标签后，发布为普通 GitHub Release。

## 验证

全千兆实机已验证 Flash 冷启动、恢复网络、通用包更新、OpenWrt 安装和标准 sysupgrade；存储和温度结果见 [实机记录](evidence/hardware-validation-20261018.json)。2.5G 版已完成镜像格式、证书链、原厂早期引导数据、板型选择及 PHY 操作测试，实机验证待补充。

离线测试执行生产代码，覆盖压缩 BL33 对齐、证书拒绝、双份 FIP 写入顺序、读回失败、坏块与恢复中断。

## 来源与许可

- [pbs05/uboot-an758x](https://github.com/pbs05/uboot-an758x)：U-Boot、恢复功能及网页前端参考。
- [jameywine/GPL-for-GP3000](https://github.com/jameywine/GPL-for-GP3000)：Realtek GPL 平台代码。
- 新增代码采用 **GPL-2.0-only**，第三方文件保留原有许可，详见 [COPYING](COPYING)。
