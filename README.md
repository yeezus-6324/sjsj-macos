# 神将世界 macOS 客户端

这是一个面向 Apple Silicon Mac 的《神将世界》兼容客户端。它把 4399 登录和游戏画面放在同一个 macOS 窗口里，使用内置的 Ruffle 运行原游戏的 Flash 资源（SWF）。游玩需要联网，使用原有的 4399 账号登录并连接游戏服务器。

[下载 v1.5 DMG](https://github.com/yeezus-6324/sjsj-macos/releases/download/v1.5/sjsj-macos-v1.5.dmg) · [查看发布记录](https://github.com/yeezus-6324/sjsj-macos/releases)

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
- **界面兼容补丁**针对经校验的资源版本，处理 Ruffle 中部分面板和弹窗的边框、底板拉伸，以及部分输入框的背景显示。官网资源版本不匹配时，客户端使用原资源。

安装包不含玩家登录数据。登录后，WebKit 可能在当前 Mac 保存会话和 Cookie，以便下次使用。公共游戏资源可缓存在磁盘上，重新打开 App 时可以复用。缓存设有容量上限，并会清理长期未使用的资源。角色和游戏进度仍由原游戏服务器管理。

DMG 内附「清理神将世界-1.5.command」。双击运行可清理当前 macOS 账户的客户端登录数据和缓存，默认保留 App。

## v1.5 更新

- 扩展九宫格渲染适配，改善 GP 面板、决斗王赛季胜率界面及部分弹窗的边框和底板显示。
- 修正商城购买数量等输入框的背景显示，这些输入框共用同一套皮肤修复。
- 新增公共游戏资源磁盘缓存，重启客户端后可复用已下载的资源。

武魂详情提示框定位、玩家头顶文字清晰度和聊天表情底板仍有待改进。完整更新说明及 DMG 的 SHA-256 校验值见 [v1.5 发布页](https://github.com/yeezus-6324/sjsj-macos/releases/tag/v1.5)。

## 反馈问题

可以在 [Issues](https://github.com/yeezus-6324/sjsj-macos/issues) 反馈。请注明客户端版本、macOS 版本、发生问题的界面以及复现步骤。截图请遮住账号、角色名和聊天信息。
