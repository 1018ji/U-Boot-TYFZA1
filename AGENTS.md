# Release 发布规则

- 所有 U-Boot Release 均保持精简，使用简洁中文介绍用户能用到的功能或实际变化。
- 首个正式版本只介绍已实现的功能，不把发布前的开发修复列为版本更新。
- 不将内部调试过程、验证流水账、免责声明式段落写入 Release；详细技术记录放在仓库文档中。
- Release 附件仅发布 `tyfza1-uboot-install.run` 和 `tyfza1-uboot-universal.bin`，分别用于安装和恢复网页升级。
- 发布工作流必须明确列出这两个附件，不得使用 `output/release/*` 等通配上传。
- 构建基线、独立刷写工具、JSON、README、许可证、版本文件、校验清单和额外源码包不作为 Release 附件上传。
- 构建基线保存在 `evidence/stock-boot/`，自动构建不得依赖 Release 的非核心附件。
