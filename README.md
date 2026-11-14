# 神将世界 Mac 兼容工具

[下载 2.0.1 安装 DMG](https://github.com/yeezus-6324/sjsj-macos/releases/download/v2.0.1/sjsj-macos-v2.0.dmg) · [下载独立卸载工具](https://github.com/yeezus-6324/sjsj-macos/releases/download/v2.0.1/sjsj-macos-uninstaller.zip) · [发布说明](https://github.com/yeezus-6324/sjsj-macos/releases/tag/v2.0.1)

v2.0 是面向 Apple Silicon Mac 的非官方兼容性研究项目。原生窗口通过 WebKit 打开 4399 官方登录页，游戏画面由 Ruffle WebAssembly 执行。应用内的 Python 桥接只监听本机回环地址，按会话转发允许的游戏资源与连接。游戏进度和房间状态由官方服务管理。

这个版本在仓库提供兼容层源码、Ruffle 修改和本地组装方法。Mac 原生启动器沿用 v1.5 的二进制，其源码和再分发授权未在本次工作中核实。从源码重新组装完整客户端需要有权使用的本机 v1.5 输入。

- [相对 v1.5 的完整改动和测试状态](CHANGELOG.md)
- [兼容层构建与本地组装](BUILD.md)
- [依赖许可、服务和隐私风险](RISKS.md)

目标环境为 Apple Silicon、macOS 12 或更新。当前候选包采用 ad hoc 签名。新设备上的安装、登录、进服及长时间游玩仍待验证。

反馈兼容问题时请写明版本、macOS 版本、操作步骤和预期行为。上传截图或日志前，请遮住账号、角色名、聊天内容、会话参数和本机路径。
