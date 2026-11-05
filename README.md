# 小米互联服务：阻止 Finder 拖拽时抢前台

针对 macOS 小米互联服务 **3.0.300（285）** 的四字节补丁。应用继续在后台运行，普通 Finder 文件拖拽不再触发已定位的那次强制激活。

在一台 Apple Silicon Mac 上，用户手动确认：**“不再抢前台，常用互联功能也正常。”** 这是单机验证结果，不代表所有互联功能或系统版本都已测试。

本项目为非官方修补记录和工具。仓库提供源码、分析与本地复现方法；小米应用、框架、安装包和签名证书由用户从官方渠道自行获取。

## 支持范围

| 项目 | 要求 |
| --- | --- |
| 系统 | macOS，Apple Silicon 原生 arm64 运行 |
| 应用 | 小米互联服务 / Xiaomi Interconnectivity |
| Bundle ID | `com.xiaomi.hyperConnect` |
| 版本 | **3.0.300（285）**，且可执行文件哈希完全匹配 |
| Python | **3.9+**，仅使用标准库 |
| Intel / Rosetta | 未修补、未验证 |
| 其他应用版本 | 拒绝修改，需重新分析 |

原始通用可执行文件 SHA-256：

```text
151c34a603f3e568eff7245830ad3034092cb12eb1e961cbe5ae91af33d1c259
```

## 原理

全局文件拖拽回调进入 `StatusBarController.checkProximityAndDropWindow()`。当应用不活跃时，程序会**先**调用 `NSApp.activateIgnoringOtherApps(true)`，**再**检查鼠标是否靠近菜单栏拖放区域。因此普通文件整理也可能让整个应用抢到前台。

补丁只将这一次调用替换为 ARM64 `NOP`。其余拖拽状态、距离判断、提示窗口和手动打开窗口的代码保持原样。详情见 [ANALYSIS.md](ANALYSIS.md)。

## 快速检查与准备副本

先进入本仓库目录。默认只检查，不修改任何文件：

```sh
python3 xiaomi_drag_focus_patch.py
```

如果原版在其他位置，用 `--source` 指定：

```sh
python3 xiaomi_drag_focus_patch.py --source '/path/to/小米互联服务.app'
```

准备新的测试副本，目标路径必须不存在，且位于 `/Applications` 之外：

```sh
python3 xiaomi_drag_focus_patch.py \
  --source '/Applications/小米互联服务.app' \
  --prepare "$HOME/XiaomiFocusTest/小米互联服务.app"
```

脚本校验版本、完整哈希、Mach-O 地址映射与原始指令；任何不匹配都会停止。它不覆盖原版，也不安装或启动应用。同目录会生成 `*.patch-report.json`；其中的 `runtime_tested: false` 表示**这次新生成的副本**尚未做运行测试。

**此时副本的原签名已经失效，准备成功不等于可以直接运行。** 继续使用需要阅读 [SIGNING.md](SIGNING.md)，在本机重签名并测试。

若准备中途失败，目标目录可能保留未完成的副本。不要启动它；检查错误原因并换一个新目标路径重试。脚本也会拒绝覆盖已有报告。

## 重签名的实际影响

已验证的办法使用本地 ad hoc 签名，并仅对测试副本添加 `com.apple.security.cs.disable-library-validation`，以加载原厂框架。该副本不再具有小米官方的签名与公证身份；钥匙串、登录授权和系统扩展行为可能变化。**手机摄像头扩展未验证。**

复现流程保留 hardened runtime；不需要关闭 SIP 或 Gatekeeper，也不修改系统钥匙串、TCC 数据库或嵌套系统扩展。若系统阻止启动，请停止并检查原因，不要全局关闭安全保护。

## 测试与回退

1. 保留完整官方原版，正常退出正在运行的小米互联服务。
2. 只启动重签后的测试副本，不要同时运行同一 Bundle ID 的两份应用。钥匙串等系统提示由本人阅读并决定。
3. 在 Finder 不同窗口中正常拖拽文件，确认焦点不被抢走；再检查你实际使用的互联功能。若依赖菜单栏拖放传输、手机摄像头或其他扩展，请单独测试。
4. 若只运行测试副本，回退只需正常退出副本，再启动保留的官方原版。
5. 若自行替换了 `/Applications` 中的应用，先退出修补版，将其移到其他位置保留，再把完整官方备份恢复到原位置。不要覆盖后来更新的官方新版。

官方更新后不要复用旧偏移或绕过哈希检查；先确认新版是否已经解决问题。

## 仓库内容

- [xiaomi_drag_focus_patch.py](xiaomi_drag_focus_patch.py)：版本检查、四字节补丁与副本生成。
- [ANALYSIS.md](ANALYSIS.md)：调用链、地址、指令及修改范围。
- [SIGNING.md](SIGNING.md)：本地重签名、启动测试与回退注意事项。
- [VALIDATION.md](VALIDATION.md)：实际完成的验证及未覆盖项目。

不包含小米应用二进制、原版备份、账号配置、钥匙串内容或本机专用恢复记录。
