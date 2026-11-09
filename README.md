# 神将世界 macOS 客户端

这是一个面向 Apple Silicon Mac 的《神将世界》兼容客户端。它把 4399 登录和游戏画面放在同一个 macOS 窗口里，使用内置的 Ruffle 运行原游戏的 Flash 资源（SWF）。游玩需要联网，使用原有的 4399 账号登录并连接游戏服务器。

[下载 v1.4 DMG](https://github.com/yeezus-6324/sjsj-macos/releases/download/v1.4/sjsj-macos-v1.4.dmg) · [查看发布记录](https://github.com/yeezus-6324/sjsj-macos/releases)

## 安装与游玩

1. 在 Apple Silicon Mac 上下载 DMG，打开后把「神将世界」拖到「应用程序」。
2. 打开 App，在窗口中的 4399 登录页面完成登录。
3. 选择区服，等待客户端加载游戏资源并进入游戏。

- **支持的机型与系统**：Apple Silicon Mac，macOS 12 或更高版本。Intel Mac 未列入支持范围。
- **额外依赖**：无。Ruffle 已随 App 提供。Adobe Flash Player 和 Rosetta 2 都不需要安装。
- **首次打开**：当前 DMG 未通过 Apple 公证，macOS 可能显示 Gatekeeper 提示。

## 客户端如何运行

- **登录**由 App 内的 WebKit 窗口加载 4399 官方页面完成。
- **游戏画面**由内置 Ruffle 加载原游戏 SWF，在客户端窗口内运行。
- **资源和连接**由仅监听本机回环地址的桥接服务转发。游戏素材仍从线上获取，首次进入和切换场景时可能需要等待下载。
- **界面兼容补丁**针对经校验的资源版本，处理 Ruffle 中部分弹窗底板和边框的拉伸。官网资源版本不匹配时，客户端使用原资源。

安装包不含玩家登录数据。登录后，WebKit 可能在当前 Mac 保存会话和 Cookie，以便下次使用。游戏资源在 App 运行期间使用内存缓存，完全退出后清空。角色和游戏进度仍由原游戏服务器管理。

## v1.4 更新

- 修正武魂转生「封印加点」底板，以及器灵和铭文面板的边框缩放。
- 调整「心法强化等级套装」提示框和共用的「获取途径」弹窗，包括「获取军功」。
- 修正房间密码弹窗外框，以及 GP 一键扫荡弹窗的外框和内底板。

玩家头顶文字清晰度和聊天表情底板仍有待改进。完整更新说明及 DMG 校验值见 [v1.4 发布页](https://github.com/yeezus-6324/sjsj-macos/releases/tag/v1.4)。

## 反馈问题

可以在 [Issues](https://github.com/yeezus-6324/sjsj-macos/issues) 反馈。请注明客户端版本、macOS 版本、发生问题的界面以及复现步骤。截图请遮住账号、角色名和聊天信息。
