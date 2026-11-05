# 在本机重签名测试副本

修改可执行文件会使官方签名失效。下面记录此次实际采用的方式，供理解 macOS 签名影响的用户复现。请先阅读 [README](README.md) 中的适用范围和限制，并保留完整原版。

该流程只处理已经生成的测试副本，不自动安装、运行或改变系统安全设置。原厂嵌套框架和系统扩展保持原样；只重签主应用。不要使用 `codesign --deep --sign`。

## 1. 准备

从仓库目录执行。这里假设官方原版仍位于 `/Applications`，且 README 中的准备命令已经成功：

```sh
xiaomi_original='/Applications/小米互联服务.app'
xiaomi_copy="$HOME/XiaomiFocusTest/小米互联服务.app"
xiaomi_signing="$HOME/XiaomiFocusTest/signing"
```

如果使用另一份官方备份，将 `xiaomi_original` 改为对应路径。`xiaomi_signing` 必须是新的目录。

## 2. 校验副本并生成签名配置

以下代码校验原版及未重签副本的完整可执行文件哈希，从官方原版读取 entitlements，仅移除三项原厂身份/安装扩展权限并添加本进程的动态库校验例外。主应用原有的 provisioning profile 会移到旁边保存。

```sh
python3 - "$xiaomi_original" "$xiaomi_copy" "$xiaomi_signing" <<'PY'
import hashlib
from pathlib import Path
import plistlib
import subprocess
import sys

original, copy, support = [Path(p).resolve() for p in sys.argv[1:]]
exe = Path('Contents/MacOS/小米互联服务')
expected_original = '151c34a603f3e568eff7245830ad3034092cb12eb1e961cbe5ae91af33d1c259'
expected_copy = '8330eafe40320871df98d753a47de26f057451dfa2385760c1f5ecd15ff9b64c'
if copy == original or copy.is_relative_to(original) or copy.is_relative_to(Path('/Applications')):
    raise SystemExit('测试副本必须独立于原版，且位于 /Applications 之外。')
if support.is_relative_to(original) or support.is_relative_to(copy):
    raise SystemExit('签名配置目录必须位于应用包之外。')
for app, expected in [(original, expected_original), (copy, expected_copy)]:
    if hashlib.sha256((app / exe).read_bytes()).hexdigest() != expected:
        raise SystemExit('原版或未重签副本哈希不匹配，停止。')
subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(original)], check=True)
result = subprocess.run(
    ['/usr/bin/codesign', '-d', '--entitlements', ':-', str(original)],
    check=True, capture_output=True,
)
entitlements = plistlib.loads(result.stdout)
for key in (
    'com.apple.application-identifier',
    'com.apple.developer.team-identifier',
    'com.apple.developer.system-extension.install',
):
    entitlements.pop(key, None)
entitlements['com.apple.security.cs.disable-library-validation'] = True
support.mkdir(parents=True, exist_ok=False)
(support / 'original-entitlements.plist').write_bytes(result.stdout)
(support / 'test-entitlements.plist').write_bytes(plistlib.dumps(entitlements))
profile = copy / 'Contents/embedded.provisionprofile'
if profile.exists():
    profile.rename(support / 'original-main.provisionprofile')
print('已准备测试签名配置。原版保持不变。')
PY
```

上一步必须成功后，才继续：

```sh
codesign --force --sign - --options runtime --timestamp=none \
  --entitlements "$xiaomi_signing/test-entitlements.plist" \
  "$xiaomi_copy"
```

签名成功后再验证：

```sh
codesign --verify --deep --strict "$xiaomi_copy"
codesign -d --verbose=4 "$xiaomi_copy"
```

应看到 ad hoc 签名及 hardened runtime 标志。`codesign --verify` 通过仅说明签名结构完整，**不代表官方信任、公证、Gatekeeper 放行或所有功能可用**。重签会修改签名数据，因此重签后可执行文件的 SHA-256 不再等于上面的未重签副本哈希。

## 3. 启动并手动验证

正常退出所有小米互联服务实例后，从 Finder 打开测试副本。不要同时运行原版和副本。若出现钥匙串或其他授权提示，请自行阅读和处理；不要把密码写入脚本。

检查普通 Finder 拖拽、后台连接及自己常用的互联功能，再决定是否替换安装位置。菜单栏拖放传输与手机摄像头扩展应分别测试。发生异常时，正常退出测试副本并重新启动官方原版即可。

## 权限变化

| 项目 | 处理 |
| --- | --- |
| 主应用签名 | 本地 ad hoc，失去原厂签名身份 |
| Hardened runtime | 保留 |
| 主应用动态库校验 | 仅该副本通过 entitlement 放宽 |
| 原厂 team/application identity | 从测试签名移除 |
| `system-extension.install` | 从测试签名移除，扩展安装能力不保证 |
| 嵌套框架及系统扩展 | 不修改、不重签 |
| SIP、Gatekeeper、TCC/钥匙串数据库 | 不修改 |

如果系统阻止启动，停止使用该副本并检查原因。不要删除 quarantine 属性或全局关闭安全保护来强行运行。
