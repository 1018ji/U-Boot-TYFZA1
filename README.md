# TYFZA1 U-Boot

为天翼 TYFZA1 的全千兆板和带 RTL8221B 2.5G 板适配恢复引导器。参考
[pbs05/uboot-an758x](https://github.com/pbs05/uboot-an758x) 的完整网页恢复功能与前端，
移入公开 Realtek Taurus 平台代码，保留本机原厂 BL2 和 BL31。

这是独立 Git 仓库，位于 OrbStack `ubuntu2404` 的 `/home/leo/U-Boot-TYFZA1`。
与 `/home/leo/PonWRT-TYFZA1` 的固件开发分开维护，不修改该工程。

**开发中，尚未通过设备 RAM 启动、网口收发或冷启动验证。当前产物不是可刷写的完整 loader。**

## 构建与测试

Ubuntu 24.04 ARM64 已具备本轮使用的 GCC 13、make、dtc、bison、flex、OpenSSL
开发环境。构建需要联网取得两个固定公开版本；版本见 `source-lock.json`。

```sh
./scripts/build.sh
python3 tests/test_formats.py -v
```

默认工具链为 `aarch64-linux-gnu-`，可用 `CROSS_COMPILE` 指定等价工具链。
源码缓存位于 `sources/`，生成源码与编译目录在 `build/`，原型产物在 `output/prototype/`；
三者不进入 Git。手工修改生成源码会在下一次 prepare 时被覆盖，应修改 `overlay/`
或 `scripts/prepare.py`。

## 设备契约

- SoC：RTL9617CVW / Taurus / 四核 Cortex-A55，512 MiB DDR3。
- GPIO113:111 为 `000` 时选择 `conf-0` / 2.5G，`001` 时选择 `conf-1` / 全千兆；
  未识别值进入恢复流程，不猜测板型。Reset 两板均为 GPIO8 低电平有效。
- NAND 物理 `boot` 为 2 MiB；两份 FIP 起点为 `0x40000`、`0x100000`，每份预留
  `0xc0000`。不能把裸 `u-boot.bin` 直接写到 NAND 头部。
- 环境位于 `0x280000`、`0x2c0000`，`static_conf` 位于 `0x300000`，
  `ubi_device` 位于 `0x340000`、大小 `0x0f5c0000`。
- 默认网络恢复地址 `192.168.0.1`，可提供 DHCP。网口自动寻找活动链路。

## 实现进度

已实现的源码与离线证据：

- 固定 U-Boot 2026.07 参考提交与 Realtek GPL 提交，生成独立的构建树。
- Taurus 串口、内存银行、安全区域、SMC 重启、原厂成功启动状态交接。
- DM NI 网口、Cortina GPIO、SPI-NAND 的新版本 API 移植；首个完整 AArch64 链接通过。
- 两板 GPIO 选择、Reset 恢复入口、原厂 UBI/FIT 启动入口。
- 参考网页的中英文布局、备份、高级控制与 gzip 压缩资源；保留来源链接。
- 刷机页按用户要求依次展示：刷写系统、刷写 U-Boot、启动/重启、UBI 重建与板级数据。
- TYFZA1 sysupgrade tar、双 FIP loader 的实际 C 输入解析器。10 项离线测试通过，
  覆盖双板名称、越界、重叠、重复条目、损坏校验和、截断、符号链接及随机短输入。
- 网页普通系统安装已改为另一 UBI 槽写入与独立读回，全部成功后才保存启动环境。
- 网页引导器更新已改为检查完整 Taurus loader、比对本机 BL2/BL31/GPT/保留区域，
  再按 FIP1 → FIP0 的顺序擦写和读回。
- UBI 重建源码先将 `ubi_Config`、`ubi_fpga`、两份 DTB 保存到内存，按原卷 ID 建卷，
  再恢复和读回。该功能仍会清除系统数据，断电容错尚未得到设备验证。

尚未完成的要求与验证：

- 当前普通原型约 504 KiB；依据两份 stock FIP，BL33 最大空间约为 517773 / 521605 字节。
  仍须完成最终证书与完整 loader 打包；后续若新增功能超出空间，应采用经验证的 BL33
  内部解压装载，而不是扩大分区、删除恢复功能或牺牲双 FIP。
- 第五个 2.5G 端口的 PHY / SerDes 启动、链路切换和真实网络验收。
- 整片 NAND 恢复改为分段上传写入，以适应 512 MiB RAM；参考项目原有全片缓冲方式不适用。
- 上传 FIT 所有地址边界、板型匹配、RAM 启动与更新失败路径的集成测试。
- 真实 sysupgrade（12042524 字节、内核 3962920、rootfs 8068096）及两份原厂 boot
  已通过实际 C 格式解析。完整 FIT 校验和安装故障注入仍待完成。
- 证书链重建、保持原厂 BL2/BL31 的 FIP 打包与可审查安装产物。
- 中英文页面已在浏览器只读 fixture 中检查；390px 手机视口无横向溢出，刷机按钮顺序
  符合用户要求。恢复 API、NAND/UBI 故障注入和实际设备 RAM 验收仍待完成。
- 两板断电冷启动、恢复、升级失败后的回退，以及 PON/Wi-Fi/硬件加速启动回归。

## 来源与许可

本仓库新增代码为 GPL-2.0-only；各覆盖文件保留原有许可。
参考网页和恢复服务来自 `pbs05/uboot-an758x`，许可为 GPL-2.0+。
GPIO、NI、SPI-NAND 选定文件来自固定的 Realtek 公共 GPL 镜像，保留原声明。
生成寄存器描述仅在构建时从固定源码取得；未把带独立专有声明的 `ca_types.h`
搬入本项目，所需最小兼容类型在覆盖目录内自行定义。

BL2/BL31、原厂 NAND、出厂身份、校准数据和私钥不进入仓库。
当前没有设置远程仓库，也没有上传或发布。
