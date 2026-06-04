#!/usr/bin/env python

import subprocess

def test_toast():
    print("正在发送 Toast 通知...")
    try:
        subprocess.run(["termux-toast", "Hello from Python!"], timeout=3)
        print("✅ Toast 发送成功！请查看屏幕底部")
        return True
    except FileNotFoundError:
        print("❌ termux-toast 未找到")
        print("   请运行: pkg install termux-api")
        return False
    except Exception as e:
        print(f"❌ 失败: {e}")
        return False

def send_toast(message: str):
    try:
        subprocess.run(["termux-toast", message], timeout=3)
        return True
    except:
        return False

if __name__ == "__main__":
    send_toast("这是一条测试消息")