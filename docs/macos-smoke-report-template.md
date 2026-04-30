# macOS Smoke Report Template

## 基本信息

- 测试日期：
- 测试人：
- 版本号：
- Commit：
- macOS 版本：
- 芯片架构：
- Python 来源：系统 Python / Homebrew / 项目 venv

## 安装验证

- [ ] 下载到 `GenericAgentLauncher-macos-<version>.dmg`
- [ ] `.sha256 / README-macOS.txt / install-metadata.json` 齐全
- [ ] Finder 中打开 dmg
- [ ] dmg 内看到 `GenericAgent Launcher.app`
- [ ] dmg 内看到 `Applications` 别名
- [ ] 成功拖入实际安装目录：`/Applications`（推荐）或 `~/Applications`
- [ ] Gatekeeper 阻拦后可通过 `System Settings -> Privacy & Security -> Open Anyway` 放行
- [ ] Finder 右键 `Open` 兼容性备选路径已验证 / 不适用

备注：

## 首次启动与环境准备

- [ ] app 从实际安装路径正常启动（默认 `/Applications`；用户级安装时为 `~/Applications`）
- [ ] 关于页“安装状态”识别正确
- [ ] 留空 `python_exe` 时能自动尝试 `python3 / python`，并覆盖常见 Homebrew 绝对路径
- [ ] 手动指定 `venv/bin/python` 可通过依赖检查
- [ ] 缺依赖场景下提示可理解

备注：

## 共享功能回归

- [ ] 会话创建 / 搜索 / 删除 / 固定
- [ ] API 保存 / 模型拉取
- [ ] 通讯渠道页打开 / 保存
- [ ] VPS / 远端设备最基础连接
- [ ] LAN Web 启停
- [ ] 无托盘场景悬浮窗 / 隐藏 / 恢复

备注：

## 升级验证

- [ ] 下载新版本 dmg
- [ ] 关闭当前 app
- [ ] 手动替换 `/Applications/GenericAgent Launcher.app`；如果用户级安装，则替换 `~/Applications/GenericAgent Launcher.app`
- [ ] 重启后版本号更新
- [ ] 用户数据仍保留

备注：

## 结论

- 结果：通过 / 不通过
- 阻断问题：
- 非阻断问题：
- 建议是否允许公开发布：
