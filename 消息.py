#!/usr/bin/env python

import subprocess
import shutil

# 缓存 termux-api 是否可用的状态
_termux_api_available = None

def _check_termux_api():
    """检查 termux-api 是否已安装"""
    global _termux_api_available
    if _termux_api_available is not None:
        return _termux_api_available

    if not shutil.which("termux-notification"):
        _termux_api_available = False
        return False

    _termux_api_available = True
    return True

def _print_install_hint():
    """打印 termux-api 安装提示（含国内镜像）"""
    print("=" * 50)
    print("[消息提醒] termux-api 未安装，无法发送通知提醒")
    print("[消息提醒] 如需新消息通知功能，请手动安装：")
    print()
    print("  # 先换国内镜像（推荐，加速下载）")
    print("  sed -i 's@^\\(deb.*stable main\\)$@#\\1\\ndeb https://mirrors.tuna.tsinghua.edu.cn/termux/termux-packages-24 stable main@' $PREFIX/etc/apt/sources.list")
    print("  apt update && apt upgrade -y")
    print()
    print("  # 安装 termux-api")
    print("  pkg install termux-api -y")
    print()
    print("  # 同时需要在手机上安装 Termux:API APP")
    print("  # F-Droid: https://f-droid.org/packages/com.termux.api/")
    print("  # 或从国内镜像下载")
    print()
    print("[消息提醒] 安装后重启程序即可生效，不安装也不影响正常使用")
    print("=" * 50)

def send_notification(title: str, message: str):
    """发送 Termux 通知提醒（收到新消息时调用）

    Args:
        title: 通知标题（如发送者昵称）
        message: 通知内容（如消息文本）
    """
    global _termux_api_available

    if not _check_termux_api():
        # 只在首次检测到未安装时提示一次
        if _termux_api_available is False:
            _termux_api_available = None  # 重置，下次还会检测
            _print_install_hint()
            _termux_api_available = False  # 标记已提示过
        return False

    try:
        subprocess.run(
            ["termux-notification", "--title", title, "--content", message],
            timeout=5
        )
        return True
    except FileNotFoundError:
        global _termux_api_available
        _termux_api_available = False
        _print_install_hint()
        return False
    except Exception as e:
        print(f"[消息提醒] 发送通知失败: {e}")
        return False

def send_toast(message: str):
    """发送 Toast 提示（短暂显示在屏幕底部）"""
    try:
        subprocess.run(["termux-toast", message], timeout=3)
        return True
    except:
        return False

def test_notification():
    """测试通知功能"""
    print("正在测试通知功能...")
    result = send_notification("测试通知", "这是一条测试消息")
    if result:
        print("✅ 通知发送成功！请查看通知栏")
    else:
        print("❌ 通知发送失败")
    return result

if __name__ == "__main__":
    test_notification()
