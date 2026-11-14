# 风险与授权

- **游戏素材与标识**。仓库内容为兼容层源码、Ruffle 修改及文档，省去游戏 SWF、增量补丁、原画、图标和历史安装包。项目名称用于说明兼容目标。项目属于第三方，运行过程依赖 4399 服务。[《中华人民共和国著作权法》](https://www.ncac.gov.cn/xxfb/flfg/flfg_532/202103/t20210309_50530.html)
- **原生启动器与头像**。本地候选复用了 v1.5 的原生启动器和 Python 运行时。必须核实启动器及相关打包组成的再分发权限。个人头像来源为用户提供的插画改编，公开发行前还需要确认原画改编及再分发权限。公开发布的 DMG 使用 AI 生成的绿发角色图标。
- **官方服务**。登录依赖原官方页面，游戏资源、进度和玩法由官方服务控制。运营方可以调整接口、服务器和账号规则。当前公开条款未提供这个项目的明确授权，发布源码或使用免责声明不能取得接入或再分发权限。[4399 通行证用户服务协议](https://ptlogin.4399.com/www_resource/protocol.html)
- **本地数据**。源码不附账号、密码、会话、诊断日志或素材缓存。运行后，WebKit 可能在本机保留登录会话，桥接会缓存符合条件的公用资源。诊断构建只应用于本地排查。分享诊断之前应检查其中的请求、路径及账户标识。
- **苹果分发**。当前本地候选使用 ad hoc 签名。正式站外分发需视适用条件采用 Developer ID Application、Hardened Runtime 及 Apple 公证，并在干净设备上测试。Apple 公证的范围是软件安全和签名检查。 [Apple 公证说明](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution)
- **上游许可证**。Ruffle 根目录及 Web 许可证保留在 [ruffle/](ruffle/)。本地组装包还包含 Python、OpenSSL、SQLite 的告知文件。项目层未额外授予原版游戏或个人插画的权利。
