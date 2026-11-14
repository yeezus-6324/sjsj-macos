# 本地构建

## 一、编译 Ruffle

基线为 Ruffle 九宫格提交 [2968d373d535ac7f57acd9de32e1582003edfe12](https://github.com/ruffle-rs/ruffle/commit/2968d373d535ac7f57acd9de32e1582003edfe12)。下载该提交的源码归档后解压至独立目录。历史构建使用 Rust 1.99.1、wasm32-unknown-unknown、Temurin Java 21、Node 24.11.1 和 wasm-bindgen 0.2.127。下列命令在 Ruffle 源码根目录运行，`project_dir` 指向本仓库。

```sh
git apply --check "$project_dir/ruffle/v2.0.patch"
git apply "$project_dir/ruffle/v2.0.patch"
export RUSTFLAGS="--remap-path-prefix=$(pwd -P)=/sjsj-build/ruffle"
export CARGO_PROFILE_RELEASE_LTO=false
export CARGO_PROFILE_RELEASE_CODEGEN_UNITS=16
export CARGO_PROFILE_RELEASE_OPT_LEVEL=1
cd web
npm ci --ignore-scripts
npm run build --workspace=ruffle-core
npm run build --workspace=ruffle-selfhosted
```

运行时输出为 `web/packages/selfhosted/dist`。以上步骤以功能重建为目标，输出哈希受工具链和构建元数据影响。

## 二、本地组装 App

需要 Apple Silicon Mac、合法取得的 v1.5 App 和用于本地构建的依赖告知目录。组装器从该 App 读取原生启动器和 Python 运行时。对 v1.5 的二进制依赖意味着这个仓库尚无法从零构建原生启动器。

依赖目录须提供 `Ruffle-Web-LICENSE.md`（本仓库 `ruffle/WEB-LICENSE.md` 的副本）、与输入运行时匹配的 `OpenSSL-LICENSE.txt`（当前本地包用 OpenSSL 3.5.8），以及 `SQLite-copyright.html`（[SQLite 版权说明](https://sqlite.org/copyright.html)）。Python 许可证和 Ruffle 的 Apache、MIT 告知由构建脚本从输入复制。

```sh
python3 compat/build.py "/path/to/v1.5/神将世界.app" "/path/to/new-output" \
  --runtime "/path/to/ruffle/web/packages/selfhosted/dist" \
  --compat --retina-single-sample --sliced-reclaim \
  --distribution-notices "/path/to/notices" --release-version 2.0 --name 神将世界
```

输出包含 `神将世界.app` 和文件校验表。组装脚本验证签名，拒绝 SWF、delta 等不应随 App 分发的资源。个人本地头像需要用明确来源的 ICNS 并显式传入 `--personal-icon`。

## 三、自动化测试

在 `compat/` 下运行 `python3 -B -m unittest test_bridge test_freeze_diagnostics`。该套件以隔离测试环境检查缓存、会话与转发。原版登录、进服和界面回归需要实际 Mac 环境与可用的官方服务。
