# TYFZA1 U-Boot

为天翼 TYFZA1 全千兆版和 RTL8221B 2.5G 口版适配的 U-Boot 2026.07，提供串口、Web 恢复、系统安装、引导器更新和 NAND 备份恢复。

## 固件

`tyfza1-uboot-universal.bin` 同时包含两种机型的完整 loader。恢复页面根据 GPIO113:111 的硬件 strap 选择机型，再核对本机 GPT、BL2、BL31 和保留区域。匹配后按 FIP1、FIP0 的顺序写入，并分别读回确认。每次实际写入的是对应机型的 2 MiB boot 数据。

- 全千兆：strap `001`，FIT `conf-1`。
- 2.5G 口：strap `000`，FIT `conf-0`。
- 两版共用 U-Boot BL33，各自保留原厂 BL2、BL31、GPT 和保留区域。

## 使用

串口为 115200 8N1。启动菜单提供 Start OpenWrt 和 Web recovery；串口命令 `httpd dhcp` 进入恢复服务。

恢复地址为 `192.168.0.1`，提供 DHCP，并自动寻找活动 LAN 网口。在“刷写 U-Boot”中上传通用包；在“刷写系统”中上传 TYFZA1 `sysupgrade.bin`。系统安装会读回 kernel/rootfs，再按实际镜像大小分配 rootfs，将余下空间用于 rootfs_data，最后保存启动环境。恢复安装初始化 OpenWrt 配置，日常升级使用 OpenWrt 的 sysupgrade。

Reset 为 GPIO8，低电平有效。整片 NAND 恢复按 4 MiB 分段传输，保持坏块偏移，最后更新引导区。

## 构建

仓库位于 OrbStack Ubuntu 24.04 的 `/home/leo/U-Boot-TYFZA1`。工具链为 `aarch64-linux-gnu-`；源码版本见 `source-lock.json`。

```sh
sh scripts/build.sh
python3 scripts/package_loader.py --stock-boot /path/to/4ge-boot.bin --output output/4ge
python3 scripts/package_loader.py --stock-boot /path/to/2p5g-boot.bin --output output/2p5g
python3 scripts/package_universal.py \
    --4ge output/4ge/taurus_spi_nand_loader.img \
    --2p5g output/2p5g/taurus_spi_nand_loader.img \
    --stock-4ge /path/to/4ge-boot.bin --stock-2p5g /path/to/2p5g-boot.bin \
    --output output/universal/tyfza1-uboot-universal.bin
```

构建树在 `build/`，源码修改放入 `overlay/` 或 `scripts/prepare.py`。压缩 BL33 使用严格对齐访问，启动时搬移、解压并验证 CRC，再跳转到 U-Boot。

## 分区

boot 为 2 MiB，FIP 起点为 `0x40000`、`0x100000`，每份容量 `0xc0000`。env/env2 位于 `0x280000`、`0x2c0000`，static_conf 位于 `0x300000`；ubi_device 位于 `0x340000`，长度 `0x0f5c0000`。

身份、光学和无线校准保存在原厂 UBI 卷中。安装系统保留这些卷和另一系统槽。

## 验证

全千兆实机已验证从 Flash 冷启动、恢复网络、完整 loader 更新、安装 OpenWrt 0.8.0-alpha，以及标准 sysupgrade。可写空间、温度和通用包的实机结果见 `evidence/hardware-validation-20261018.json`。2.5G 镜像已通过格式、签名、原厂早期引导数据比对和板型选择测试，尚待该机型实机验证。

离线测试执行生产代码，覆盖 FIP、证书、通用包选择、压缩装载、恢复中断和 PHY 操作。

## 来源与许可

基于 [pbs05/uboot-an758x](https://github.com/pbs05/uboot-an758x) 的 U-Boot 和网页恢复功能，平台代码来自固定的 Realtek GPL 源码。新增代码采用 GPL-2.0-only，第三方文件保留原有许可。

原厂备份、私钥和生成文件分别保存在忽略的 inputs、keys、output 或本机交接目录中。
