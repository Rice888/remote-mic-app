# 外置 UB500 连接

这是 SayAll fork 的实验连接入口。默认仍是系统蓝牙。目标是让一台已收录的
小米遥控器通过 TP-Link UB500（USB `2357:0604`）使用现有按键映射和 ATVV
语音处理。实现不修改 EFI、OpenCore、系统驱动或内置蓝牙控制器。
其他蓝牙键盘、耳机、音箱及外置端的隔空投送不在本次支持范围内。

遵守[硬件兼容合同](HardwareCompatibilityContract.md)和
[语音音频合同](HardwareVoiceAudioContract.md)。自动化通过不等于真实硬件通过。

## 本机准备与运行

1. 先用 SayAll 的配置导出功能保存当前设置，退出官方 SayAll 和之前的外置蓝牙管理器。
   同一个 UB500 只能由一个后端占用。保留已安装的 SayAll 音频驱动。
2. 下载本功能分支源码。在 macOS「终端」中 `cd` 到解压后的仓库根目录。
   确认 `xcrun swift --version` 为 Swift 6.2 或以上；需要完整 Xcode。
3. 准备 Python 3.11 或以上，以及你之前使用的 RTL8761BU 固件目录。
   目录应包含 `rtl8761bu_fw`、`rtl8761bu_config`，或带 `.bin` 后缀的同名文件。
   本仓库不分发固件，也不自动下载其他型号固件。
4. 在仓库根目录运行下列安装命令。将两个示例路径替换为本机真实路径，保留引号：

   ```bash
   SAYALL_PYTHON="/path/to/python3.12" \
     bash scripts/install-external-bluetooth.sh "/path/to/firmware"
   ```

   后端安装到 `~/Library/Application Support/SayAll/ExternalBluetooth`，更新时保留
   `bonds.json` 配对记录。只创建用户目录中的 Python 虚拟环境、后端和固件副本；
   不需要 `sudo`。运行时不联网。脚本需要联网安装固定提交的 Bumble 和其依赖。
5. 从源码构建本地 public 测试 App：

   ```bash
   SAYALL_PRIVATE_PLATFORM_MODE=public \
   RELEASE_VARIANT=intel CONFIGURATION=debug \
   REQUIRE_SIRI_REMOTE_SIGNING=0 \
     ./scripts/build-app.sh
   ```

   这是本地开发构建，不是可分发候选。公开兼容构建不包含私有组件；
   私有功能需要维护者提供的合法依赖。分发修改版前还必须遵守
   [Logo 授权](../LOGO-LICENSE.md)与既有签名、公证流程。
   构建流程与权限说明另见[本地测试 App](LocalTestApp.md)。
6. 打开脚本产出的 `SayAll.app`。在按键页先选择原来那台小米遥控器的档案，
   再到「连接 → 小米遥控器连接方式」选择「外置 UB500」。填写遥控器地址，
   后端目录保持默认；如果安装时指定了其他目录，点击「选择后端目录」。
7. 插入 UB500，让遥控器进入配对模式（RC003 的 Home＋菜单组合以设备实际提示为准），
   点击「应用并重新连接」。内置蓝牙可保持开启。如果系统抢先连接了这台遥控器，
   在 macOS 蓝牙设置中仅忽略该遥控器，再进入配对模式；不要移除触控板等其他设备。
8. 等待 SayAll 真正显示已连接。该状态要求型号识别、HID 订阅、语音通道订阅以及
   ATVV 能力确认全部成功。之后直接使用原有按键页和语音输出设置，无须重新映射。

## 故障与回退

- 后端目录或地址无效：应用按钮不可用；确认 `.venv/bin/python3` 与 `bridge.py` 存在。
- 外置连接失败：先退出旧管理器，检查固件、USB 占用和遥控器配对模式，再用 SayAll
  原有重新连接按钮重试。本候选不会在配对失败后偷偷清除配对密钥或改用内置连接。
- 损坏/失效的外置配对记录：先退出 SayAll，再在 Finder 中将上述后端目录的
  `bonds.json` 移到废纸篓，重新进入遥控器配对模式。不要删除 macOS 蓝牙配置。
- 切回「系统蓝牙」并应用会停止外置后端、恢复原有连接流程，保留映射档案。
  遥控器可能只记住一个主机；切换控制器后可能需要重新配对，不保证无缝切换。
- 退出 fork 后可重新打开原版 SayAll；本次没有替换原版 App 或系统蓝牙驱动。

## 必须实测的矩阵

| 场景 | 通过证据 |
| --- | --- |
| 未安装后端、首次启动 | 默认系统模式；原内置路径、触控板及隔空投送正常 |
| 外置模式且后端/固件/USB 缺失 | 明确失败，无虚假已连接，不回退到内置 |
| RC003 新配对、保存后重连 | 使用独立密钥；型号正确，现有映射仍然有效 |
| 上下左右、确认、返回、电源、主页、菜单、TV、音量 | 单击、双击、长按/重复按配置执行；无双重动作和松手后重复 |
| 内置蓝牙同时开启 | 触控板与隔空功能正常，遥控器按键只执行一次 |
| Fn/Command、Fn 点按 | 按既有设置触发；需要的辅助功能和输入监控权限真实有效 |
| 连续 20 次短语音及 30 秒语音 | 真实遥控器声音经原 ATVV 解码到原虚拟麦克风，首尾完整，无串话 |
| 录音中拔掉 UB500、退出、权限撤销 | 按住状态、重复计时器和语音键释放；取消会话不混入下一段 |
| 睡眠唤醒、USB 拔插、手动重连 | 旧进程/旧代数事件无效，只有一个后端持有 USB |
| 外置关闭后切回系统 | 原系统连接和按键流程恢复；必要时重新配对 |
| UI | 默认/最小窗口，中英文、浅色/深色真实生产窗口无裁切，字号至少 12pt |

## 自动化与验证边界

```bash
"$HOME/Library/Application Support/SayAll/ExternalBluetooth/.venv/bin/python3" \
  -m unittest discover -s Tests/ExternalBluetooth -v
SAYALL_PRIVATE_PLATFORM_MODE=public swift test --disable-keychain --filter ExternalBluetoothTests
git diff --check
```

Python 回归使用固定 Bumble 版本和模拟 GATT/连接对象，验证订阅顺序、HID 边沿、
音频字节保真、独立密钥、过期密钥不静默重新配对、固定 USB 目标与溢出中止。
Swift 回归覆盖 IPC 分帧、序号、报文边界、RC003 HID 归一化、既有映射和权限撤销。

当前环境为 Linux：Python 回归与语法检查可执行；macOS Swift 构建/测试、实际 UI
截图、USB 配对、真实按键/麦克风、延迟和隔空共存尚未验证。候选保持 Draft，
上述证据补齐前不得声称达到与系统蓝牙相同的完整功能或发布为可用安装包。
日志仅记录阶段、稳定原因与计数，不记录遥控器地址、原始报告、音频或密钥。
