# mac 内部功能与安装收口交接记录

本文档用于记录当前 mac 版本的续接状态，方便下次直接进入真实验收或剩余修补。

## 当前范围

当前阶段已经从“只做内部功能复刻”扩展到：

- 共享 Qt 内部功能对齐
- mac 安装 / 升级入口收口
- 未做 Apple Developer 签名 / 未 notarize 的 `.dmg` 打包与发布资产闭环
- 基础 CI 验证闭环

当前仍明确不做：

- Apple Developer 账号
- Developer ID 签名
- notarization
- mac 内部更新器 / rollback / bootstrap
- mac 私有 Python 安装器

## 当前代码状态

### 1. 共享功能主链

- 聊天、会话、远端设备、渠道、VPS、LAN Web、悬浮窗等主要内部功能继续走共享 Qt 代码路径
- mac 下无托盘场景的降级逻辑已补齐
- 大多数核心按钮已经统一为“可解释禁用状态”，不再只是简单灰掉

### 2. 安装与升级口径

- 关于页已有“安装状态”卡片
- mac 更新入口已固定为“查看手动升级说明”
- 手动升级说明会指向双架构 `.dmg`、`.sha256`、`README-macOS-<arch>.txt`、`install-metadata-<arch>.json`
- README 已改成 Windows / macOS 双平台叙事

### 3. 打包与 CI

- `tools/build_macos_release.py` 会生成 `.app/.dmg/.sha256/README-macOS.txt/install-metadata.json`
- `release-installer.yml` 在公开 release 上传阶段会把 README / metadata 复制成带架构后缀的发布资产
- `release-installer.yml` 的 `build-macos` job 会发布 macOS Release 资产
- `macos-validate.yml` 会做：
  - `python -m pytest tests -q`
  - source startup smoke
  - packaged app startup smoke
  - release 资产校验

## 当前验收基线

推荐本地命令：

```bash
python -m pytest tests -q
```

推荐人工清单：

- [macos-manual-smoke-checklist.md](./macos-manual-smoke-checklist.md)
- [macos-release-runbook.md](./macos-release-runbook.md)
- [macos-smoke-report-template.md](./macos-smoke-report-template.md)

说明：

- 当前自动化已经足够覆盖“共享逻辑 + 打包 + 最小启动”
- 但它仍不能替代真实 mac 设备上的 Finder / Gatekeeper / 系统 Python 验证

## 当前还没算完全收口的部分

### 1. 真实 mac 设备人工 smoke

这是当前最高优先级的剩余项，尤其要看：

- Finder 拖入 `/Applications`（推荐）；如果只安装给当前用户，也允许放到 `~/Applications`
- `System Settings -> Privacy & Security -> Open Anyway` 首次放行
- Finder 右键 `Open` 兼容性备选路径
- system Python 自动探测
- 项目 venv 的 `venv/bin/python`
- 手动替换 `/Applications/GenericAgent Launcher.app` 升级；如果用户级安装，则替换 `~/Applications/GenericAgent Launcher.app`

### 2. 系统 Python 失败体验

虽然文案和探测逻辑已经补强，但还需要真实机器反馈确认：

- 没有 Python 时的报错是否足够直观
- 多解释器并存时是否会误选
- `uv` / `pip` 回退说明是否足够清楚

## 下次最合理的继续方式

1. 按 `macos-manual-smoke-checklist.md` 在真实 mac 设备上跑一轮
2. 把发现的问题按“阻断 / 体验 / 文案”分级修补
3. 再次跑 `python -m pytest tests -q`

如果下次没有真实 mac 设备，最合理的继续方向是：

1. 继续补系统 Python 失败场景提示
2. 继续加强基于源码的回归测试
3. 不要把范围重新扩散到 Apple Developer 签名、notarization 或内部更新器
