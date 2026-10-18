## 1.0

- 适配 TYFZA1 全千兆版与 RTL8221B 2.5G 口版，提供自动识别机型的通用安装包。
- 集成中英文网页恢复、OpenWrt 安装、U-Boot 更新、备份下载和内存启动。
- 提供原厂 Telnet 与 OpenWrt 安装工具，校验本机引导数据，按 FIP1、FIP0 顺序更新并读回确认。
- 原生安装按镜像大小分配系统卷，当前 OpenWrt beta 可写数据卷约 41.6 MiB。
- 修复压缩 BL33 对齐、SPI-NAND 冷启动和恢复网络连续传输问题。

全千兆版已完成实机验证；2.5G 版完成镜像、证书、板型选择和 PHY 代码测试，实机结果待补充。

恢复功能与前端参考并感谢 [pbs05/uboot-an758x](https://github.com/pbs05/uboot-an758x)。安装与使用见 README。
