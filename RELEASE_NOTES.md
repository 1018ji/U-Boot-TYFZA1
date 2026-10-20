## 1.1

- 修复部分同型号设备因 GPT 标识不同，安装或更新 U-Boot 时误报 `profile do not match` 的问题。
- 增加 GPT 头和分区表的 CRC 校验，拒绝损坏的启动分区数据。

下载：`tyfza1-uboot-install.run` 用于安装；`tyfza1-uboot-universal.bin` 用于恢复网页更新 U-Boot。用法见 [安装指南](https://github.com/LeoooChen/U-Boot-TYFZA1#安装)。
