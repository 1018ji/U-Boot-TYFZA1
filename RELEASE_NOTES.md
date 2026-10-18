## 1.0

适配 TYFZA1 全千兆版及带 RTL8221B 2.5G 口版，提供通用安装包与恢复网页升级包。

- 修复压缩 BL33 冷启动对齐和遗留看门狗问题。
- 修复 RTL8221B Clause45 访问、MDIO 超时和原厂 SerDes 等待语义，保留模式及铜口状态读回检查。
- Reset 上电请求提前锁存；进入 U-Boot 后 LAN1–LAN4 依次亮灯。
- 恢复 IP、掩码和 DHCP 服务设置可持久保存。
- 旧 OpenWrt 安装自动识别系统槽；UBI 重建保留出厂配置、FPGA、DTB 卷原位。
- 单文件安装器兼容原厂 BusyBox，先写 FIP1 再写 FIP0，每份写入后读回。
- 移除恢复网页页脚的 Based on 链接，源码许可和 README 来源说明保留。

全千兆版已有冷启动、网页刷写及系统升级实机记录。2.5G 版已确认新版启动并进入恢复网页；2.5G 协商速率与四口逐一收发仍待实测。

普通安装下载 `tyfza1-uboot-install.run`；恢复网页更新选择 `tyfza1-uboot-universal.bin`。两个 `*-boot.bin` 文件是自动构建原厂基线，不是安装包。校验值见 SHA256SUMS，安装说明见 README。
