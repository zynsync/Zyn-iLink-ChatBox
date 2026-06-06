#!/usr/bin/env python3
import sys
import time
import random
import string
import urllib.request
import urllib.error
import threading

GITEE_RAW_URL = "https://gitee.com/zynsync/zyn-i-link-chat-box/raw/master/ZynWechatBot.enc"
VERSION_URL = "https://gitee.com/zynsync/zyn-i-link-chat-box/raw/master/version.txt"

_k1 = "Zynchat"
_k2 = "NB"
_k3 = "123456"
KEY_B = _k1 + _k2 + _k3

CURRENT_VERSION = "0"

def xor_crypt(data, key):
    key_bytes = key.encode('utf-8')
    key_len = len(key_bytes)
    result = bytearray()
    for i, byte in enumerate(data):
        result.append(byte ^ key_bytes[i % key_len])
    return bytes(result)

def fetch_file(url, timeout=10):
    timestamp = int(time.time())
    rand_str = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
    separator = '&' if '?' in url else '?'
    fresh_url = f"{url}{separator}_={timestamp}&r={rand_str}"
    
    headers = {
        'Cache-Control': 'no-cache, no-store, must-revalidate',
        'Pragma': 'no-cache',
        'Expires': '0',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    
    try:
        req = urllib.request.Request(fresh_url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                return resp.read()
    except Exception as e:
        print(f"[拉取] 失败: {e}")
    return None

def get_remote_version():
    data = fetch_file(VERSION_URL)
    if data:
        try:
            return data.decode('utf-8').strip()
        except:
            pass
    return None

def fetch_and_run():
    global CURRENT_VERSION
    
    print(f"[1/2] 拉取远程代码...", end=" ", flush=True)
    encrypted_data = fetch_file(GITEE_RAW_URL)
    if not encrypted_data:
        print("失败")
        return False
    
    print("成功！")
    
    remote_ver = get_remote_version()
    if remote_ver:
        CURRENT_VERSION = remote_ver
        print(f"[版本] v{CURRENT_VERSION}")
    
    print("正在转译...")
    try:
        decrypted = xor_crypt(encrypted_data, KEY_B)
        decrypted_str = decrypted.decode('utf-8')
        print("转译成功！正在执行...")
        print("="*40)
        exec(decrypted_str, {'__name__': '__main__'})
        return True
    except Exception as e:
        print(f"转译或执行失败: {e}")
        return False

def version_check_loop():
    global CURRENT_VERSION
    while True:
        time.sleep(30)
        remote_ver = get_remote_version()
        if remote_ver and remote_ver != CURRENT_VERSION:
            print(f"\n[更新] 发现新版本 {remote_ver} (当前 {CURRENT_VERSION})，正在更新...")
            encrypted = fetch_file(GITEE_RAW_URL)
            if encrypted:
                try:
                    decrypted = xor_crypt(encrypted, KEY_B)
                    CURRENT_VERSION = remote_ver
                    print("[更新] 成功！新代码已执行")
                except Exception as e:
                    print(f"[更新] 失败: {e}")

def main():
    print("="*50)
    print("Zynsync 代码拉取器")
    print("="*50)
    
    updater = threading.Thread(target=version_check_loop, daemon=True)
    updater.start()
    print("[更新线程] ")
    
    if not fetch_and_run():
        sys.exit(1)

if __name__ == "__main__":
    main()