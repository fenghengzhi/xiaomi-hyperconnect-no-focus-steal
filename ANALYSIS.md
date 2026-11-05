# Finder 拖拽抢前台：分析与验证

本记录针对小米互联服务 **3.0.300（285）**，Bundle ID 为
`com.xiaomi.hyperConnect`。静态分析和补丁均针对通用可执行文件中的
**arm64** 部分。其他版本及 Intel / Rosetta 运行方式不在验证范围内。

## 发现

全局文件拖拽监听会进入
`StatusBarController.checkProximityAndDropWindow()`。在拖放提示窗口存在、
应用当前未激活时，该函数先调用 `NSApp.activateIgnoringOtherApps(true)`，
然后才判断鼠标是否靠近菜单栏拖放目标。

这条调用顺序解释了普通 Finder 文件拖拽也会让后台应用抢到前台的现象。
在已检查的拖拽回调及距离判断路径中，没有发现控制该激活行为的用户偏好检查。
这是对特定版本调用链的结论，不代表穷尽了整个应用的所有设置或动态调用。

## 已确认的调用链

1. `0x10075F644` 中的初始化逻辑在 `0x10075F6F8` 注册
   `NSEvent.addGlobalMonitorForEventsMatchingMask(handler)`，事件掩码为十进制
   `70`，包含 `leftMouseDown`、`leftMouseUp` 和 `leftMouseDragged`。
   block thunk `0x100766864` 转入回调 `0x10075F848`。
2. 回调处理 `NSEvent.type == 6`，即 `leftMouseDragged`。移动距离达到
   `65.0` 后，`0x100764684` 检查拖拽粘贴板的 `changeCount` 及
   `NSPasteboardTypeFileURL`。进入文件拖拽跟踪状态后，在 `0x10075FA68`
   调用 `0x10075FA94`。
3. `0x10075FA94` 对应 `checkProximityAndDropWindow()`；内嵌日志中的
   `HCMacUI/StatusBarController.swift` 和函数名支持这一识别。
   已发现的直接调用点只有上述拖拽回调中的一处。
4. 该函数有约 `0.1` 秒的节流检查。若拖放窗口已打开、鼠标离开其区域，
   则关闭窗口。否则，在拖放提示窗口存在时，检查 `self + 0xBA` 的应用
   激活状态，并在未激活时调用 `activateIgnoringOtherApps(true)`。
5. **激活之后**才计算鼠标与提示窗口的距离，与 `50.0` 阈值比较。
   鼠标足够接近时，后续路径才会打开拖放窗口。

`self + 0xBA` 的含义由两个通知处理函数确认：

```asm
; -[StatusBarController appBecameActive], 0x10075D5C0
MOV  W8, #1
STRB W8, [X0, #0xBA]
RET

; -[StatusBarController appResignedActive], 0x10075D5CC
STRB WZR, [X0, #0xBA]
RET
```

因此，该字段表示运行时的应用激活状态，而非用户可配置的开关。

## 补丁位置

| 项目 | 值 |
| --- | --- |
| arm64 虚拟地址 | `0x10075FDF4` |
| arm64 切片内文件偏移 | `0x75FDF4` |
| FAT 文件中 arm64 切片起点 | `0x1240000` |
| 通用可执行文件偏移 | `0x199FDF4` |
| 原始指令字节 | `8d 1a 0e 94`，`BL _objc_msgSend` |
| 替换指令字节 | `1f 20 03 d5`，ARM64 `NOP` |

原始通用可执行文件的 SHA-256：

```text
151c34a603f3e568eff7245830ad3034092cb12eb1e961cbe5ae91af33d1c259
```

补丁脚本同时校验应用身份、版本、完整可执行文件哈希、Mach-O 地址映射和
原始指令。此偏移不能直接套用到其他构建。重签名前，可执行文件仅上述四个
字节改变；重签名还会改变签名数据，不能据此声称最终签名产物也只差四字节。

## 相关汇编

```asm
10075FDA8 LDR  X27, [X19, #0x50]   ; dragTipWindow
10075FDAC CBZ  X27, loc_100760150
10075FDB0 LDRB W8, [X19, #0xBA]    ; isAppActive
10075FDB4 TBZ  W8, #0, loc_10075FDCC
10075FDB8 MOV  X0, X27
10075FDBC BL   _objc_retain
10075FDC0 B    loc_10075FDF8
10075FDCC ADRP X8, #_NSApp_ptr@PAGE
10075FDD0 LDR  X8, [X8, #_NSApp_ptr@PAGEOFF]
10075FDD4 LDR  X20, [X8]
10075FDD8 CBZ  X20, loc_100760D90
10075FDDC MOV  X0, X27
10075FDE0 BL   _objc_retain
10075FDE4 ADRP X8, #selRef_activateIgnoringOtherApps_@PAGE
10075FDE8 LDR  X1, [X8, #selRef_activateIgnoringOtherApps_@PAGEOFF]
10075FDEC MOV  X0, X20
10075FDF0 MOV  W2, #1
10075FDF4 BL   _objc_msgSend        ; 补丁将此调用替换为 NOP
10075FDF8 ADRP X8, #selRef_frame@PAGE
10075FDFC LDR  X1, [X8, #selRef_frame@PAGEOFF]
10075FE00 MOV  X0, X27              ; 覆盖激活调用未使用的返回寄存器
10075FE04 BL   _objc_msgSend        ; dragTipWindow.frame
10075FE18 FMOV D0, D10              ; 鼠标坐标
10075FE1C FMOV D1, D9
10075FE30 BL   sub_100766898        ; 计算点到矩形的距离
10075FE3C FCMP D0, D1               ; 阈值 50.0
10075FE40 B.LS loc_100760140
```

## 修改范围与静态依据

被跳过的方法返回 `void`，其后在下一次消息调用前重新设置 `X0`。
补丁保留前面的 `objc_retain(dragTipWindow)`、后续释放路径、栈平衡、节流、
拖拽状态及距离判断逻辑。它只跳过这一处主动激活调用，没有替换整个函数，
也没有全局拦截 `NSApplication` 激活。

以下窗口调用保持原样：

- `showDragTip()`（`0x10075F044`）在 `0x10075F250` 使用
  `orderFrontRegardless` 显示菜单栏提示；该函数内未发现 `NSApp` 激活调用。
- `showDragWindow()`（`0x100763020`）在 `0x100763100` 使用
  `makeKeyAndOrderFront`。
- `DragDropWindow.show(relativeTo:)`（`0x10070B878`）在 `0x10070BA4C`
  使用 `orderFrontRegardless`。

保留这些调用意在维持用户主动拖向菜单栏时的交互，但其保留本身不能证明
完整的拖放传输功能已通过运行验证。

另外检查了 arm64 中 `activateIgnoringOtherApps` 选择器的全部四处静态
代码引用：

| 调用地址 | 所属路径 | 处理 |
| --- | --- | --- |
| `0x10075FDF4` | 文件拖拽距离检查 | 替换为 NOP |
| `0x100615BFC` | `PrivacyAlertCoordinator.tryPresentAlertOnMac(viewModel:)` | 保留 |
| `0x1006F3444` | `DownloadDMGViewModel` 相关对话框 | 保留 |
| `0x100786428` | `NSAlert` 展示 | 保留 |

在本次检查的拖拽路径中没有发现第二处无条件的 `NSApp` 激活调用。
静态引用检查不能排除整个应用中所有可能的动态分派行为。

## 后续运行验证

静态分析完成后，在一台 Apple Silicon Mac 上对修补副本进行了本地重签名
和运行测试。签名校验 `codesign --verify --deep --strict` 通过；用户自行
处理钥匙串授权提示后，界面显示手机通过局域网连接。

用户手动验证后的反馈为：

> 不再抢前台，常用互联功能也正常

同一测试产物随后用于本机安装，并成功重新启动、显示局域网连接。
这是一台机器上的人工确认，不是覆盖全部功能、设备或系统版本的测试。

尚未独立验证：

- 手机摄像头系统扩展。
- Intel / Rosetta 运行；x86_64 切片未修补。
- 主动将文件拖到菜单栏目标后的完整传输流程。

## 签名与适用限制

修改可执行文件会使原签名失效。上述运行测试使用本地 ad hoc 签名，并仅对
测试副本设置 `com.apple.security.cs.disable-library-validation`，以载入
原厂框架；保留其余 hardened runtime 保护。主程序签名移除了原厂的
team/application identity 以及 `system-extension.install` entitlement，
副本中的主程序 provisioning profile 也已移出。

因此，修补副本不再具有小米官方签名身份，涉及签名身份的钥匙串授权及系统
扩展能力可能变化。测试没有关闭 SIP 或 Gatekeeper，也没有修改系统钥匙串
或 TCC 数据库。

官方更新会改变程序字节或签名。每个新版本都需要重新分析及验证，不能仅
修改版本判断或跳过哈希检查来复用本补丁。
