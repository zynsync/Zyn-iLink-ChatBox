#!/usr/bin/env python

import subprocess

_install_hint_shown = False

def _print_install_hint():
    global _install_hint_shown
    if _install_hint_shown:
        return
    _install_hint_shown = True

    print("=" * 50)
    print("[消息提醒] termux-api 未安装，无法发送 Toast 提醒")
    print("[消息提醒] 如需新消息提醒功能，请手动安装：")
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
    print()
    print("[消息提醒] 安装后重启程序即可生效，不安装也不影响正常使用")
    print("=" * 50)

def send_toast(message: str):
    try:
        subprocess.run(["termux-toast", message], timeout=5, check=True)
        return True
    except FileNotFoundError:
        _print_install_hint()
        return False
    except subprocess.CalledProcessError as e:
        print(f"[消息提醒] termux-toast 调用失败: {e}")
        _print_install_hint()
        return False
    except Exception as e:
        print(f"[消息提醒] Toast 发送失败: {e}")
        return False

def test_toast():
    print("正在发送 Toast 通知...")
    result = send_toast("这是一条测试消息")
    if result:
        print("✅ Toast 发送成功！请查看屏幕底部")
    else:
        print("❌ Toast 发送失败")
    return result

if __name__ == "__main__":
    test_toast()
