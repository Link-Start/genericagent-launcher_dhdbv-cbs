# mac 版本相对 Windows 的当前审查报告

审查日期：2026-04-27

## 结论

- 当前 mac 版已经不再是“只有脚手架”的状态。
- 共享 Qt 主界面、聊天、会话、远端设备、渠道、VPS、LAN Web 等大块内部功能，已经和 Windows 版走同一条主代码路径。
- 安装与分发层面的产品边界已经明确为：
  `未做 Apple Developer 签名 / 未 notarize 的 .dmg 手动安装`、`手动替换 .app 升级`、`系统 Python`、`无内部更新器`、`无 Apple Developer 签名`、`无 notarization`。
- 目前真正剩下的重点不是再补一大块新功能，而是：
  `真实 mac 设备手工 smoke`、`系统 Python 失败场景体验`、`持续回归验证`。

## 已落地

### 1. mac 打包与发布资产

- `GenericAgentLauncher.mac.spec` 会产出 `GenericAgent Launcher.app`
- `tools/build_macos_release.py` 会生成：
  - `.app`
  - `.dmg`
  - `.sha256`
  - `README-macOS.txt`
  - `install-metadata.json`
- `.github/workflows/release-installer.yml` 已包含 `build-macos` job，并会在 tag 发布时上传 macOS Release 资产

### 2. 运行时与 UI 适配

- 数据目录已切到 `~/Library/Application Support/GenericAgentLauncher`
- 关于页已有：
  - 安装状态卡片
  - 手动升级说明
  - mac 安装路径 / 数据目录排查入口
- 下载页、定位页、依赖检查页已统一到 `系统 Python` 口径
- mac 下无托盘时的悬浮窗 / 隐藏行为已做降级分流

### 3. 自动化验证

- 当前有效基线命令仍是：
  `python -m pytest tests -q`
- `macos-validate.yml` 已覆盖：
  - 测试集
  - source startup smoke
  - mac 打包
  - packaged app startup smoke
  - release 资产存在性校验

## 与 Windows 仍然不同的地方

这些差异是当前产品定义的一部分，不算 bug：

- Windows 有内部更新器、回滚、安装器；mac 没有
- Windows 发布资产以安装包 + 内部更新资产为主；mac 公开资产是双架构 `.dmg + .sha256 + README-macOS-<arch>.txt + install-metadata-<arch>.json`
- Windows 可做私有 Python 安装器；mac 当前固定使用系统 Python
- Windows 可继续走签名和安装器增强；mac 当前明确不做 Apple Developer 签名和 notarization

## 当前剩余缺口

### 1. 缺少真实 mac 设备验收记录

- 现在的自动化能证明：
  `代码存在`、`测试通过`、`能打包`、`打出来的 app 能启动 smoke`
- 但还不能替代真实用户路径验证：
  - Finder 拖拽安装
  - Gatekeeper 首次放行
  - 系统 Python 差异
  - 悬浮窗 / 无托盘行为
  - 手动替换 `.app` 升级

### 2. 系统 Python 体验仍是重点关注项

- 当前已经能自动尝试 `python3` / `python` / 手动指定的 `python_exe`
- 但真实机器上仍可能遇到：
  - 系统没有 Python
  - 多个 Python 版本并存
  - 项目依赖需要 venv
  - `uv` / `pip` 安装路径差异

### 3. 文档和人工回归需要持续跟进

- README 已改成双平台说明
- 需要按独立 checklist 持续做人工验收：
  [macos-manual-smoke-checklist.md](./macos-manual-smoke-checklist.md)

## 当前判断

如果问题是“mac 版是否还有明显没补的内部功能空洞”，当前答案是：

- 没有发现新的大块空洞
- 当前更像是 `安装收口 + 验证收口 + 文档收口` 阶段

如果问题是“mac 版是否已经和 Windows 一样拥有同等级安装器与更新体系”，答案仍然是否定的，因为这不在当前产品边界内。
