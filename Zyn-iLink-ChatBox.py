import threading
import time
import json
import uuid
import base64
import random
import sys
import subprocess
import os
import hashlib
import struct
import shutil

try:
    from Crypto.Cipher import AES as _CryptoAES
    _HAS_PYCRYPTODOME = True
except ImportError:
    _HAS_PYCRYPTODOME = False
from pathlib import Path
from typing import Optional, Dict, List, Union
from datetime import datetime
import io
import socketserver
from http.server import SimpleHTTPRequestHandler
import select
import urllib.request
import urllib.error
import urllib.parse

def is_termux():
    if sys.platform != "linux":
        return False
    
    checks = [
        "termux" in sys.prefix.lower(),
        "com.termux" in sys.prefix.lower(),
        "termux" in sys.executable.lower(),
        "com.termux" in sys.executable.lower(),
    ]
    
    if os.environ.get("TERMUX") or os.environ.get("PREFIX", "").startswith("/data/data/com.termux"):
        return True
    
    termux_paths = [
        "/data/data/com.termux",
        "/data/data/com.termux/files/usr/bin/python",
    ]
    for path in termux_paths:
        try:
            if os.path.exists(path):
                return True
        except Exception:
            pass
    
    return any(checks)

def setup_termux_compat():
    if not is_termux():
        return
    
    print("=" * 60)
    print("[Zyn] 检测到 Termux 环境")
    print("[Zyn] 正在启用兼容模式...")
    print("=" * 60)
    
    env_vars = {
        'TMPDIR': '/data/data/com.termux/files/usr/tmp',
        'TEMP': '/data/data/com.termux/files/usr/tmp',
        'TMP': '/data/data/com.termux/files/usr/tmp',
        'TERMUX': '1',
        'LD_LIBRARY_PATH': '/data/data/com.termux/files/usr/lib',
        'PATH': '/data/data/com.termux/files/usr/bin:' + os.environ.get('PATH', ''),
    }
    
    for key, value in env_vars.items():
        os.environ.setdefault(key, value)
        print(f"[TERMUX]   ✓ 设置 {key}")
    
    tmp_dir = Path("/data/data/com.termux/files/usr/tmp")
    try:
        tmp_dir.mkdir(parents=True, exist_ok=True)
        print(f"[TERMUX]   ✓ 确保临时目录存在: {tmp_dir}")
    except Exception as e:
        print(f"[TERMUX]   ⚠ 无法创建临时目录: {e}")
    
    tools = ["pkg", "python", "pip"]
    for tool in tools:
        if shutil.which(tool):
            print(f"[TERMUX]   ✓ {tool} 可用")
        else:
            print(f"[TERMUX]   ⚠ {tool} 未找到")
    
    print("[TERMUX] 兼容性设置完成")
    print("=" * 60)

setup_termux_compat()

def ensure_pip_available():
    if is_termux():
        print("[Zyn] 检测到 Termux 环境，尝试使用 pkg 安装 pip...")
        try:
            subprocess.check_call(["pkg", "install", "-y", "python-pip"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print("[TERMUX] Termux pip 安装成功")
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            print("[TERMUX] pkg 安装失败，尝试其他方式...")
    
    try:
        import pip
        return True
    except ImportError:
        pass
    
    try:
        result = subprocess.run([sys.executable, "-m", "pip", "--version"], capture_output=True, text=True)
        if result.returncode == 0:
            return True
    except Exception:
        pass
    
    try:
        import ensurepip
        print("正在通过 ensurepip 安装 pip...")
        
        try:
            ensurepip.bootstrap(upgrade=True)
        except Exception as bootstrap_err:
            print(f"  bootstrap 升级失败，尝试基础安装...")
            ensurepip.bootstrap()
        
        import site
        site.main()
        
        result = subprocess.run([sys.executable, "-m", "pip", "--version"], capture_output=True, text=True)
        if result.returncode == 0:
            print("pip 安装成功")
            return True
        else:
            print(f"  验证失败: {result.stderr}")
            
            import importlib
            try:
                if 'pip' in sys.modules:
                    del sys.modules['pip']
                importlib.import_module('pip')
                print("pip 安装成功（通过重新导入）")
                return True
            except ImportError:
                pass
                
    except Exception as e:
        print(f"ensurepip 安装失败: {e}")
    
    try:
        print("正在下载 get-pip.py...")
        import tempfile
        get_pip_url = "https://bootstrap.pypa.io/get-pip.py"
        
        if is_termux():
            temp_dir = Path("/data/data/com.termux/files/usr/tmp") / "temp_pip_install"
        else:
            temp_dir = Path(tempfile.gettempdir()) / "temp_pip_install"
        
        temp_dir.mkdir(exist_ok=True, parents=True)
        get_pip_path = temp_dir / "get-pip.py"
        
        urllib.request.urlretrieve(get_pip_url, str(get_pip_path))
        
        print("正在运行 get-pip.py 安装 pip...")
        result = subprocess.run(
            [sys.executable, str(get_pip_path), "--user", "--no-warn-script-location"],
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            print(f"用户目录安装失败，尝试使用临时目录...")
            target_dir = Path(temp_dir) / "pip_target"
            target_dir.mkdir(exist_ok=True)
            
            result = subprocess.run(
                [sys.executable, str(get_pip_path), "--target", str(target_dir)],
                capture_output=True,
                text=True
            )
            
            if result.returncode != 0:
                raise Exception(result.stderr)
                
            sys.path.insert(0, str(target_dir))
        
        get_pip_path.unlink(missing_ok=True)
        print("pip 安装成功")
        return True
    except Exception as e:
        print(f"get-pip.py 安装失败: {e}")
    
    return False

_PIP_MIRRORS = [
    ("https://pypi.tuna.tsinghua.edu.cn/simple", "pypi.tuna.tsinghua.edu.cn"),
    ("https://mirrors.aliyun.com/pypi/simple", "mirrors.aliyun.com"),
    ("https://mirrors.cloud.tencent.com/pypi/simple", "mirrors.cloud.tencent.com"),
    ("https://pypi.mirrors.ustc.edu.cn/simple", "pypi.mirrors.ustc.edu.cn"),
    ("https://mirrors.huaweicloud.com/repository/pypi/simple", "mirrors.huaweicloud.com"),
]

def _get_pip_index_args():
    import urllib.request
    for url, host in _PIP_MIRRORS:
        try:
            urllib.request.urlopen(url + "/", timeout=5)
            return ["-i", url, "--trusted-host", host]
        except Exception:
            continue
    return []

def install_package(package):
    index_args = _get_pip_index_args()
    if index_args:
        print(f"  使用镜像源: {index_args[1]}")

    install_commands = []
    if index_args:
        install_commands.append([sys.executable, "-m", "pip", "install", package] + index_args)
        install_commands.append([sys.executable, "-m", "pip", "install", "--user", package] + index_args)
    install_commands.append([sys.executable, "-m", "pip", "install", package])
    install_commands.append([sys.executable, "-m", "pip", "install", "--user", package])

    pip_exe = shutil.which("pip") or shutil.which("pip3")
    if pip_exe:
        if index_args:
            install_commands.insert(0, [pip_exe, "install", package] + index_args)
        install_commands.append([pip_exe, "install", package])
    
    for cmd in install_commands:
        try:
            print(f"  尝试: {' '.join(cmd[:6])}{'...' if len(cmd) > 6 else ''}")
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=180
            )
            
            if result.returncode == 0:
                return True
            else:
                err_msg = result.stderr.strip()
                if len(err_msg) > 200:
                    err_msg = err_msg[-200:]
                print(f"  失败: {err_msg}")
        except subprocess.TimeoutExpired:
            print(f"  超时(180s)")
        except FileNotFoundError:
            continue
        except Exception as e:
            print(f"  错误: {e}")
    
    if is_termux():
        try:
            print("  [TERMUX] 尝试 Termux 方式...")
            termux_cmd = ["pip", "install", package]
            if index_args:
                termux_cmd += index_args
            subprocess.check_call(termux_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass
    
    return False

def check_and_install_dependencies():
    required_packages = {
        "qrcode": "qrcode"
    }
    
    missing_packages = []
    for pip_name, import_name in required_packages.items():
        try:
            __import__(import_name)
        except ImportError:
            missing_packages.append(pip_name)
    
    if missing_packages:
        print(f"需要安装的库: {', '.join(missing_packages)}")
        
        has_pip = True
        try:
            import pip
        except ImportError:
            print("未检测到 pip，正在尝试自动安装...")
            has_pip = ensure_pip_available()
        
        if not has_pip:
            print("错误: 无法安装 pip，请手动安装后重试")
            print("  - Windows: python -m ensurepip --upgrade")
            print("  - Linux/Mac: python3 -m ensurepip --upgrade")
            print("  - Termux: pkg install python-pip")
            sys.exit(1)
        
        for package in missing_packages:
            print(f"正在安装 {package}...")
            if install_package(package):
                print(f"{package} 安装完成")
            else:
                print(f"{package} 安装失败，请手动安装: pip install {package}")
                sys.exit(1)

    try:
        from Crypto.Cipher import AES
    except ImportError:
        print()
        print("=" * 56)
        print("  未安装 pycryptodome 库，媒体解密将极慢（纯Python实现）")
        print("  建议安装以获得 1000x+ 解密速度提升，请运行：")
        print()
        print("    pip install pycryptodome -i https://pypi.tuna.tsinghua.edu.cn/simple")
        print("    (阿里云: -i https://mirrors.aliyun.com/pypi/simple)")
        print("    (腾讯云: -i https://mirrors.cloud.tencent.com/pypi/simple)")
        print()
        print("  安装后重启程序即可生效")
        print("=" * 56)
        print()

check_and_install_dependencies()

import qrcode

CONFIG_FILE = "wechat_bot_config.json"
MESSAGES_FILE = "wechat_messages.json"
AI_CONFIG_FILE = "ai_config.json"
MEDIA_CACHE_DIR = "media_cache"

class WeChatiLinkBot:
    ILINK_BASE_URL = "https://ilinkai.weixin.qq.com"
    MEDIA_TYPE_MAP = {"image": 2, "voice": 3, "file": 4, "video": 5}
    MEDIA_TYPE_NAMES = {2: "图片", 3: "语音", 4: "文件", 5: "视频"}
    MEDIA_TYPE_PREFIXES = {"image": "[图片]", "video": "[视频]", "file": "[文件]", "voice": "[语音]"}
    EXPIRED_CODES = {-14, 40014, 1002}
    SCRIPT_VERSION = "2.0.0"
    AUTHOR_NAME = "ZynSync"
    
    def __init__(self):
        self.token: Optional[str] = None
        self.bot_id: Optional[str] = None
        self.user_id: Optional[str] = None
        self._cursor: str = ""
        self._context_tokens: Dict[str, str] = {}
        self._current_user: Optional[str] = None
        self._timeout = 35
        self._running = True 
        self._qrcode_matrix: Optional[List[List[str]]] = None
        self._http_server = None
        self._server_thread = None
        self._qrcode_key = None
        self._login_done = False
        self._web_port = 8888
        self._messages: List[dict] = []
        self._message_callback = None
        self._max_messages_per_user = 500
        self._total_max_messages = 2000
        self.ai_config = self._load_ai_config()
        self._active_timers: Dict[str, threading.Timer] = {}
        self._session_tokens: Dict[str, float] = {}
        self._media_cache_dir = Path(MEDIA_CACHE_DIR)
        self._media_cache_dir.mkdir(parents=True, exist_ok=True)
        self._media_downloading: Dict[str, threading.Event] = {}
        self._media_download_lock = threading.Lock()
        
        self._load_messages()
    
    def _load_ai_config(self) -> dict:
        default_config = {
            "enabled": False,
            "api_url": "",
            "api_key": "",
            "model": "gpt-3.5-turbo",
            "active_interval": 60,
            "min_words": 10,
            "max_words": 200,
            "system_prompt": "你是一个微信聊天助手，请用自然的中文回复。"
        }
        try:
            if Path(AI_CONFIG_FILE).exists():
                with open(AI_CONFIG_FILE, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                    default_config.update(saved)
                    print(f"[AI] 已加载 AI 配置: enabled={default_config.get('enabled')}, api_url={default_config.get('api_url', '')[:50]}, api_key={'已设置' if default_config.get('api_key') else '未设置'}")
            else:
                print("[AI] 未找到 AI 配置文件，使用默认配置")
        except Exception as e:
            print(f"[AI] 加载 AI 配置失败: {e}")
        return default_config
    
    def _save_ai_config(self):
        try:
            with open(AI_CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.ai_config, f, ensure_ascii=False, indent=2)
            print(f"[AI] 配置已保存: enabled={self.ai_config.get('enabled')}, api_url={self.ai_config.get('api_url', '')[:50]}, api_key={'已设置' if self.ai_config.get('api_key') else '未设置'}")
        except Exception as e:
            print(f"[AI] 保存 AI 配置失败: {e}")
    
    def _generate_session_token(self) -> str:
        token = uuid.uuid4().hex + uuid.uuid4().hex
        self._session_tokens[token] = time.time() + 3600
        if len(self._session_tokens) > 100:
            self._cleanup_expired_sessions()
        return token
    
    def _verify_session_token(self, token: str) -> bool:
        if not token:
            return False
        if token in self._session_tokens:
            if time.time() < self._session_tokens[token]:
                return True
            else:
                del self._session_tokens[token]
        return False
    
    def _cleanup_expired_sessions(self):
        now = time.time()
        expired = [t for t, exp in self._session_tokens.items() if exp <= now]
        for t in expired:
            del self._session_tokens[t]
    
    def _call_ai_api(self, user_message: str, history: List[dict], is_active: bool = False, custom_instruction: str = "") -> Optional[str]:
        if not self.ai_config.get("enabled"):
            print("[AI] AI 自动回复未启用")
            return None
        if not self.ai_config.get("api_url") or not self.ai_config.get("api_key"):
            print(f"[AI] API 配置不完整: url={self.ai_config.get('api_url')}, key={'已设置' if self.ai_config.get('api_key') else '未设置'}")
            return None
        
        print(f"[AI] 正在调用 AI API，{'主动发送' if is_active else '回复消息'}")
        if not is_active:
            print(f"[AI] 用户消息: {user_message[:100]}...")
        print(f"[AI] 历史消息数量: {len(history)} 条")
        
        system_prompt = self.ai_config.get("system_prompt", "")
        if not system_prompt:
            system_prompt = "你是一个微信聊天助手，请用自然的中文回复。"
        
        messages = []
        
        for msg in history[-50:]:
            if msg.get("type") == "in":
                messages.append({"role": "user", "content": msg.get("text", "")})
            elif msg.get("type") == "out":
                messages.append({"role": "assistant", "content": msg.get("text", "")})
        
        if is_active:
            final_prompt = f"{system_prompt}\n\n现在没有用户的新消息，你需要主动发起一个话题。请严格按照上面的性格要求来回复。"
            messages.append({"role": "user", "content": final_prompt})
        else:
            if custom_instruction:
                final_prompt = f"{system_prompt}\n\n用户说：{user_message}\n\n额外要求：{custom_instruction}\n\n请严格按照你的性格要求和额外要求回复。"
            else:
                final_prompt = f"{system_prompt}\n\n用户说：{user_message}\n\n请严格按照你的性格要求回复。"
            messages.append({"role": "user", "content": final_prompt})
        
        payload = {
            "model": self.ai_config.get("model", "gpt-3.5-turbo"),
            "messages": messages,
            "temperature": 1.2,
            "max_tokens": 500,
        }
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.ai_config.get('api_key')}"
        }
        
        req = urllib.request.Request(
            self.ai_config.get("api_url"),
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST"
        )
        
        try:
            print(f"[AI] 请求 URL: {self.ai_config.get('api_url')}")
            with urllib.request.urlopen(req, timeout=60) as resp:
                status_code = resp.getcode()
                print(f"[AI] HTTP 状态码: {status_code}")
                result = json.loads(resp.read().decode("utf-8"))
                content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
                print(f"[AI] API 返回内容: {content[:200]}...")
                return content
        except urllib.error.HTTPError as e:
            status_code = e.code
            print(f"[AI] HTTP 错误: {status_code} - {e.reason}")
            try:
                error_body = e.read().decode('utf-8')
                print(f"[AI] 错误详情: {error_body[:500]}")
            except Exception:
                pass
            return None
        except urllib.error.URLError as e:
            print(f"[AI] 网络错误: {e.reason}")
            return None
        except Exception as e:
            print(f"[AI] 未知错误: {e}")
            return None
    
    def _should_segment(self, text: str) -> tuple:
        if len(text) < 30:
            return text, 1, 0
        
        sentences = text.replace('！', '。').replace('？', '。').replace('；', '。').split('。')
        sentences = [s.strip() for s in sentences if s.strip()]
        
        if len(sentences) >= 3:
            mid = len(sentences) // 2
            part1 = '。'.join(sentences[:mid]) + '。'
            part2 = '。'.join(sentences[mid:]) + '。'
            return [part1, part2], 2, 2
        
        if len(text) > 100:
            half = len(text) // 2
            part1 = text[:half]
            part2 = text[half:]
            return [part1, part2], 2, 2
        
        return text, 1, 0
    
    def _send_ai_reply_in_segments(self, to_user_id: str, response_text: str):
        print(f"[AI] 准备发送: {response_text[:100]}...")
        
        segments, seg_count, delay = self._should_segment(response_text)
        
        if seg_count <= 1:
            self.send_text(to_user_id, response_text)
            return
        
        def send_segments():
            if isinstance(segments, list):
                for idx, seg_text in enumerate(segments):
                    if not self._running:
                        break
                    print(f"[AI] 发送第 {idx+1}/{seg_count} 段: {seg_text[:30]}...")
                    self.send_text(to_user_id, seg_text)
                    if idx < len(segments) - 1:
                        time.sleep(delay)
            else:
                self.send_text(to_user_id, segments)
        
        threading.Thread(target=send_segments, daemon=True).start()
    
    def _auto_ai_reply(self, from_user: str, user_message: str):
        if not self.ai_config.get("enabled"):
            return
        
        print(f"[AI] 收到来自 {from_user} 的消息，准备回复...")
        
        history = self.get_user_messages(from_user, 200)
        print(f"[AI] 获取到 {len(history)} 条历史消息作为上下文")
        
        response = self._call_ai_api(user_message, history, is_active=False)
        
        if response:
            self._send_ai_reply_in_segments(from_user, response)
        else:
            print(f"[AI] 未能获取有效回复")
    
    def _manual_ai_reply(self, from_user: str, user_message: str, custom_instruction: str = ""):
        if not self.ai_config.get("enabled"):
            print("[AI] AI 功能未启用，请先在设置中启用并配置 API")
            return False
        
        print(f"[AI] 手动触发 AI 回复，用户: {from_user}")
        if custom_instruction:
            print(f"[AI] 额外指令: {custom_instruction}")
        
        history = self.get_user_messages(from_user, 200)
        
        response = self._call_ai_api(user_message, history, is_active=False, custom_instruction=custom_instruction)
        
        if response:
            self._send_ai_reply_in_segments(from_user, response)
            return True
        else:
            print(f"[AI] 未能获取有效回复")
            return False
    
    def _schedule_active_message(self, user_id: str):
        if not self.ai_config.get("enabled"):
            return
        
        interval = self.ai_config.get("active_interval", 60)
        if interval <= 0:
            return
        
        if user_id in self._active_timers:
            old_timer = self._active_timers[user_id]
            if old_timer:
                old_timer.cancel()
        
        print(f"[AI] 为 {user_id} 安排主动发送，间隔 {interval} 秒")
        
        timer = threading.Timer(interval, self._send_active_message, args=[user_id])
        timer.daemon = True
        timer.start()
        self._active_timers[user_id] = timer
    
    def _send_active_message(self, user_id: str):
        if not self.ai_config.get("enabled"):
            return
        
        if not self._running:
            return
        
        if user_id not in self._context_tokens:
            print(f"[AI] 用户 {user_id} 已不存在，取消主动发送")
            if user_id in self._active_timers:
                del self._active_timers[user_id]
            return
        
        print(f"[AI] 主动发送定时器触发，准备向 {user_id} 发送消息...")
        
        history = self.get_user_messages(user_id, 200)
        print(f"[AI] 获取到 {len(history)} 条历史消息作为上下文")
        
        response = self._call_ai_api("", history, is_active=True)
        
        if response:
            self._send_ai_reply_in_segments(user_id, response)
        else:
            print(f"[AI] 主动发送未能获取有效回复")
        
        if self.ai_config.get("enabled") and self._running and user_id in self._context_tokens:
            self._schedule_active_message(user_id)
    
    def _on_new_user(self, user_id: str):
        if self.ai_config.get("enabled"):
            print(f"[AI] 检测到新用户 {user_id}，启动主动发送定时器")
            self._schedule_active_message(user_id)
    
    def _load_messages(self):
        try:
            if Path(MESSAGES_FILE).exists():
                with open(MESSAGES_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._messages = data.get("messages", [])
                    print(f"[MSG] 已加载 {len(self._messages)} 条历史消息")
                    
                    if self._messages:
                        max_id = max(msg.get('id', 0) for msg in self._messages)
                        self._last_msg_id = max_id
                    else:
                        self._last_msg_id = 0
        except Exception as e:
            print(f"[MSG] 加载历史消息失败: {e}")
            self._messages = []
            self._last_msg_id = 0
    
    def _save_messages(self):
        try:
            data = {
                "messages": self._messages,
                "saved_at": datetime.now().isoformat(),
                "version": "1.0"
            }
            
            if len(self._messages) > self._total_max_messages:
                print(f"[MSG] 消息数量超过限制，保留最近 {self._total_max_messages} 条")
                self._messages = self._messages[-self._total_max_messages:]
            
            with open(MESSAGES_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                
            try:
                Path(MESSAGES_FILE).chmod(0o600)
            except (OSError, AttributeError, NotImplementedError):
                pass
        except Exception as e:
            print(f"[MSG] 保存消息失败: {e}")
    
    def _add_message_to_history(self, msg: dict):
        if not hasattr(self, '_last_msg_id'):
            self._last_msg_id = 0
        self._last_msg_id += 1
        msg['id'] = self._last_msg_id
        
        if 'time' not in msg:
            msg['time'] = datetime.now().strftime('%H:%M:%S')
        
        self._messages.append(msg)
        print(f"[MSG] 添加消息: id={msg['id']}, type={msg.get('type')}, text={msg.get('text', '')[:50]}...")
        
        target_id = msg.get('to') or msg.get('from')
        if target_id:
            user_msgs = [m for m in self._messages if m.get('to') == target_id or m.get('from') == target_id]
            if len(user_msgs) > self._max_messages_per_user:
                remove_ids = {m.get('id') for m in user_msgs[:len(user_msgs) - self._max_messages_per_user]}
                self._messages = [m for m in self._messages if m.get('id') not in remove_ids]
        
        threading.Thread(target=self._save_messages, daemon=True).start()
    
    def get_user_messages(self, user_id: str, limit: int = 50) -> List[dict]:
        if not user_id:
            return self._messages[-limit:] if self._messages else []
        
        user_msgs = [m for m in self._messages
                     if m.get('from') == user_id or m.get('to') == user_id]
        
        return user_msgs[-limit:] if limit > 0 else user_msgs
    
    def _open_browser(self):
        url = f'http://localhost:{self._web_port}'
        
        if is_termux():
            print(f"\n[TERMUX] 网页地址: {url}")
            print("[TERMUX] 提示:")
            print("  1. 在同一设备上打开浏览器访问上述地址")
            print("  2. 或使用其他设备访问（需确保网络可达）")
            print("  3. 或使用 termux-open-url 工具")
            
            try:
                subprocess.run(["termux-open-url", url], check=False, 
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                print("[TERMUX] 已尝试用 termux-open-url 打开浏览器")
                return
            except FileNotFoundError:
                pass
            
            try:
                intent_url = f'intent://action=android.intent.action.VIEW#Intent;scheme=http;package=com.android.chrome;end'
                subprocess.run(["am", "start", "-a", "android.intent.action.VIEW", "-d", url],
                             check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                print("[TERMUX] 已尝试用系统默认应用打开")
                return
            except FileNotFoundError:
                pass
            
            print("[TERMUX] ⚠ 无法自动打开浏览器，请手动访问上述地址")
            return
        
        try:
            import webbrowser
            webbrowser.open(url)
            print(f"\n[WEB] 已在浏览器中打开: {url}")
        except ImportError:
            print(f"\n[WEB] 请手动在浏览器中打开: {url}")
        except Exception as e:
            print(f"\n[WEB] 打开浏览器失败: {e}")
            print(f"[WEB] 请手动访问: {url}")
    
    def _save_config(self):
        config = {
            "token": self.token,
            "bot_id": self.bot_id,
            "user_id": self.user_id,
            "cursor": self._cursor,
            "context_tokens": self._context_tokens,
            "current_user": self._current_user,
        }
        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=2)
        try:
            Path(CONFIG_FILE).chmod(0o600)
        except (OSError, AttributeError, NotImplementedError):
            pass
    
    def load_config(self) -> bool:
        try:
            with open(CONFIG_FILE, "r") as f:
                config = json.load(f)
            self.token = config.get("token")
            self.bot_id = config.get("bot_id")
            self.user_id = config.get("user_id")
            self._cursor = config.get("cursor", "")
            self._context_tokens = config.get("context_tokens", {})
            self._current_user = config.get("current_user")
            if self.token:
                print(f"加载配置成功，{len(self._context_tokens)} 个会话已恢复")
                if self._current_user:
                    print(f"当前会话用户: {self._current_user}")
                for user_id in self._context_tokens.keys():
                    self._on_new_user(user_id)
                return True
            return False
        except FileNotFoundError:
            return False
    
    def _get_qrcode_matrix(self, qrcode_url: str) -> List[List[str]]:
        qr = qrcode.QRCode(border=1)
        qr.add_data(qrcode_url)
        qr.make(fit=True)
        matrix = qr.get_matrix()
        result = []
        for row in matrix:
            line = []
            for cell in row:
                line.append('█' if cell else ' ')
            result.append(line)
        return result
    
    def _generate_wasm_wrapper(self, session_token: str) -> str:
        return '''window.__ZN''' + session_token[:16] + ''' = (function() {
    let _state = {
        token: "''' + session_token + '''",
        apiBase: "",
        currentUser: null,
        lastMsgId: 0,
        pollInterval: null,
        displayedIds: new Set(),
        users: [],
        selectedMessage: null,
        selectedUserId: null,
        aiModalVisible: false,
        view: "list",
        nicknames: JSON.parse(localStorage.getItem("zyn_nicknames") || "{}"),
        lastMessages: {}
    };
    
    function antiDebug() {
        document.addEventListener("contextmenu", function(e) { e.preventDefault(); return false; });
        document.addEventListener("keydown", function(e) {
            if (e.key === "F12" || e.keyCode === 123 ||
                (e.ctrlKey && e.shiftKey && (e.key === "I" || e.keyCode === 73)) ||
                (e.ctrlKey && e.shiftKey && (e.key === "J" || e.keyCode === 74)) ||
                (e.ctrlKey && (e.key === "U" || e.keyCode === 85)) ||
                (e.ctrlKey && (e.key === "s" || e.keyCode === 83))) {
                e.preventDefault();
                return false;
            }
        });
    }
    
    const _api = function(e, t) {
        return new Promise((function(r, n) {
            const o = new XMLHttpRequest();
            o.open("POST", "/api/wasm/" + e, true);
            o.setRequestHeader("Content-Type", "application/json");
            o.setRequestHeader("X-Session-Token", _state.token);
            o.timeout = 120000;
            o.onload = function() {
                if (o.status >= 200 && o.status < 300) {
                    try {
                        r(JSON.parse(o.responseText));
                    } catch(e) {
                        r({});
                    }
                } else {
                    n(new Error(o.statusText || "HTTP " + o.status));
                }
            };
            o.onerror = function() { return n(new Error("Network Error")); };
            o.ontimeout = function() { return n(new Error("请求超时")); };
            o.send(JSON.stringify(t || {}));
        }));
    };
    
    const _get = function(e) {
        return new Promise((function(r, n) {
            const o = new XMLHttpRequest();
            o.open("GET", "/api/wasm/" + e, true);
            o.setRequestHeader("X-Session-Token", _state.token);
            o.onload = function() {
                if (o.status >= 200 && o.status < 300) {
                    try {
                        r(JSON.parse(o.responseText));
                    } catch(e) {
                        r({});
                    }
                } else {
                    n(new Error(o.statusText));
                }
            };
            o.onerror = function() { return n(new Error("Network Error")); };
            o.send();
        }));
    };
    
    const _escape = function(e) {
        const t = document.createElement("div");
        t.textContent = e;
        return t.innerHTML;
    };
    
    const _toast = function(e, t) {
        const n = document.getElementById("toast");
        if (!n) return;
        n.textContent = e;
        n.classList.add("show");
        setTimeout((function() { return n.classList.remove("show"); }), t || 3000);
    };
    
    const _svgImage = '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="#999" stroke-width="1.5"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/></svg>';
    const _svgVideo = '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="#999" stroke-width="1.5"><polygon points="23 7 16 12 23 17 23 7"/><rect x="1" y="5" width="15" height="14" rx="2"/></svg>';
    const _svgFile = '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="#999" stroke-width="1.5"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>';
    const _svgVoice = '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="#999" stroke-width="1.5"><path d="M12 1a3 3 0 00-3 3v8a3 3 0 006 0V4a3 3 0 00-3-3z"/><path d="M19 10v2a7 7 0 01-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg>';
    const _svgPlay = '<svg viewBox="0 0 24 24" width="36" height="36" fill="rgba(0,0,0,0.5)"><path d="M8 5v14l11-7z"/></svg>';

    const _renderMsg = function(e) {
        const t = document.getElementById("messages-area");
        if (!t) return;
        const n = t.querySelector(".empty-state");
        if (n) n.remove();
        const o = document.createElement("div");
        o.className = "msg-row " + (e.type === "out" ? "out" : "in");
        if (e.id) o.dataset.msgId = e.id;
        var bubbleContent = "";
        var mt = e.media_type;
        if (mt === "image" || mt === 2) {
            var imgSrc = e.media_data || "";
            var cacheSrc = e.media_cache_id ? '/api/wasm/media/' + e.media_cache_id : '';
            if (cacheSrc || imgSrc) {
                var cdnAttr = (e.media_cdn && !e.media_cache_id) ? ' data-cdn="' + encodeURIComponent(e.media_cdn) + '"' : '';
                var displaySrc = imgSrc || cacheSrc;
                var loadAttr = cacheSrc && imgSrc ? ' data-hq-src="' + cacheSrc + '"' : '';
                bubbleContent = '<div class="bubble-media-img-wrap"' + cdnAttr + loadAttr + '><img class="bubble-media-img" src="' + displaySrc + '" alt="图片" /></div>';
            } else if (e.media_cdn) {
                bubbleContent = '<div class="bubble-media-img-wrap bubble-media-loading" data-cdn="' + encodeURIComponent(e.media_cdn) + '"><div class="bubble-media-placeholder">' + _svgImage + '<span>图片</span></div></div>';
            } else {
                bubbleContent = '<div class="bubble-media-placeholder">' + _svgImage + '<span>图片</span></div>';
            }
        } else if (mt === "video" || mt === 5) {
            if (e.media_cache_id) {
                var videoSrc = '/api/wasm/media/' + e.media_cache_id;
                bubbleContent = '<div class="bubble-media-img-wrap"><div class="bubble-media-video-thumb" data-action="play-video" data-video-src="' + videoSrc + '"><video class="bubble-media-video-thumb-vid" src="' + videoSrc + '" preload="metadata" muted playsinline></video><div class="bubble-media-play-btn">' + _svgPlay + '</div></div></div>';
            } else if (e.media_data) {
                bubbleContent = '<div class="bubble-media-img-wrap"><div class="bubble-media-video-thumb" data-action="play-video"><img class="bubble-media-img" src="' + e.media_data + '" alt="视频" /><div class="bubble-media-play-btn">' + _svgPlay + '</div></div></div>';
            } else if (e.media_cdn) {
                bubbleContent = '<div class="bubble-media-img-wrap bubble-media-loading" data-cdn="' + encodeURIComponent(e.media_cdn) + '" data-media-type="video"><div class="bubble-media-placeholder">' + _svgVideo + '<span>视频</span></div></div>';
            } else {
                bubbleContent = '<div class="bubble-media-file"><div class="bubble-media-file-icon">' + _svgVideo + '</div><div class="bubble-media-file-info"><div class="bubble-media-file-name">' + _escape(e.media_filename || "视频") + '</div><div class="bubble-media-file-size">' + (e.media_duration ? (e.media_duration / 1000).toFixed(1) + "s" : "") + '</div></div></div>';
            }
        } else if (mt === "file" || mt === 4) {
            if (e.media_cache_id) {
                bubbleContent = '<div class="bubble-media-file"><div class="bubble-media-file-icon">' + _svgFile + '</div><div class="bubble-media-file-info"><div class="bubble-media-file-name">' + _escape(e.media_filename || "文件") + '</div></div></div>';
            } else if (e.media_cdn) {
                bubbleContent = '<div class="bubble-media-file bubble-media-loading" data-cdn="' + encodeURIComponent(e.media_cdn) + '" data-media-type="file"><div class="bubble-media-file-icon">' + _svgFile + '</div><div class="bubble-media-file-info"><div class="bubble-media-file-name">' + _escape(e.media_filename || "文件") + '</div></div></div>';
            } else {
                bubbleContent = '<div class="bubble-media-file"><div class="bubble-media-file-icon">' + _svgFile + '</div><div class="bubble-media-file-info"><div class="bubble-media-file-name">' + _escape(e.media_filename || "文件") + '</div></div></div>';
            }
        } else if (mt === "voice" || mt === 3) {
            var dur = e.media_duration ? Math.ceil(e.media_duration / 1000) : 1;
            var bars = "";
            for (var i = 0; i < Math.min(dur, 12); i++) {
                var h = 6 + Math.floor(Math.random() * 14);
                bars += '<div class="bubble-media-voice-bar" style="height:' + h + 'px"></div>';
            }
            if (e.media_cache_id) {
                bubbleContent = '<div class="bubble-media-voice" data-action="play-voice" data-cache-id="' + e.media_cache_id + '">' + _svgVoice + '<div class="bubble-media-voice-bars">' + bars + '</div><div class="bubble-media-voice-dur">' + dur + '"</div></div>';
            } else if (e.media_cdn) {
                bubbleContent = '<div class="bubble-media-voice bubble-media-loading" data-cdn="' + encodeURIComponent(e.media_cdn) + '" data-media-type="voice">' + _svgVoice + '<div class="bubble-media-voice-bars">' + bars + '</div><div class="bubble-media-voice-dur">' + dur + '"</div></div>';
            } else {
                bubbleContent = '<div class="bubble-media-voice">' + _svgVoice + '<div class="bubble-media-voice-bars">' + bars + '</div><div class="bubble-media-voice-dur">' + dur + '"</div></div>';
            }
        } else {
            bubbleContent = '<div class="bubble-text">' + _escape(e.text || "") + '</div>';
        }
        o.innerHTML = '<div class="bubble ' + (e.type === "out" ? "out" : "in") + '">' + bubbleContent + '<div class="msg-time-row">' + (e.media_cdn && !e.media_cache_id ? '<span class="msg-send-status msg-send-loading"></span>' : '') + '<span class="msg-time">' + (e.time || "") + '</span></div></div>';
        o._msgData = e;
        t.appendChild(o);
        t.scrollTop = t.scrollHeight;
        
        var loadingEl = o.querySelector('.bubble-media-loading');
        if (loadingEl) {
            window._loadCdnMedia(loadingEl);
        }

        var hqWrap = o.querySelector('.bubble-media-img-wrap[data-hq-src]');
        if (hqWrap) {
            var hqImg = new Image();
            hqImg.onload = (function(wrap, src) {
                return function() {
                    var img = wrap.querySelector('.bubble-media-img');
                    if (img) img.src = src;
                };
            })(hqWrap, hqWrap.dataset.hqSrc);
            hqImg.src = hqWrap.dataset.hqSrc;
        }

        const bubbleDiv = o.querySelector('.bubble');
        if (bubbleDiv) {
            var isMediaMsg = (mt === "image" || mt === 2 || mt === "video" || mt === 5 || mt === "voice" || mt === 3 || mt === "file" || mt === 4);
            if (isMediaMsg) {
                bubbleDiv.style.cursor = 'pointer';
                bubbleDiv.addEventListener('click', (function(ev) {
                    ev.stopPropagation();
                    _handleMediaClick(e);
                }));
            } else if (e.type === 'in') {
                bubbleDiv.style.cursor = 'pointer';
                bubbleDiv.addEventListener('click', (function(ev) {
                    ev.stopPropagation();
                    _showAiModal(e.id, e.text, e.from || _state.currentUser);
                }));
            }
        }
    };

    const _renderSendingMsg = function(e) {
        const t = document.getElementById("messages-area");
        if (!t) return;
        const n = t.querySelector(".empty-state");
        if (n) n.remove();
        const o = document.createElement("div");
        o.className = "msg-row out";
        o.dataset.sendingId = e.id;
        if (e.id) o.dataset.msgId = e.id;
        var bubbleContent = "";
        var mt = e.media_type;
        if (mt === 2 && e.media_data) {
            bubbleContent = '<div class="bubble-media-img-wrap"><img class="bubble-media-img" src="' + e.media_data + '" alt="图片" /></div>';
        } else if (mt === 5 && e.media_data) {
            bubbleContent = '<div class="bubble-media-img-wrap"><div class="bubble-media-video-thumb"><img class="bubble-media-img" src="' + e.media_data + '" alt="视频" /><div class="bubble-media-play-btn">' + _svgPlay + '</div></div></div>';
        } else if (mt === 3) {
            var dur = e.media_duration ? Math.ceil(e.media_duration / 1000) : 1;
            var bars = "";
            for (var i = 0; i < Math.min(dur, 12); i++) {
                var h = 6 + Math.floor(Math.random() * 14);
                bars += '<div class="bubble-media-voice-bar" style="height:' + h + 'px"></div>';
            }
            bubbleContent = '<div class="bubble-media-voice">' + _svgVoice + '<div class="bubble-media-voice-bars">' + bars + '</div><div class="bubble-media-voice-dur">' + dur + '"</div></div>';
        } else if (mt === 4) {
            bubbleContent = '<div class="bubble-media-file"><div class="bubble-media-file-icon">' + _svgFile + '</div><div class="bubble-media-file-info"><div class="bubble-media-file-name">' + _escape(e.media_filename || "文件") + '</div></div></div>';
        } else {
            bubbleContent = '<div class="bubble-text">' + _escape(e.text || "") + '</div>';
        }
        o.innerHTML = '<div class="bubble out">' + bubbleContent + '<div class="msg-time-row"><span class="msg-send-status msg-send-loading"></span><span class="msg-time">' + (e.time || "") + '</span></div></div>';
        t.appendChild(o);
        t.scrollTop = t.scrollHeight;
    };

    var _currentAudio = null;
    var _currentVoiceEl = null;

    const _cdnInfoStr = function(cdn) {
        if (typeof cdn === 'string') return cdn;
        return JSON.stringify(cdn);
    };

    const _handleMediaClick = function(msg) {
        var mt = msg.media_type;
        if (mt === "image" || mt === 2) {
            if (msg.media_cache_id) {
                window._previewImage('/api/wasm/media/' + msg.media_cache_id);
            } else if (msg.media_data) {
                window._previewImage(msg.media_data);
            } else if (msg.media_cdn) {
                _toast("正在加载图片...");
                fetch('/api/wasm/download-media', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json', 'X-Session-Token': _state.token},
                    body: JSON.stringify({cdn_info: _cdnInfoStr(msg.media_cdn)})
                }).then(function(r) {
                    if (!r.ok) {
                        return r.text().then(function(t) { throw new Error('HTTP ' + r.status); });
                    }
                    return r.json();
                }).then(function(result) {
                    if (result.success && result.cache_key) {
                        window._previewImage('/api/wasm/media/' + result.cache_key);
                    } else {
                        _toast("图片加载失败: " + (result.error || ""));
                    }
                }).catch(function(err) {
                    console.log('图片加载异常:', err);
                    _toast("图片加载失败");
                });
            }
        } else if (mt === "video" || mt === 5) {
            _playVideo(msg);
        } else if (mt === "voice" || mt === 3) {
            _playVoice(msg);
        } else if (mt === "file" || mt === 4) {
            _downloadMedia(msg, "file");
        }
    };

    var _voicePlayFailed = {};

    const _playVoice = function(msg) {
        if (!msg.media_cdn && !msg.media_cache_id) {
            _toast("语音数据不可用");
            return;
        }
        var msgId = msg.id;
        if (_voicePlayFailed[msgId]) {
            delete _voicePlayFailed[msgId];
            _downloadMedia(msg, "voice");
            return;
        }
        if (_currentAudio) {
            _currentAudio.pause();
            _currentAudio = null;
            if (_currentVoiceEl) {
                _currentVoiceEl.classList.remove('voice-playing');
                _currentVoiceEl = null;
            }
        }
        var voiceEl = null;
        if (msgId) {
            var msgRow = document.querySelector('[data-msg-id="' + msgId + '"]');
            if (msgRow) voiceEl = msgRow.querySelector('.bubble-media-voice');
        }
        var tryPlayAudio = function(cacheId) {
            var cacheUrl = '/api/wasm/media/' + cacheId;
            var audio = new Audio();
            var hasPlayed = false;
            audio.addEventListener('canplaythrough', function() {
                hasPlayed = true;
                if (voiceEl) {
                    _currentVoiceEl = voiceEl;
                    voiceEl.classList.add('voice-playing');
                }
                audio.play().catch(function() {
                    _voicePlayFailed[msgId] = true;
                    if (voiceEl) voiceEl.classList.remove('voice-playing');
                    _toast("语音播放失败，再次点击可下载");
                });
            });
            audio.addEventListener('error', function() {
                if (!hasPlayed) {
                    _voicePlayFailed[msgId] = true;
                    _toast("浏览器不支持此语音格式，再次点击可下载");
                }
            });
            audio.addEventListener('ended', function() {
                _currentAudio = null;
                if (_currentVoiceEl) {
                    _currentVoiceEl.classList.remove('voice-playing');
                    _currentVoiceEl = null;
                }
            });
            _currentAudio = audio;
            audio.src = cacheUrl;
            audio.load();
        };
        if (msg.media_cache_id) {
            tryPlayAudio(msg.media_cache_id);
            return;
        }
        _toast("正在加载语音...");
        fetch('/api/wasm/download-media', {
            method: 'POST',
            headers: {'Content-Type': 'application/json', 'X-Session-Token': _state.token},
            body: JSON.stringify({cdn_info: _cdnInfoStr(msg.media_cdn)})
        }).then(function(r) {
            if (!r.ok) {
                return r.text().then(function(t) { throw new Error('HTTP ' + r.status + ': ' + t); });
            }
            return r.json();
        }).then(function(result) {
            if (result.success && result.cache_key) {
                tryPlayAudio(result.cache_key);
            } else {
                _toast("语音加载失败: " + (result.error || "未知错误"));
            }
        }).catch(function(err) {
            console.log('语音加载异常:', err);
            _toast("语音加载失败");
        });
    };

    const _playVideo = function(msg) {
        if (!msg.media_cdn && !msg.media_cache_id) {
            _toast("视频数据不可用");
            return;
        }
        var tryPlayVideo = function(cacheId) {
            var videoUrl = '/api/wasm/media/' + cacheId;
            window._previewVideo(videoUrl);
        };
        if (msg.media_cache_id) {
            tryPlayVideo(msg.media_cache_id);
            return;
        }
        _toast("正在加载视频...");
        fetch('/api/wasm/download-media', {
            method: 'POST',
            headers: {'Content-Type': 'application/json', 'X-Session-Token': _state.token},
            body: JSON.stringify({cdn_info: _cdnInfoStr(msg.media_cdn)})
        }).then(function(r) {
            if (!r.ok) {
                return r.text().then(function(t) { throw new Error('HTTP ' + r.status + ': ' + t); });
            }
            return r.json();
        }).then(function(result) {
            if (result.success && result.cache_key) {
                tryPlayVideo(result.cache_key);
            } else {
                _toast("视频加载失败: " + (result.error || "未知错误"));
            }
        }).catch(function(err) {
            console.log('视频加载异常:', err);
            _toast("视频加载失败");
        });
    };

    window._previewVideo = function(src) {
        var overlay = document.createElement('div');
        overlay.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.92);z-index:10002;display:flex;flex-direction:column;align-items:center;justify-content:center;cursor:default';
        var video = document.createElement('video');
        video.src = src;
        video.controls = true;
        video.autoplay = true;
        video.playsInline = true;
        video.style.cssText = 'max-width:95%;max-height:85%;border-radius:8px;background:#000;outline:none';
        var closeBtn = document.createElement('div');
        closeBtn.style.cssText = 'position:absolute;top:16px;right:16px;width:36px;height:36px;border-radius:50%;background:rgba(255,255,255,0.2);display:flex;align-items:center;justify-content:center;cursor:pointer;font-size:20px;color:#fff;z-index:10003';
        closeBtn.innerHTML = '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="#fff" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>';
        var downloadBtn = document.createElement('div');
        downloadBtn.style.cssText = 'position:absolute;top:16px;right:60px;width:36px;height:36px;border-radius:50%;background:rgba(255,255,255,0.2);display:flex;align-items:center;justify-content:center;cursor:pointer;z-index:10003';
        downloadBtn.innerHTML = '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="#fff" stroke-width="2"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>';
        downloadBtn.addEventListener('click', function(ev) {
            ev.stopPropagation();
            var a = document.createElement('a');
            a.href = src + '?download=1';
            a.download = 'video.mp4';
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
        });
        var closeOverlay = function() {
            video.pause();
            video.src = '';
            if (overlay.parentNode) document.body.removeChild(overlay);
        };
        closeBtn.addEventListener('click', function(ev) { ev.stopPropagation(); closeOverlay(); });
        overlay.addEventListener('click', function(ev) { if (ev.target === overlay) closeOverlay(); });
        overlay.appendChild(video);
        overlay.appendChild(closeBtn);
        overlay.appendChild(downloadBtn);
        document.body.appendChild(overlay);
    };

    const _downloadDirectUrl = function(cacheId, filename) {
        try {
            var downloadUrl = '/api/wasm/media/' + cacheId + '?download=1';
            var a = document.createElement('a');
            a.href = downloadUrl;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            _toast("正在接收: " + filename);
        } catch (err) {
            _toast("下载失败");
        }
    };

    const _downloadMedia = function(msg, mediaType) {
        if (!msg.media_cdn && !msg.media_cache_id) {
            _toast("媒体数据不可用");
            return;
        }
        var filename = msg.media_filename || (mediaType === "video" ? "video.mp4" : mediaType === "voice" ? "voice.silk" : "file.bin");
        if (msg.media_cache_id) {
            _downloadDirectUrl(msg.media_cache_id, filename);
            return;
        }
        _toast("正在接收 " + filename + "...");
        fetch('/api/wasm/download-media', {
            method: 'POST',
            headers: {'Content-Type': 'application/json', 'X-Session-Token': _state.token},
            body: JSON.stringify({cdn_info: _cdnInfoStr(msg.media_cdn)})
        }).then(function(r) {
            if (!r.ok) {
                return r.text().then(function(t) { throw new Error('HTTP ' + r.status); });
            }
            return r.json();
        }).then(function(result) {
            if (result.success && result.cache_key) {
                _downloadDirectUrl(result.cache_key, filename);
            } else {
                _toast("下载失败: " + (result.error || "未知错误"));
            }
        }).catch(function(err) {
            console.log('下载异常:', err);
            _toast("下载失败");
        });
    };

    window._previewImage = function(src) {
        var overlay = document.createElement('div');
        overlay.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.9);z-index:10002;display:flex;align-items:center;justify-content:center;cursor:zoom-out';
        var img = document.createElement('img');
        img.src = src;
        img.style.cssText = 'max-width:95%;max-height:95%;object-fit:contain;border-radius:4px';
        overlay.appendChild(img);
        overlay.addEventListener('click', function() { document.body.removeChild(overlay); });
        document.body.appendChild(overlay);
    };

    const _removeLoadingSpinner = function(el, cacheKey) {
        var row = el.closest('.msg-row');
        if (row) {
            var spinner = row.querySelector('.msg-send-loading');
            if (spinner) spinner.remove();
            if (cacheKey && row._msgData) {
                row._msgData.media_cache_id = cacheKey;
            }
        }
    };

    window._loadCdnMedia = function(el) {
        var cdn = decodeURIComponent(el.dataset.cdn || "");
        var mediaType = el.dataset.mediaType || "image";
        if (!cdn) return;
        fetch('/api/wasm/download-media', {
            method: 'POST',
            headers: {'Content-Type': 'application/json', 'X-Session-Token': _state.token},
            body: JSON.stringify({cdn_info: _cdnInfoStr(cdn)})
        }).then(function(r) { return r.json(); }).then(function(result) {
            if (result.success && result.cache_key) {
                var cacheUrl = '/api/wasm/media/' + result.cache_key;
                if (mediaType === "video") {
                    el.innerHTML = '<div class="bubble-media-video-thumb" data-action="play-video" data-video-src="' + cacheUrl + '"><video class="bubble-media-video-thumb-vid" src="' + cacheUrl + '" preload="metadata" muted playsinline></video><div class="bubble-media-play-btn">' + _svgPlay + '</div></div>';
                } else if (mediaType === "file") {
                    el.classList.remove('bubble-media-loading');
                    el.removeAttribute('data-cdn');
                    el.removeAttribute('data-media-type');
                    el.dataset.cacheId = result.cache_key;
                    return _removeLoadingSpinner(el, result.cache_key);
                } else if (mediaType === "voice") {
                    el.classList.remove('bubble-media-loading');
                    el.removeAttribute('data-cdn');
                    el.removeAttribute('data-media-type');
                    el.dataset.action = 'play-voice';
                    el.dataset.cacheId = result.cache_key;
                    return _removeLoadingSpinner(el, result.cache_key);
                } else {
                    el.innerHTML = '<img class="bubble-media-img" src="' + cacheUrl + '" alt="图片" />';
                }
                el.classList.remove('bubble-media-loading');
                _removeLoadingSpinner(el, result.cache_key);
            } else {
                var svgIcon = _svgImage;
                var label = "加载失败";
                if (mediaType === "video") { svgIcon = _svgVideo; label = "视频加载失败"; }
                else if (mediaType === "file") { svgIcon = _svgFile; label = "文件加载失败"; }
                else if (mediaType === "voice") { svgIcon = _svgVoice; label = "语音加载失败"; }
                else { label = "图片加载失败"; }
                el.innerHTML = '<div class="bubble-media-placeholder">' + svgIcon + '<span>' + label + '</span></div>';
                el.classList.remove('bubble-media-loading');
                _removeLoadingSpinner(el);
            }
        }).catch(function() {
            var svgIcon = _svgImage;
            var label = "加载失败";
            if (mediaType === "video") { svgIcon = _svgVideo; label = "视频加载失败"; }
            else if (mediaType === "file") { svgIcon = _svgFile; label = "文件加载失败"; }
            else if (mediaType === "voice") { svgIcon = _svgVoice; label = "语音加载失败"; }
            else { label = "图片加载失败"; }
            el.innerHTML = '<div class="bubble-media-placeholder">' + svgIcon + '<span>' + label + '</span></div>';
            el.classList.remove('bubble-media-loading');
            _removeLoadingSpinner(el);
        });
    };
    
    const _showAiModal = function(msgId, msgText, userId) {
        _state.selectedMessage = { id: msgId, text: msgText };
        _state.selectedUserId = userId;
        const modal = document.getElementById("ai-modal");
        const msgPreview = document.getElementById("ai-modal-msg-preview");
        const instructionInput = document.getElementById("ai-instruction");
        if (modal) {
            if (msgPreview) msgPreview.innerText = msgText;
            if (instructionInput) instructionInput.value = "";
            modal.classList.add("show");
        }
    };
    
    const _closeAiModal = function() {
        const modal = document.getElementById("ai-modal");
        if (modal) modal.classList.remove("show");
        _state.selectedMessage = null;
        _state.selectedUserId = null;
    };
    
    const _sendAiReply = async function() {
        if (!_state.selectedMessage) {
            _toast("请选择要回复的消息");
            _closeAiModal();
            return;
        }
        let targetUser = _state.selectedUserId;
        if (!targetUser) {
            targetUser = _state.currentUser;
        }
        if (!targetUser) {
            _toast("无法确定要回复的用户");
            _closeAiModal();
            return;
        }
        const instruction = document.getElementById("ai-instruction") ? document.getElementById("ai-instruction").value : "";
        _toast("正在生成 AI 回复...");
        const result = await _api("ai-manual-reply", {
            user_id: targetUser,
            original_message: _state.selectedMessage.text,
            instruction: instruction
        });
        if (result && result.success) {
            _toast("AI 回复已发送");
            setTimeout(_fetchMessages, 500);
        } else {
            _toast((result && result.error) || "AI 回复失败，请检查 API 配置");
        }
        _closeAiModal();
    };
    
    const _loadUsers = async function() {
        const e = await _get("users");
        if (e && e.users) {
            _state.users = e.users;
            if (_state.view === 'list') {
                _renderChatList();
                _loadChatListPreviews();
            }
        }
    };
    
    const _updateSelector = function() {
        const e = document.getElementById("user-select-btn");
        const t = document.getElementById("user-dropdown");
        if (e && _state.currentUser) {
            var nick = _state.nicknames[_state.currentUser] || '';
            e.textContent = nick || (_state.currentUser ? _state.currentUser.substring(0, 15) + (_state.currentUser.length > 15 ? "..." : "") : "选择用户");
        }
        if (t && _state.users && _state.users.length > 0) {
            t.innerHTML = _state.users.map((function(r) {
                return `<div class="user-option ${r === _state.currentUser ? "current" : ""}" data-user-id="${r}">用户 ${r}</div>`;
            })).join("");
            t.querySelectorAll(".user-option").forEach((function(e) {
                e.addEventListener("click", (function() {
                    const t = e.getAttribute("data-user-id");
                    if (t) _openChat(t);
                }));
            }));
        }
    };
    
    const _selectUser = async function(e) {
        if (!e) return;
        _openChat(e);
    };
    
    const _renderChatList = function() {
        var container = document.getElementById("chat-list-items");
        if (!container) return;
        if (!_state.users || _state.users.length === 0) {
            container.innerHTML = '<div class="chat-list-empty"><div class="chat-list-empty-icon">💬</div><div>暂无聊天</div></div>';
            return;
        }
        var html = '';
        _state.users.forEach(function(userId) {
            var nickname = _state.nicknames[userId] || '';
            var displayName = nickname || userId;
            var lastMsg = _state.lastMessages[userId];
            var preview = '';
            var time = '';
            if (lastMsg) {
                if (lastMsg.media_type) {
                    var mediaLabels = {2: '[图片]', 3: '[语音]', 4: '[文件]', 5: '[视频]', 'image': '[图片]', 'voice': '[语音]', 'file': '[文件]', 'video': '[视频]'};
                    preview = mediaLabels[lastMsg.media_type] || lastMsg.text || '';
                } else {
                    preview = lastMsg.text || '';
                }
                time = lastMsg.time || '';
            }
            html += '<div class="chat-list-item" data-user-id="' + _escape(userId) + '">' +
                '<div class="chat-list-item-avatar">用户</div>' +
                '<div class="chat-list-item-content">' +
                '<div class="chat-list-item-name">' + _escape(displayName) + '</div>' +
                '<div class="chat-list-item-msg">' + _escape(preview) + '</div>' +
                '</div>' +
                '<div class="chat-list-item-time">' + time + '</div>' +
                '</div>';
        });
        container.innerHTML = html;
        container.querySelectorAll('.chat-list-item').forEach(function(item) {
            item.addEventListener('click', function() {
                var userId = item.getAttribute('data-user-id');
                if (userId) _openChat(userId);
            });
        });
    };
    
    const _openChat = async function(userId) {
        if (!userId) return;
        _state.currentUser = userId;
        _state.view = 'chat';
        _state.displayedIds.clear();
        _state.lastMsgId = 0;
        var chatListPage = document.getElementById("chat-list-page");
        if (chatListPage) chatListPage.classList.remove("active");
        var chatPage = document.getElementById("chat-page");
        if (chatPage) chatPage.classList.add("active");
        var title = document.getElementById("chat-header-title");
        if (title) {
            var nickname = _state.nicknames[userId] || '';
            title.textContent = nickname || userId;
        }
        var messagesArea = document.getElementById("messages-area");
        if (messagesArea) messagesArea.innerHTML = '<div class="empty-state"><div class="empty-state-icon">⏳</div><div>正在加载历史消息...</div></div>';
        await _api("switch-user", { user_id: userId });
        _loadHistory(userId);
    };
    
    const _backToChatList = function() {
        _state.view = 'list';
        _state.currentUser = null;
        _state.displayedIds.clear();
        var chatPage = document.getElementById("chat-page");
        if (chatPage) chatPage.classList.remove("active");
        var chatListPage = document.getElementById("chat-list-page");
        if (chatListPage) chatListPage.classList.add("active");
        _loadUsers();
        _loadChatListPreviews();
    };
    
    const _loadChatListPreviews = async function() {
        var promises = _state.users.map(async function(userId) {
            try {
                var data = await _get("history?user=" + encodeURIComponent(userId) + "&limit=1");
                if (data && data.messages && data.messages.length > 0) {
                    var lastMsg = data.messages[data.messages.length - 1];
                    _state.lastMessages[userId] = {
                        text: lastMsg.text || '',
                        time: lastMsg.time || '',
                        media_type: lastMsg.media_type
                    };
                }
            } catch(e) {}
        });
        await Promise.all(promises);
        _renderChatList();
    };
    
    const _openNicknameModal = function() {
        if (!_state.currentUser) return;
        var modal = document.getElementById("nickname-modal");
        var input = document.getElementById("nickname-input");
        var userIdDiv = document.getElementById("nickname-modal-userid");
        if (!modal || !input) return;
        if (userIdDiv) userIdDiv.textContent = '用户ID: ' + _state.currentUser;
        input.value = _state.nicknames[_state.currentUser] || '';
        modal.classList.add("show");
        setTimeout(function() { input.focus(); }, 100);
    };
    
    const _closeNicknameModal = function() {
        var modal = document.getElementById("nickname-modal");
        if (modal) modal.classList.remove("show");
    };
    
    const _saveNickname = function() {
        if (!_state.currentUser) return;
        var input = document.getElementById("nickname-input");
        var nickname = input ? input.value.trim() : '';
        if (nickname) {
            _state.nicknames[_state.currentUser] = nickname;
        } else {
            delete _state.nicknames[_state.currentUser];
        }
        localStorage.setItem("zyn_nicknames", JSON.stringify(_state.nicknames));
        var title = document.getElementById("chat-header-title");
        if (title) title.textContent = nickname || _state.currentUser;
        _closeNicknameModal();
        _toast(nickname ? "备注名已保存" : "备注名已清除");
    };
    
    const _loadHistory = async function(e) {
        const t = e ? `/history?user=${encodeURIComponent(e)}&limit=500` : "/history?limit=500";
        const n = await _get(t);
        if (!n || n.error) return;
        const o = n.messages || [];
        if (o.length === 0) return;
        const i = document.getElementById("messages-area");
        if (i) i.innerHTML = "";
        _state.displayedIds.clear();
        o.forEach((function(e) {
            _renderMsg(e);
            if (e.id) _state.displayedIds.add(e.id);
        }));
        if (o.length > 0) {
            const e = Math.max.apply(null, o.map((function(e) { return e.id || 0; })));
            _state.lastMsgId = Math.max(_state.lastMsgId, e);
        }
        const r = document.getElementById("messages-area");
        if (r) r.scrollTop = r.scrollHeight;
    };
    
    const _fetchMessages = async function() {
        const e = _state.currentUser ? "&user=" + encodeURIComponent(_state.currentUser) : "";
        const t = await _get("messages?since=" + _state.lastMsgId + e);
        if (t && t.messages) {
            t.messages.forEach((function(e) {
                if (e.id && !_state.displayedIds.has(e.id)) {
                    if (_state.view === 'chat' && _state.currentUser) {
                        _renderMsg(e);
                    }
                    _state.displayedIds.add(e.id);
                    _state.lastMsgId = Math.max(_state.lastMsgId, e.id);
                    var fromUser = e.from || _state.currentUser;
                    if (fromUser) {
                        _state.lastMessages[fromUser] = {
                            text: e.text || '',
                            time: e.time || '',
                            media_type: e.media_type
                        };
                    }
                }
            }));
            if (_state.view === 'list') {
                _renderChatList();
            }
        }
    };
    
    const _startPoll = function() {
        if (_state.pollInterval) clearInterval(_state.pollInterval);
        _state.pollInterval = setInterval(_fetchMessages, 500);
    };
    
    const _sendMsg = async function() {
        const e = document.getElementById("message-input");
        const t = e ? e.value.trim() : "";
        if (!t) {
            _toast("请输入消息内容");
            return;
        }
        if (!_state.currentUser) {
            _toast("请先选择用户");
            return;
        }
        if (e) e.value = "";
        const n = await _api("send", { text: t });
        if (n && n.success) {
            setTimeout(_fetchMessages, 200);
            _toast("发送成功");
        } else {
            _toast((n && n.error) || "发送失败");
            if (e) e.value = t;
        }
    };
    
    const _toggleMediaPanel = function() {
        const panel = document.getElementById("media-panel");
        const btn = document.getElementById("plus-btn");
        if (!panel || !btn) return;
        if (panel.classList.contains("show")) {
            panel.classList.remove("show");
            btn.classList.remove("active");
        } else {
            panel.classList.add("show");
            btn.classList.add("active");
            const input = document.getElementById("message-input");
            if (input) input.blur();
        }
    };
    
    const _closeMediaPanel = function() {
        const panel = document.getElementById("media-panel");
        const btn = document.getElementById("plus-btn");
        if (panel) panel.classList.remove("show");
        if (btn) btn.classList.remove("active");
    };
    
    const _showUploadProgress = function(text) {
        const el = document.getElementById("media-upload-progress");
        const txt = el ? el.querySelector(".media-upload-text") : null;
        if (txt) txt.textContent = text || "正在发送...";
        if (el) el.classList.add("show");
    };
    
    const _hideUploadProgress = function() {
        const el = document.getElementById("media-upload-progress");
        if (el) el.classList.remove("show");
    };
    
    const _readFileAsBase64 = function(file) {
        return new Promise(function(resolve, reject) {
            var reader = new FileReader();
            reader.onload = function() {
                var result = reader.result;
                var base64 = result.split(",")[1] || result;
                resolve(base64);
            };
            reader.onerror = function() { reject(reader.error); };
            reader.readAsDataURL(file);
        });
    };
    
    const _readFileAsArrayBuffer = function(file) {
        return new Promise(function(resolve, reject) {
            var reader = new FileReader();
            reader.onload = function() { resolve(reader.result); };
            reader.onerror = function() { reject(reader.error); };
            reader.readAsArrayBuffer(file);
        });
    };
    
    const _generateThumbnail = function(file, maxWidth, maxHeight) {
        return new Promise(function(resolve) {
            if (file.type && file.type.startsWith("image/")) {
                var img = new Image();
                var url = URL.createObjectURL(file);
                img.onload = function() {
                    var w = img.width, h = img.height;
                    var scale = Math.min(maxWidth / w, maxHeight / h, 1);
                    var cw = Math.round(w * scale), ch = Math.round(h * scale);
                    var canvas = document.createElement("canvas");
                    canvas.width = cw; canvas.height = ch;
                    var ctx = canvas.getContext("2d");
                    ctx.drawImage(img, 0, 0, cw, ch);
                    URL.revokeObjectURL(url);
                    var dataUrl = canvas.toDataURL("image/jpeg", 0.6);
                    resolve(dataUrl);
                };
                img.onerror = function() { URL.revokeObjectURL(url); resolve(""); };
                img.src = url;
            } else if (file.type && file.type.startsWith("video/")) {
                var video = document.createElement("video");
                var vurl = URL.createObjectURL(file);
                video.preload = "metadata";
                video.muted = true;
                video.onloadeddata = function() {
                    video.currentTime = Math.min(1, video.duration / 4);
                };
                video.onseeked = function() {
                    var w = video.videoWidth, h = video.videoHeight;
                    var scale = Math.min(maxWidth / w, maxHeight / h, 1);
                    var cw = Math.round(w * scale), ch = Math.round(h * scale);
                    var canvas = document.createElement("canvas");
                    canvas.width = cw; canvas.height = ch;
                    var ctx = canvas.getContext("2d");
                    ctx.drawImage(video, 0, 0, cw, ch);
                    URL.revokeObjectURL(vurl);
                    var dataUrl = canvas.toDataURL("image/jpeg", 0.6);
                    resolve(dataUrl);
                };
                video.onerror = function() { URL.revokeObjectURL(vurl); resolve(""); };
                video.src = vurl;
            } else {
                resolve("");
            }
        });
    };

    const _sendMediaFile = async function(file, mediaType) {
        if (!_state.currentUser) {
            _toast("请先选择用户");
            return;
        }
        if (!file) return;
        
        var maxSize = 25 * 1024 * 1024;
        if (file.size > maxSize) {
            _toast("文件过大，最大支持 25MB");
            return;
        }
        
        _closeMediaPanel();
        
        var mediaTypeInt = {"image": 2, "voice": 3, "file": 4, "video": 5}[mediaType] || 4;
        var mediaTypeLabel = {"image": "图片", "voice": "语音", "file": "文件", "video": "视频"}[mediaType] || "文件";
        var thumbDataUrl = "";
        
        if (mediaType === "image") {
            thumbDataUrl = await _generateThumbnail(file, 200, 200);
        } else if (mediaType === "video") {
            thumbDataUrl = await _generateThumbnail(file, 200, 200);
        }
        
        var placeholderMsg = {
            from: 'me',
            to: _state.currentUser,
            text: '[' + mediaTypeLabel + '] ' + file.name,
            time: new Date().toTimeString().slice(0, 8),
            type: 'out',
            media_type: mediaTypeInt,
            media_data: thumbDataUrl,
            media_filename: file.name,
            _sending: true
        };
        
        _state._tempMsgId = (_state._tempMsgId || 0) + 1;
        placeholderMsg.id = "sending_" + _state._tempMsgId;
        
        _renderSendingMsg(placeholderMsg);
        
        try {
            var base64Data = await _readFileAsBase64(file);
            var thumbnailData = "";
            
            if (mediaType === "image" || mediaType === "video") {
                try {
                    var fullThumb = await _generateThumbnail(file, 300, 300);
                    if (fullThumb) {
                        thumbnailData = fullThumb.split(",")[1] || "";
                    }
                } catch(e) {}
            }
            
            var payload = {
                media_type: mediaType,
                filename: file.name,
                file_data: base64Data,
                file_size: file.size,
                thumbnail: thumbnailData
            };
            
            var result = await _api("send-media", payload);
            
            var sendingEl = document.querySelector('[data-sending-id="' + placeholderMsg.id + '"]');
            
            if (result && result.success && result.message) {
                var msg = result.message;
                if (!msg.id) {
                    _state._tempMsgId = (_state._tempMsgId || 0) + 1;
                    msg.id = "temp_" + _state._tempMsgId;
                }
                if (sendingEl) sendingEl.remove();
                if (!_state.displayedIds.has(msg.id)) {
                    _renderMsg(msg);
                    _state.displayedIds.add(msg.id);
                }
            } else if (result && result.success) {
                if (sendingEl) sendingEl.remove();
                setTimeout(_fetchMessages, 300);
            } else {
                if (sendingEl) {
                    var statusEl = sendingEl.querySelector('.msg-send-status');
                    if (statusEl) {
                        statusEl.className = 'msg-send-status msg-send-fail';
                        statusEl.textContent = '!';
                    }
                }
                _toast((result && result.error) || "发送失败");
            }
        } catch(e) {
            var sendingEl2 = document.querySelector('[data-sending-id="' + placeholderMsg.id + '"]');
            if (sendingEl2) {
                var statusEl2 = sendingEl2.querySelector('.msg-send-status');
                if (statusEl2) {
                    statusEl2.className = 'msg-send-status msg-send-fail';
                    statusEl2.textContent = '!';
                }
            }
            _toast("发送失败: " + (e.message || e));
        }
    };
    
    const _handlePhotoSelect = function(e) {
        var file = e.target.files && e.target.files[0];
        if (file) _sendMediaFile(file, "image");
        e.target.value = "";
    };
    
    const _handleVideoSelect = function(e) {
        var file = e.target.files && e.target.files[0];
        if (file) _sendMediaFile(file, "video");
        e.target.value = "";
    };
    
    const _handleFileSelect = function(e) {
        var file = e.target.files && e.target.files[0];
        if (file) _sendMediaFile(file, "file");
        e.target.value = "";
    };
    
    const _loadAIConfig = async function() {
        const e = await _get("ai-config");
        if (e) {
            const t = document.getElementById("ai-enabled");
            const n = document.getElementById("api-url");
            const o = document.getElementById("api-key");
            const i = document.getElementById("model-name");
            const r = document.getElementById("active-interval");
            const s = document.getElementById("min-words");
            const a = document.getElementById("max-words");
            const c = document.getElementById("system-prompt");
            if (t) t.checked = e.enabled || false;
            if (n) n.value = e.api_url || "";
            if (o) o.value = e.api_key || "";
            if (i) i.value = e.model || "gpt-3.5-turbo";
            if (r) r.value = e.active_interval || 60;
            if (s) s.value = e.min_words || 10;
            if (a) a.value = e.max_words || 200;
            if (c) c.value = e.system_prompt || "你是一个微信聊天助手，请用自然的中文回复，回复内容要简洁自然，像真人一样。";
        }
    };
    
    const _saveAIConfig = async function() {
        const e = {
            enabled: document.getElementById("ai-enabled") ? document.getElementById("ai-enabled").checked : false,
            api_url: document.getElementById("api-url") ? document.getElementById("api-url").value : "",
            api_key: document.getElementById("api-key") ? document.getElementById("api-key").value : "",
            model: document.getElementById("model-name") ? document.getElementById("model-name").value : "gpt-3.5-turbo",
            active_interval: parseInt(document.getElementById("active-interval") ? document.getElementById("active-interval").value : "60") || 60,
            min_words: parseInt(document.getElementById("min-words") ? document.getElementById("min-words").value : "10") || 10,
            max_words: parseInt(document.getElementById("max-words") ? document.getElementById("max-words").value : "200") || 200,
            system_prompt: document.getElementById("system-prompt") ? document.getElementById("system-prompt").value : ""
        };
        const t = await _api("ai-config", e);
        if (t && t.success) {
            _toast("AI 配置已保存");
            _showSettingsPage('settings-main');
        } else {
            _toast("保存失败: " + ((t && t.error) || "未知错误"));
        }
    };
    
    const _openSettings = function() {
        const e = document.getElementById("settings-panel");
        if (e) {
            e.classList.add("show");
            _showSettingsPage('settings-main');
        }
    };
    
    const _closeSettings = function() {
        const e = document.getElementById("settings-panel");
        if (e) e.classList.remove("show");
    };
    
    const _showSettingsPage = function(pageId) {
        var pages = document.querySelectorAll('.settings-page');
        pages.forEach(function(p) { p.classList.remove('active'); p.classList.remove('settings-page-slide'); });
        var target = document.getElementById(pageId);
        if (target) {
            target.classList.add('active');
            if (pageId !== 'settings-main') {
                target.classList.add('settings-page-slide');
            }
        }
        if (pageId === 'settings-api') {
            _loadAIConfig();
        } else if (pageId === 'settings-about') {
            _loadAbout();
        }
    };

    const _loadAbout = async function() {
        const authorEl = document.getElementById("about-author");
        const versionEl = document.getElementById("about-version");
        if (authorEl) authorEl.textContent = "加载中...";
        if (versionEl) versionEl.textContent = "加载中...";
        const e = await _get("about");
        if (e) {
            if (authorEl) authorEl.textContent = e.author || "未知";
            if (versionEl) versionEl.textContent = e.version || "未知";
        } else {
            if (authorEl) authorEl.textContent = "获取失败";
            if (versionEl) versionEl.textContent = "获取失败";
        }
    };
    
    const _initTheme = function() {
        var saved = localStorage.getItem('theme');
        if (saved === 'dark') {
            document.documentElement.setAttribute('data-theme', 'dark');
            var btn = document.getElementById('theme-toggle-btn');
            if (btn) btn.classList.add('active');
        }
    };
    
    const _toggleTheme = function() {
        var btn = document.getElementById('theme-toggle-btn');
        var isDark = document.documentElement.getAttribute('data-theme') === 'dark';
        if (isDark) {
            document.documentElement.removeAttribute('data-theme');
            localStorage.setItem('theme', 'light');
            if (btn) btn.classList.remove('active');
        } else {
            document.documentElement.setAttribute('data-theme', 'dark');
            localStorage.setItem('theme', 'dark');
            if (btn) btn.classList.add('active');
        }
    };
    
    const _checkStatus = async function() {
        const e = await _get("status");
        if (e && e.logged_in && e.login_done) {
            _showChat(e);
            return true;
        }
        await _loadQR();
        return false;
    };
    
    const _loadQR = async function() {
        const e = await _get("qrcode");
        if (e && (e.redirect_to_chat || e.login_done)) {
            _toast("检测到已连接，正在跳转...");
            const t = await _get("status");
            if (t && t.logged_in && t.login_done) {
                _showChat(t);
            }
            return;
        }
        if (!e || !e.matrix) {
            const t = await _get("status");
            if (t && t.logged_in && t.login_done) {
                _toast("检测到已连接，正在进入聊天...");
                _showChat(t);
                return;
            }
            const n = document.getElementById("status-text");
            if (n) n.textContent = (e && e.message) || "正在获取二维码...";
            setTimeout(_loadQR, 3000);
            return;
        }
        _renderQR(e.matrix);
        if (e.login_done) {
            _toast("连接成功！");
            setTimeout(_checkStatus, 1000);
        } else {
            setTimeout((async function() {
                const t = await _get("status");
                if (t && t.logged_in && t.login_done) {
                    _toast("扫码成功！正在进入聊天...");
                    _showChat(t);
                } else {
                    _loadQR();
                }
            }), 2000);
        }
    };
    
    const _renderQR = function(e) {
        const t = document.getElementById("qr-code");
        if (!t) return;
        const n = e.length;
        const o = e[0].length;
        const i = window.innerWidth || screen.width;
        let r;
        if (i < 768) {
            r = Math.min(i * 0.85, 320);
        } else {
            r = Math.min(300, 350);
        }
        const s = Math.max(5, Math.min(10, Math.floor((r - 80) / o)));
        const a = o * s + 40;
        let c = '<div class="qr-grid" style="grid-template-columns: repeat(' + o + ', ' + s + 'px); width: ' + a + 'px; max-width: 100%; overflow-x: auto; margin: 0 auto;">';
        for (const i of e) {
            for (const e of i) {
                c += '<div class="qr-cell ' + (e === " " ? "white" : "") + '" style="width:' + s + 'px;height:' + s + 'px;"></div>';
            }
        }
        c += "</div>";
        t.innerHTML = c;
        const l = document.getElementById("qr-loading");
        if (l) l.style.display = "none";
        const d = document.getElementById("status-text");
        if (d) d.innerHTML = '<div class="qr-tip">请使用微信扫码连接</div><div class="qr-subtip">打开手机微信 → 扫一扫 → 确认连接</div>';
    };
    
    const _showChat = function(e) {
        const t = document.getElementById("login-page");
        if (t) t.style.display = "none";
        _state.users = e.users || [];
        _state.view = 'list';
        const n = document.getElementById("chat-list-page");
        if (n) n.classList.add("active");
        _renderChatList();
        _loadChatListPreviews();
        _startPoll();
        _toast("进入聊天界面");
    };
    
    const _manualRefresh = async function() {
        const e = document.getElementById("refresh-btn");
        const t = e ? e.textContent : "";
        if (e) {
            e.textContent = "检查中...";
            e.disabled = true;
        }
        try {
            _toast("正在检查连接状态...");
            const n = await _get("status");
            if (n && n.logged_in && n.login_done) {
                _toast("已连接，正在进入聊天...");
                _showChat(n);
            } else if (n && n.logged_in) {
                _toast("已获取 token，等待完成连接...");
            } else {
                _toast("未连接，请扫描二维码");
            }
        } catch(e) {
            _toast("检查失败");
        } finally {
            setTimeout((function() {
                if (e) {
                    e.textContent = t;
                    e.disabled = false;
                }
            }), 1500);
        }
    };
    
    const _forceChat = async function() {
        const e = document.getElementById("force-chat-btn");
        if (e) {
            e.textContent = "进入中...";
            e.disabled = true;
        }
        try {
            _toast("正在进入聊天界面...");
            const t = await _get("status");
            if (!t) throw new Error("无法获取状态");
            _showChat(t);
        } catch(t) {
            try {
                const n = document.getElementById("login-page");
                if (n) n.style.display = "none";
                _state.users = [];
                _state.view = 'list';
                const o = document.getElementById("chat-list-page");
                if (o) o.classList.add("active");
                _renderChatList();
                _startPoll();
                _toast("已强制进入聊天");
            } catch(e) {
                _toast("强制进入失败");
            }
        } finally {
            setTimeout((function() {
                if (e) {
                    e.textContent = "进入聊天";
                    e.disabled = false;
                }
            }), 2000);
        }
    };
    
    const _initEvents = function() {
        document.addEventListener("error", function(ev) {
            var img = ev.target;
            if (img.tagName === 'IMG' && img.classList.contains('bubble-media-img')) {
                var wrap = img.closest('.bubble-media-img-wrap');
                if (wrap && wrap.dataset.cdn && !wrap.classList.contains('bubble-media-loading') && img.src.indexOf('/api/wasm/media/') === -1) {
                    wrap.classList.add('bubble-media-loading');
                    wrap.innerHTML = '<div class="bubble-media-placeholder">' + _svgImage + '<span>图片</span></div>';
                    window._loadCdnMedia(wrap);
                }
            }
        }, true);
        document.addEventListener("click", function(ev) {
            var thumb = ev.target.closest("[data-action='play-video']");
            if (thumb) {
                var videoSrc = thumb.dataset.videoSrc;
                if (videoSrc) {
                    window._previewVideo(videoSrc);
                } else {
                    var imgEl = thumb.querySelector('img');
                    if (imgEl && imgEl.src && imgEl.src.indexOf('/api/wasm/media/') !== -1) {
                        window._previewVideo(imgEl.src);
                    }
                }
                return;
            }
        });
        const e = document.getElementById("send-btn");
        if (e) e.addEventListener("click", _sendMsg);
        const t = document.getElementById("message-input");
        if (t) {
            t.addEventListener("keypress", function(e) { if (e.key === "Enter") { _closeMediaPanel(); _sendMsg(); } });
            t.addEventListener("focus", function() { _closeMediaPanel(); });
        }
        const plusBtn = document.getElementById("plus-btn");
        if (plusBtn) plusBtn.addEventListener("click", _toggleMediaPanel);
        const photoOpt = document.getElementById("media-photo");
        if (photoOpt) photoOpt.addEventListener("click", function() { document.getElementById("file-photo").click(); });
        const cameraOpt = document.getElementById("media-camera");
        if (cameraOpt) cameraOpt.addEventListener("click", function() { document.getElementById("file-camera").click(); });
        const videoOpt = document.getElementById("media-video");
        if (videoOpt) videoOpt.addEventListener("click", function() { document.getElementById("file-video").click(); });
        const fileOpt = document.getElementById("media-file");
        if (fileOpt) fileOpt.addEventListener("click", function() { document.getElementById("file-doc").click(); });
        const filePhoto = document.getElementById("file-photo");
        if (filePhoto) filePhoto.addEventListener("change", _handlePhotoSelect);
        const fileCamera = document.getElementById("file-camera");
        if (fileCamera) fileCamera.addEventListener("change", _handlePhotoSelect);
        const fileVideo = document.getElementById("file-video");
        if (fileVideo) fileVideo.addEventListener("change", _handleVideoSelect);
        const fileVideoCap = document.getElementById("file-video-capture");
        if (fileVideoCap) fileVideoCap.addEventListener("change", _handleVideoSelect);
        const fileDoc = document.getElementById("file-doc");
        if (fileDoc) fileDoc.addEventListener("change", _handleFileSelect);
        const n = document.getElementById("user-select-btn");
        if (n) n.addEventListener("click", function() { const e = document.getElementById("user-dropdown"); if (e) e.classList.toggle("show"); });
        const chatListSettingsBtn = document.getElementById("chat-list-settings-btn");
        if (chatListSettingsBtn) chatListSettingsBtn.addEventListener("click", _openSettings);
        const chatBackBtn = document.getElementById("chat-back-btn");
        if (chatBackBtn) chatBackBtn.addEventListener("click", _backToChatList);
        const chatMenuBtn = document.getElementById("chat-menu-btn");
        if (chatMenuBtn) chatMenuBtn.addEventListener("click", _openNicknameModal);
        const nicknameCancelBtn = document.getElementById("nickname-cancel-btn");
        if (nicknameCancelBtn) nicknameCancelBtn.addEventListener("click", _closeNicknameModal);
        const nicknameSaveBtn = document.getElementById("nickname-save-btn");
        if (nicknameSaveBtn) nicknameSaveBtn.addEventListener("click", _saveNickname);
        const nicknameInput = document.getElementById("nickname-input");
        if (nicknameInput) nicknameInput.addEventListener("keypress", function(e) { if (e.key === "Enter") _saveNickname(); });
        const i = document.getElementById("refresh-btn");
        if (i) i.onclick = _manualRefresh;
        const r = document.getElementById("force-chat-btn");
        if (r) r.onclick = _forceChat;
        const modalClose = document.getElementById("ai-modal-close");
        if (modalClose) modalClose.addEventListener("click", _closeAiModal);
        const modalCancel = document.getElementById("ai-modal-cancel");
        if (modalCancel) modalCancel.addEventListener("click", _closeAiModal);
        const modalSend = document.getElementById("ai-modal-send");
        if (modalSend) modalSend.addEventListener("click", _sendAiReply);
        document.addEventListener("click", function(e) {
            const t = document.getElementById("user-dropdown");
            const n = document.getElementById("user-select-btn");
            const o = document.getElementById("settings-panel");
            const chatListSettingsBtn = document.getElementById("chat-list-settings-btn");
            const modal = document.getElementById("ai-modal");
            const mediaPanel = document.getElementById("media-panel");
            const plusBtn = document.getElementById("plus-btn");
            const nicknameModal = document.getElementById("nickname-modal");
            if (t && !t.contains(e.target) && n && !n.contains(e.target)) {
                t.classList.remove("show");
            }
            if (o && o.classList.contains("show") && !o.contains(e.target) && chatListSettingsBtn && !chatListSettingsBtn.contains(e.target)) {
                _closeSettings();
            }
            if (modal && modal.classList.contains("show") && e.target === modal) {
                _closeAiModal();
            }
            if (nicknameModal && nicknameModal.classList.contains("show") && e.target === nicknameModal) {
                _closeNicknameModal();
            }
            if (mediaPanel && mediaPanel.classList.contains("show") && !mediaPanel.contains(e.target) && plusBtn && !plusBtn.contains(e.target)) {
                _closeMediaPanel();
            }
        });
        const s = document.getElementById("settings-back-btn");
        if (s) s.addEventListener("click", _closeSettings);
        const apiBackBtn = document.getElementById("api-back-btn");
        if (apiBackBtn) apiBackBtn.addEventListener("click", function() { _showSettingsPage('settings-main'); });
        const apiItem = document.getElementById("settings-api-item");
        if (apiItem) apiItem.addEventListener("click", function() { _showSettingsPage('settings-api'); });
        const aboutItem = document.getElementById("settings-about-item");
        if (aboutItem) aboutItem.addEventListener("click", function() { _showSettingsPage('settings-about'); });
        const aboutBackBtn = document.getElementById("about-back-btn");
        if (aboutBackBtn) aboutBackBtn.addEventListener("click", function() { _showSettingsPage('settings-main'); });
        const themeBtn = document.getElementById("theme-toggle-btn");
        if (themeBtn) themeBtn.addEventListener("click", function(ev) { ev.stopPropagation(); _toggleTheme(); });
        const themeItem = document.getElementById("settings-theme-item");
        if (themeItem) themeItem.addEventListener("click", function() { _toggleTheme(); });
        const a = document.querySelector(".settings-save");
        if (a) a.addEventListener("click", _saveAIConfig);
    };
    
    const _init = function() {
        antiDebug();
        _initTheme();
        _initEvents();
        _checkStatus();
    };
    
    return { init: _init };
})();

window.ZynWasm = window.__ZN''' + session_token[:16] + ''';
window.ZynWasm.init();
'''
    
    def start_web_interface(self):
        if self._http_server is not None:
            print(f"网页服务已在运行中: http://localhost:{self._web_port}")
            return
        
        port = self._web_port
        handler = self._make_web_handler()
        
        bind_addresses = [""]
        if is_termux():
            bind_addresses = ["127.0.0.1", "localhost", ""]
            print("[TERMUX] 使用 Termux 兼容模式启动 Web 服务")
        
        server_started = False
        
        for bind_addr in bind_addresses:
            try:
                self._http_server = socketserver.ThreadingTCPServer((bind_addr, port), handler)
                self._server_thread = threading.Thread(target=self._http_server.serve_forever, daemon=True)
                self._server_thread.start()
                
                display_addr = "localhost" if bind_addr else "127.0.0.1"
                print(f"\n[WEB] 网页界面已启动: http://{display_addr}:{port}")
                print("     支持扫码连接和聊天功能")
                if is_termux():
                    print("     [TERMUX] 提示: 如果无法访问，请使用端口转发或反向代理")
                server_started = True
                break
            except OSError as e:
                if bind_addr != "":
                    continue
                for p in range(port + 1, port + 100):
                    try:
                        self._web_port = p
                        self._http_server = socketserver.ThreadingTCPServer((bind_addr, p), handler)
                        self._server_thread = threading.Thread(target=self._http_server.serve_forever, daemon=True)
                        self._server_thread.start()
                        
                        display_addr = "localhost" if bind_addr else "127.0.0.1"
                        print(f"\n[WEB] 网页界面已启动: http://{display_addr}:{p}")
                        print("     支持扫码连接和聊天功能")
                        server_started = True
                        break
                    except OSError:
                        continue
                
                if server_started:
                    break
        
        if not server_started:
            print("[ERROR] 无法启动网页服务，端口均被占用")
            if is_termux():
                print("[TERMUX] 提示: Termux 可能需要特殊权限才能绑定端口")
                print("         尝试: termux-chroot 或使用 root 权限")
    
    def _make_web_handler(self):
        bot = self
        
        class WebHandler(SimpleHTTPRequestHandler):
            def log_message(self, format, *args):
                pass
            
            def _check_auth(self):
                session_token = self.headers.get('X-Session-Token')
                if session_token and bot._verify_session_token(session_token):
                    return True
                cookie_header = self.headers.get('Cookie', '')
                if cookie_header:
                    for part in cookie_header.split(';'):
                        part = part.strip()
                        if part.startswith('session_token='):
                            token = part.split('=', 1)[1]
                            if token and bot._verify_session_token(token):
                                return True
                parsed = urllib.parse.urlparse(self.path)
                params = urllib.parse.parse_qs(parsed.query)
                token_param = params.get('token', [None])[0]
                if token_param and bot._verify_session_token(token_param):
                    return True
                return False
            
            def do_GET(self):
                parsed = urllib.parse.urlparse(self.path)
                
                if parsed.path == '/':
                    self._serve_wasm_page()
                elif parsed.path.startswith('/api/wasm/'):
                    if not self._check_auth():
                        self.send_response(401)
                        self.end_headers()
                        return
                    api_path = parsed.path[10:]
                    if api_path == 'status':
                        self._serve_status()
                    elif api_path == 'qrcode':
                        self._serve_qrcode()
                    elif api_path == 'messages':
                        self._serve_messages()
                    elif api_path == 'users':
                        self._serve_users()
                    elif api_path == 'history':
                        self._serve_history()
                    elif api_path == 'ai-config':
                        self._serve_ai_config()
                    elif api_path == 'about':
                        self._serve_about()
                    elif api_path.startswith('media/'):
                        self._serve_cached_media(api_path[6:])
                    else:
                        self.send_error(404)
                else:
                    self.send_error(404)
            
            def do_POST(self):
                if not self._check_auth():
                    self.send_response(401)
                    self.end_headers()
                    return
                
                data = self._parse_json_body()
                if data is None:
                    return
                
                parsed = urllib.parse.urlparse(self.path)
                
                if parsed.path == '/api/wasm/send':
                    self._handle_send(data)
                elif parsed.path == '/api/wasm/send-media':
                    self._handle_send_media(data)
                elif parsed.path == '/api/wasm/download-media':
                    self._handle_download_media(data)
                elif parsed.path == '/api/wasm/switch-user':
                    self._handle_switch_user(data)
                elif parsed.path == '/api/wasm/ai-config':
                    self._handle_save_ai_config(data)
                elif parsed.path == '/api/wasm/ai-manual-reply':
                    self._handle_ai_manual_reply(data)
                else:
                    self.send_error(404)
            
            def _parse_json_body(self):
                content_length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(content_length) if content_length else b'{}'
                try:
                    return json.loads(body.decode('utf-8'))
                except (json.JSONDecodeError, UnicodeDecodeError) as e:
                    self._send_json({'success': False, 'error': f'请求数据格式错误: {e}'}, 400)
                    return None
            
            def _handle_ai_manual_reply(self, data):
                try:
                    user_id = data.get('user_id')
                    original_message = data.get('original_message', '')
                    instruction = data.get('instruction', '')
                    
                    if not user_id:
                        self._send_json({'success': False, 'error': '用户ID不能为空'})
                        return
                    
                    print(f"[WEB] 收到手动 AI 回复请求: user={user_id}, msg={original_message[:50]}, instruction={instruction[:50] if instruction else '无'}")
                    
                    success = bot._manual_ai_reply(user_id, original_message, instruction)
                    
                    if success:
                        self._send_json({'success': True, 'message': 'AI 回复已发送'})
                    else:
                        self._send_json({'success': False, 'error': 'AI 回复失败，请检查 API 配置'})
                        
                except Exception as e:
                    print(f"[WEB] 手动 AI 回复异常: {e}")
                    self._send_json({'success': False, 'error': str(e)})
            
            def _serve_wasm_page(self):
                session_token = bot._generate_session_token()
                html = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
<title>Zyn iLink ChatBox</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
html, body { width: 100%; height: 100%; overflow: hidden; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; font-size: 14px; background: var(--chat-bg); }
:root { --bg-primary: #FFFFFF; --bg-secondary: #F5F5F5; --accent: #07C160; --accent-hover: #06AD56; --accent-light: #E8F8EF; --text-primary: #111111; --text-secondary: #576B95; --text-hint: #B2B2B2; --bubble-out: #95EC69; --bubble-in: #FFFFFF; --divider: #E7E7E7; --header-height: 56px; --nav-bg: #FFFFFF; --chat-bg: #EDEDED; --input-bg: #FFFFFF; --setting-item-bg: #FFFFFF; --setting-arrow: #C7C7CC; --toggle-off: #E5E5E5; }
[data-theme="dark"] { --bg-primary: #1C1C1E; --bg-secondary: #2C2C2E; --accent: #30D158; --accent-hover: #28B84C; --accent-light: #1C3A25; --text-primary: #F5F5F5; --text-secondary: #8E8E93; --text-hint: #636366; --bubble-out: #2D6A18; --bubble-in: #2C2C2E; --divider: #38383A; --nav-bg: #1C1C1E; --chat-bg: #000000; --input-bg: #2C2C2E; --setting-item-bg: #2C2C2E; --setting-arrow: #48484A; --toggle-off: #39393D; }
#app { display: flex; width: 100%; height: 100%; background: var(--bg-primary); position: relative; overflow: hidden; }
.login-container { width: 100%; height: 100%; display: flex; flex-direction: column; align-items: center; background: #F5F5F5; overflow-y: auto; }
.login-header { width: 100%; background: var(--accent); color: white; text-align: center; padding: 48px 20px 36px; position: relative; }
.login-header::after { content: ''; position: absolute; bottom: -16px; left: 0; right: 0; height: 32px; background: #F5F5F5; border-radius: 50% 50% 0 0 / 100% 100% 0 0; }
.login-header h1 { font-size: 28px; font-weight: 600; margin-bottom: 6px; letter-spacing: 2px; }
.login-header p { font-size: 14px; opacity: 0.85; letter-spacing: 1px; }
.qr-container { background: #FFFFFF; border-radius: 8px; padding: 36px 28px; box-shadow: 0 2px 12px rgba(0,0,0,0.08); text-align: center; max-width: 320px; width: calc(100% - 40px); margin: 24px 20px; border: 1px solid #E8E8E8; }
#qr-code { margin: 25px auto; display: flex; justify-content: center; max-width: 100%; overflow: visible; }
.qr-grid { display: grid; gap: 0; background: #FFFFFF; padding: 16px; border-radius: 4px; border: 1px solid #D9D9D9; max-width: 300px; width: auto; min-width: 180px; box-sizing: border-box; image-rendering: pixelated; margin: 0 auto; }
.qr-cell { width: 9px; height: 9px; background: #000000; min-width: 5px; min-height: 5px; display: block; }
.qr-cell.white { background: #FFFFFF; }
.qr-tip { color: var(--accent); font-size: 15px; font-weight: 500; margin: 20px 0 8px; }
.qr-subtip { color: #999; font-size: 12px; }
.status-text { color: #8C8C8C; font-size: 14px; margin-top: 15px; }
.loading-spinner { width: 40px; height: 40px; border: 3px solid #F3F3F3; border-top: 3px solid var(--accent); border-radius: 50%; animation: spin 1s linear infinite; margin: 20px auto; }
@keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
.chat-container { display: none; flex-direction: column; width: 100%; height: 100%; }
.chat-container.active { display: flex; }
.chat-header { height: var(--header-height); background: var(--nav-bg); display: flex; align-items: center; justify-content: center; padding: 0 48px; flex-shrink: 0; border-bottom: 1px solid var(--divider); position: relative; }
.chat-header-title { font-size: 17px; font-weight: 600; color: var(--text-primary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 100%; }
.settings-toggle { position: absolute; left: 12px; top: 50%; transform: translateY(-50%); width: 32px; height: 32px; border-radius: 50%; background: transparent; color: var(--text-secondary); border: none; cursor: pointer; display: flex; align-items: center; justify-content: center; font-size: 20px; }
.user-selector { position: absolute; left: 50%; transform: translateX(-50%); padding: 6px 12px; border: 1px solid var(--divider); border-radius: 6px; background: var(--bg-primary); cursor: pointer; font-size: 14px; color: var(--text-primary); max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.user-dropdown { position: absolute; top: 100%; left: 50%; transform: translateX(-50%); background: var(--bg-primary); border-radius: 8px; box-shadow: 0 4px 20px rgba(0,0,0,0.15); min-width: 200px; z-index: 100; display: none; margin-top: 4px; }
.user-dropdown.show { display: block; }
.user-option { padding: 12px 16px; cursor: pointer; transition: background 0.15s; border-bottom: 1px solid var(--divider); }
.user-option:last-child { border-bottom: none; }
.user-option:hover { background: var(--bg-secondary); }
.user-option.current { background: rgba(7, 193, 96, 0.1); color: var(--accent); font-weight: 500; }
.messages-area { flex: 1; overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 8px; background: var(--chat-bg); }
.msg-row { display: flex; align-items: flex-end; gap: 8px; max-width: 80%; }
.msg-row.out { flex-direction: row-reverse; margin-left: auto; }
.bubble { position: relative; padding: 10px 14px; border-radius: 18px; max-width: 100%; line-height: 1.4; font-size: 14px; color: var(--text-primary); word-break: break-word; cursor: pointer; transition: background 0.2s; }
.bubble.in { background: var(--bubble-in); border-bottom-left-radius: 4px; }
.bubble.in:hover { background: var(--bg-secondary); }
.bubble.out { background: var(--bubble-out); border-bottom-right-radius: 4px; cursor: default; }
.bubble.out:hover { background: var(--bubble-out); }
.bubble-text { margin-bottom: 4px; }
.msg-time { font-size: 11px; color: var(--text-hint); margin-top: 4px; text-align: right; }
.msg-time-row { display: flex; align-items: center; justify-content: flex-end; gap: 4px; margin-top: 4px; }
.msg-send-status { display: inline-flex; align-items: center; justify-content: center; }
.msg-send-loading { width: 14px; height: 14px; border: 2px solid var(--text-hint); border-top-color: transparent; border-radius: 50%; animation: spin 0.8s linear infinite; }
.msg-send-fail { width: 18px; height: 18px; border-radius: 50%; background: #FA5151; color: #fff; font-size: 12px; font-weight: 700; line-height: 18px; text-align: center; cursor: pointer; }
.input-area { background: var(--input-bg); padding: 12px 16px; display: flex; gap: 12px; align-items: center; border-top: 1px solid var(--divider); flex-shrink: 0; }
.message-input { flex: 1; height: 44px; border: 1px solid var(--divider); border-radius: 22px; padding: 0 20px; font-size: 14px; outline: none; transition: border-color 0.2s; background: var(--bg-primary); color: var(--text-primary); }
.message-input:focus { border-color: var(--accent); }
.send-button { width: 44px; height: 44px; border-radius: 50%; border: none; background: var(--accent); color: white; cursor: pointer; display: flex; align-items: center; justify-content: center; transition: all 0.2s; font-size: 18px; }
.send-button:hover { background: var(--accent-hover); transform: scale(1.05); }
.send-button:active { transform: scale(0.95); }
.plus-button { width: 44px; height: 44px; border-radius: 50%; border: none; background: transparent; color: var(--text-secondary); cursor: pointer; display: flex; align-items: center; justify-content: center; transition: all 0.2s; font-size: 28px; font-weight: 300; flex-shrink: 0; user-select: none; -webkit-user-select: none; }
.plus-button:hover { color: var(--text-primary); }
.plus-button:active { transform: scale(0.9); }
.plus-button.active { color: var(--accent); transform: rotate(45deg); }
.media-panel { background: #F5F5F5; border-top: 1px solid var(--divider); display: none; flex-direction: column; flex-shrink: 0; overflow: hidden; transition: max-height 0.3s ease; }
.media-panel.show { display: flex; }
.media-panel-inner { padding: 20px 16px; display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; justify-items: center; }
.media-option { display: flex; flex-direction: column; align-items: center; gap: 8px; cursor: pointer; -webkit-tap-highlight-color: transparent; user-select: none; -webkit-user-select: none; }
.media-option:active .media-option-icon { transform: scale(0.9); background: #D9D9D9; }
.media-option-icon { width: 56px; height: 56px; border-radius: 12px; background: var(--bg-primary); display: flex; align-items: center; justify-content: center; font-size: 26px; transition: all 0.15s; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
.media-option-label { font-size: 11px; color: var(--text-secondary); text-align: center; line-height: 1.2; }
.media-upload-progress { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.45); display: none; align-items: center; justify-content: center; z-index: 10001; }
.media-upload-progress.show { display: flex; }
.media-upload-box { background: rgba(0,0,0,0.75); border-radius: 12px; padding: 28px 32px; text-align: center; color: #fff; min-width: 140px; }
.media-upload-spinner { width: 36px; height: 36px; border: 3px solid rgba(255,255,255,0.2); border-top: 3px solid #fff; border-radius: 50%; animation: spin 0.8s linear infinite; margin: 0 auto 14px; }
.media-upload-text { font-size: 14px; }
.bubble-media-img { max-width: 200px; max-height: 200px; border-radius: 8px; cursor: pointer; display: block; object-fit: cover; }
.bubble-media-file { display: flex; align-items: center; gap: 10px; min-width: 180px; cursor: pointer; }
.bubble-media-file-icon { width: 40px; height: 40px; border-radius: 8px; background: var(--accent-light); display: flex; align-items: center; justify-content: center; font-size: 20px; flex-shrink: 0; }
.bubble-media-file-info { flex: 1; min-width: 0; }
.bubble-media-file-name { font-size: 14px; color: var(--text-primary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 140px; }
.bubble-media-file-size { font-size: 11px; color: var(--text-hint); margin-top: 2px; }
.bubble-media-voice { display: flex; align-items: center; gap: 8px; min-width: 80px; cursor: pointer; }
.bubble-media-voice-bars { display: flex; align-items: center; gap: 2px; height: 20px; }
.bubble-media-voice-bar { width: 3px; border-radius: 2px; background: var(--text-primary); }
.bubble-media-voice-dur { font-size: 12px; color: var(--text-hint); }
.bubble-media-voice.voice-playing .bubble-media-voice-bar { animation: voiceBarPulse 0.6s ease-in-out infinite alternate; }
@keyframes voiceBarPulse { 0% { opacity: 0.4; } 100% { opacity: 1; } }
.bubble-media-img-wrap { position: relative; overflow: hidden; border-radius: 8px; background: #f0f0f0; min-height: 80px; display: flex; align-items: center; justify-content: center; }
.bubble-media-placeholder { display: flex; flex-direction: column; align-items: center; gap: 6px; padding: 20px; color: #999; font-size: 12px; }
.bubble-media-placeholder span { white-space: nowrap; }
.bubble-media-loading { cursor: wait; }
.bubble-media-loading .bubble-media-placeholder { animation: pulse 1.5s ease-in-out infinite; }
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }
.bubble-media-video-thumb { position: relative; cursor: pointer; }
.bubble-media-video-thumb-vid { max-width: 100%; max-height: 240px; border-radius: 8px; display: block; object-fit: contain; background: #000; }
.bubble-media-play-btn { position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); width: 48px; height: 48px; border-radius: 50%; background: rgba(0,0,0,0.4); display: flex; align-items: center; justify-content: center; pointer-events: none; }
.bubble-media-play-btn svg { width: 24px; height: 24px; fill: #fff; margin-left: 2px; }
.toast { position: fixed; top: 70px; left: 50%; transform: translateX(-50%) translateY(-100px); background: rgba(0,0,0,0.78); color: #fff; padding: 10px 22px; border-radius: 4px; font-size: 14px; z-index: 9999; transition: transform 0.3s cubic-bezier(0.2, 0.9, 0.4, 1.1); pointer-events: none; white-space: nowrap; max-width: 90%; overflow: hidden; text-overflow: ellipsis; }
.toast.show { transform: translateX(-50%) translateY(0); }
.empty-state { text-align: center; padding: 60px 20px; color: var(--text-secondary); }
.empty-state-icon { font-size: 64px; margin-bottom: 16px; opacity: 0.3; }
.settings-panel { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: var(--bg-secondary); z-index: 1000; display: none; flex-direction: column; overflow: hidden; }
.settings-panel.show { display: flex; }
.settings-page { position: absolute; top: 0; left: 0; right: 0; bottom: 0; background: var(--bg-secondary); display: none; flex-direction: column; overflow: hidden; }
.settings-page.active { display: flex; }
.settings-page-slide { animation: slideInRight 0.25s ease; }
@keyframes slideInRight { from { transform: translateX(100%); } to { transform: translateX(0); } }
.settings-nav-header { height: var(--header-height); background: var(--nav-bg); display: flex; align-items: center; padding: 0 16px; flex-shrink: 0; border-bottom: 1px solid var(--divider); gap: 12px; }
.settings-nav-header .back-btn { width: 28px; height: 28px; border: none; background: transparent; color: var(--accent); font-size: 22px; cursor: pointer; display: flex; align-items: center; justify-content: center; padding: 0; }
.settings-nav-header .nav-title { font-size: 17px; font-weight: 600; color: var(--text-primary); }
.settings-scroll { flex: 1; overflow-y: auto; -webkit-overflow-scrolling: touch; }
.settings-group { margin-top: 22px; }
.settings-group:first-child { margin-top: 12px; }
.settings-group-title { padding: 0 16px 6px; font-size: 12px; color: var(--text-hint); }
.settings-item { display: flex; align-items: center; padding: 14px 16px; background: var(--setting-item-bg); cursor: pointer; transition: background 0.15s; min-height: 52px; }
.settings-item:active { background: var(--bg-secondary); }
.settings-item + .settings-item { border-top: 1px solid var(--divider); margin-left: 16px; margin-right: 16px; padding-left: 0; padding-right: 0; }
.settings-item:first-child { border-radius: 10px 10px 0 0; }
.settings-item:last-child { border-radius: 0 0 10px 10px; }
.settings-item:only-child { border-radius: 10px; }
.settings-item-icon { width: 28px; height: 28px; border-radius: 6px; display: flex; align-items: center; justify-content: center; margin-right: 14px; font-size: 16px; flex-shrink: 0; }
.settings-item-content { flex: 1; min-width: 0; }
.settings-item-label { font-size: 16px; color: var(--text-primary); }
.settings-item-desc { font-size: 12px; color: var(--text-hint); margin-top: 2px; }
.settings-item-arrow { color: var(--setting-arrow); font-size: 16px; margin-left: 8px; flex-shrink: 0; }
.settings-item-action { margin-left: 8px; flex-shrink: 0; }
.theme-toggle { width: 51px; height: 31px; border-radius: 16px; background: var(--toggle-off); position: relative; cursor: pointer; transition: background 0.3s; border: none; padding: 0; }
.theme-toggle.active { background: var(--accent); }
.theme-toggle-knob { width: 27px; height: 27px; border-radius: 50%; background: #FFFFFF; position: absolute; top: 2px; left: 2px; transition: transform 0.3s; box-shadow: 0 1px 3px rgba(0,0,0,0.2); }
.theme-toggle.active .theme-toggle-knob { transform: translateX(20px); }
.settings-header { padding: 16px; background: var(--accent); color: white; border-radius: 16px 16px 0 0; font-weight: 600; display: flex; justify-content: space-between; align-items: center; position: sticky; top: 0; }
.settings-close { background: none; border: none; color: white; font-size: 20px; cursor: pointer; }
.settings-body { padding: 16px; padding-bottom: 32px; }
.setting-item { margin-bottom: 16px; }
.setting-label { display: block; font-size: 14px; color: var(--text-primary); margin-bottom: 6px; font-weight: 500; }
.setting-input, .setting-select { width: 100%; padding: 10px 12px; border: 1px solid var(--divider); border-radius: 8px; font-size: 14px; outline: none; background: var(--bg-primary); color: var(--text-primary); }
.setting-input:focus { border-color: var(--accent); }
.setting-checkbox { display: flex; align-items: center; gap: 8px; cursor: pointer; }
.setting-checkbox input { width: 18px; height: 18px; cursor: pointer; }
.setting-row { display: flex; gap: 12px; }
.setting-row .setting-item { flex: 1; }
.settings-save { width: 100%; padding: 12px; background: var(--accent); color: white; border: none; border-radius: 8px; font-size: 16px; font-weight: 500; cursor: pointer; margin-top: 8px; }
.settings-save:hover { background: var(--accent-hover); }
.about-logo { display: flex; flex-direction: column; align-items: center; padding: 24px 0 16px; }
.about-logo-circle { width: 72px; height: 72px; border-radius: 50%; background: var(--accent); color: #fff; display: flex; align-items: center; justify-content: center; font-size: 26px; font-weight: 600; box-shadow: 0 4px 12px rgba(7,193,96,0.25); }
.about-logo-name { margin-top: 12px; font-size: 18px; font-weight: 600; color: var(--text-primary); }
.about-info { margin-top: 8px; background: var(--setting-item-bg); border-radius: 10px; overflow: hidden; }
.about-row { display: flex; align-items: center; justify-content: space-between; padding: 14px 16px; }
.about-row + .about-row { border-top: 1px solid var(--divider); }
.about-label { font-size: 15px; color: var(--text-secondary); }
.about-value { font-size: 15px; color: var(--text-primary); font-weight: 500; }
.refresh-btn { margin-top: 16px; padding: 10px 28px; background: #FFFFFF; color: var(--accent); border: 1px solid var(--accent); border-radius: 4px; font-size: 14px; cursor: pointer; transition: all 0.2s; font-weight: 500; }
.refresh-btn:hover { background: var(--accent); color: #FFFFFF; }
.refresh-btn:active { background: #06AD56; color: #FFFFFF; }
.refresh-btn.primary { background: var(--accent); color: #FFFFFF; border: none; }
.refresh-btn.primary:hover { background: #06AD56; }
.ai-modal { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.5); display: none; align-items: center; justify-content: center; z-index: 10000; }
.ai-modal.show { display: flex; }
.ai-modal-content { background: var(--bg-primary); border-radius: 16px; width: 90%; max-width: 400px; max-height: 80vh; overflow-y: auto; }
.ai-modal-header { padding: 16px; border-bottom: 1px solid var(--divider); font-weight: 600; font-size: 16px; display: flex; justify-content: space-between; align-items: center; }
.ai-modal-close { background: none; border: none; font-size: 24px; cursor: pointer; color: #999; padding: 0 8px; }
.ai-modal-body { padding: 16px; }
.ai-modal-msg-preview { background: var(--bg-secondary); padding: 12px; border-radius: 8px; margin-bottom: 16px; font-size: 13px; color: var(--text-secondary); word-break: break-all; max-height: 150px; overflow-y: auto; }
.ai-modal-label { font-size: 14px; color: var(--text-primary); margin-bottom: 8px; display: block; font-weight: 500; }
.ai-instruction-input { width: 100%; padding: 10px 12px; border: 1px solid var(--divider); border-radius: 8px; font-size: 14px; outline: none; resize: vertical; font-family: inherit; }
.ai-instruction-input:focus { border-color: var(--accent); }
.ai-modal-footer { padding: 16px; border-top: 1px solid var(--divider); display: flex; gap: 12px; justify-content: flex-end; }
.ai-modal-btn { padding: 8px 20px; border-radius: 8px; border: none; cursor: pointer; font-size: 14px; }
.ai-modal-btn.cancel { background: var(--bg-secondary); color: var(--text-primary); }
.ai-modal-btn.send { background: var(--accent); color: white; }
.ai-modal-btn.send:hover { background: var(--accent-hover); }
@media (max-width: 768px) { .login-header { padding: 36px 16px 28px; } .login-header h1 { font-size: 22px; } .login-header p { font-size: 13px; } .qr-container { padding: 24px 16px; margin: 20px 12px; max-width: calc(100% - 24px); } .qr-grid { padding: 12px; max-width: 280px; } .chat-header { padding: 0 40px; } .chat-header-title { font-size: 15px; } .messages-area { padding: 10px; } .input-area { padding: 8px 10px; padding-bottom: calc(8px + env(safe-area-inset-bottom, 0px)); gap: 8px; } .user-selector { max-width: 160px; font-size: 13px; } .message-input { font-size: 16px; height: 40px; } .settings-toggle { left: 8px; } .msg-row { max-width: 90%; } .bubble { padding: 8px 12px; font-size: 13px; } .plus-button { width: 40px; height: 40px; font-size: 26px; } .send-button { width: 40px; height: 40px; } .media-panel-inner { padding: 16px 12px; gap: 12px; } .media-option-icon { width: 50px; height: 50px; font-size: 22px; } .media-option-label { font-size: 10px; } .bubble-media-img { max-width: 160px; max-height: 160px; } }
@media (max-width: 480px) { .login-header { padding: 28px 14px 22px; } .login-header h1 { font-size: 20px; } .login-header::after { bottom: -12px; height: 24px; } .qr-container { padding: 16px 12px; border-radius: 6px; margin: 16px 10px; } .qr-grid { padding: 10px; max-width: 260px; } .qr-cell { min-width: 4px; min-height: 4px; } .bubble { font-size: 13px; padding: 8px 12px; } .message-input { height: 40px; font-size: 16px; } .send-button { width: 40px; height: 40px; } .refresh-btn { padding: 8px 20px; font-size: 13px; } .user-selector { max-width: 140px; font-size: 12px; } .settings-toggle { width: 28px; height: 28px; font-size: 18px; left: 6px; } .msg-row { max-width: 95%; } }
.chat-list-container { display: none; flex-direction: column; width: 100%; height: 100%; background: var(--bg-primary); }
.chat-list-container.active { display: flex; }
.chat-list-header { height: var(--header-height); background: var(--nav-bg); display: flex; align-items: center; justify-content: center; padding: 0 16px; flex-shrink: 0; border-bottom: 1px solid var(--divider); position: relative; }
.chat-list-header-title { font-size: 17px; font-weight: 600; color: var(--text-primary); }
.chat-list-settings-btn { position: absolute; right: 12px; top: 50%; transform: translateY(-50%); width: 32px; height: 32px; border-radius: 50%; background: transparent; color: var(--text-secondary); border: none; cursor: pointer; display: flex; align-items: center; justify-content: center; }
.chat-list-items { flex: 1; overflow-y: auto; -webkit-overflow-scrolling: touch; background: var(--bg-primary); }
.chat-list-item { display: flex; align-items: center; padding: 14px 16px; border-bottom: 1px solid var(--divider); cursor: pointer; transition: background 0.15s; gap: 12px; }
.chat-list-item:active { background: var(--bg-secondary); }
.chat-list-item-avatar { width: 48px; height: 48px; border-radius: 8px; background: var(--accent-light); display: flex; align-items: center; justify-content: center; font-size: 22px; flex-shrink: 0; }
.chat-list-item-content { flex: 1; min-width: 0; }
.chat-list-item-name { font-size: 16px; color: var(--text-primary); font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.chat-list-item-msg { font-size: 13px; color: var(--text-hint); margin-top: 4px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.chat-list-item-time { font-size: 11px; color: var(--text-hint); flex-shrink: 0; align-self: flex-start; margin-top: 2px; }
.chat-list-empty { text-align: center; padding: 80px 20px; color: var(--text-secondary); }
.chat-list-empty-icon { font-size: 64px; margin-bottom: 16px; opacity: 0.3; }
.chat-back-btn { position: absolute; left: 12px; top: 50%; transform: translateY(-50%); width: 32px; height: 32px; border-radius: 50%; background: transparent; color: var(--text-secondary); border: none; cursor: pointer; display: flex; align-items: center; justify-content: center; }
.chat-header-menu-btn { position: absolute; right: 12px; top: 50%; transform: translateY(-50%); width: 32px; height: 32px; border-radius: 50%; background: transparent; color: var(--text-secondary); border: none; cursor: pointer; display: flex; align-items: center; justify-content: center; }
.nickname-modal { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.5); display: none; align-items: center; justify-content: center; z-index: 10002; }
.nickname-modal.show { display: flex; }
.nickname-modal-content { background: var(--bg-primary); border-radius: 16px; width: 90%; max-width: 360px; padding: 24px; }
.nickname-modal-title { font-size: 17px; font-weight: 600; color: var(--text-primary); margin-bottom: 16px; text-align: center; }
.nickname-modal-userid { font-size: 13px; color: var(--text-hint); text-align: center; margin-bottom: 12px; word-break: break-all; }
.nickname-modal-input { width: 100%; padding: 12px; border: 1px solid var(--divider); border-radius: 8px; font-size: 16px; outline: none; background: var(--bg-primary); color: var(--text-primary); margin-bottom: 16px; }
.nickname-modal-input:focus { border-color: var(--accent); }
.nickname-modal-btns { display: flex; gap: 12px; }
.nickname-modal-btn { flex: 1; padding: 12px; border-radius: 8px; border: none; cursor: pointer; font-size: 15px; font-weight: 500; }
.nickname-modal-btn.cancel { background: var(--bg-secondary); color: var(--text-primary); }
.nickname-modal-btn.save { background: var(--accent); color: white; }
@media (max-width: 768px) { .chat-list-item { padding: 12px 14px; } .chat-list-item-avatar { width: 44px; height: 44px; font-size: 20px; } .chat-list-item-name { font-size: 15px; } .chat-list-item-msg { font-size: 12px; } .chat-back-btn { width: 28px; height: 28px; left: 8px; } .chat-header-menu-btn { width: 28px; height: 28px; right: 8px; } .chat-list-settings-btn { width: 28px; height: 28px; right: 8px; } }
@media (max-width: 480px) { .chat-list-item { padding: 10px 12px; gap: 10px; } .chat-list-item-avatar { width: 40px; height: 40px; font-size: 18px; border-radius: 6px; } .chat-list-item-name { font-size: 14px; } .chat-list-item-msg { font-size: 11px; } .chat-back-btn { width: 28px; height: 28px; left: 6px; } .chat-header-menu-btn { width: 28px; height: 28px; right: 6px; } .chat-list-settings-btn { width: 28px; height: 28px; right: 6px; } .nickname-modal-content { padding: 20px; } }
</style>
</head>
<body>
<div id="app">
    <div id="login-page" class="login-container">
        <div class="login-header">
            <h1>ZynWechat</h1>
            <p>微信官方接口 · 扫码连接</p>
        </div>
        <div class="qr-container">
            <div id="qr-loading" class="loading-spinner"></div>
            <div id="qr-code"></div>
            <div id="status-text" class="status-text">正在获取二维码...</div>
            <div style="display: flex; gap: 10px; justify-content: center; margin-top: 20px;">
                <button id="refresh-btn" class="refresh-btn">刷新状态</button>
                <button id="force-chat-btn" class="refresh-btn primary">进入聊天</button>
            </div>
        </div>
    </div>
    <div id="chat-list-page" class="chat-list-container">
        <div class="chat-list-header">
            <span class="chat-list-header-title">ZynWechat</span>
            <button id="chat-list-settings-btn" class="chat-list-settings-btn"><svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z"/></svg></button>
        </div>
        <div id="chat-list-items" class="chat-list-items">
            <div class="chat-list-empty">
                <div class="chat-list-empty-icon">💬</div>
                <div>暂无聊天</div>
            </div>
        </div>
    </div>
    <div id="chat-page" class="chat-container">
        <div class="chat-header">
            <button id="chat-back-btn" class="chat-back-btn"><svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 18 9 12 15 6"/></svg></button>
            <span id="chat-header-title" class="chat-header-title"></span>
            <button id="chat-menu-btn" class="chat-header-menu-btn"><svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="4" y1="6" x2="20" y2="6"/><line x1="4" y1="12" x2="20" y2="12"/><line x1="4" y1="18" x2="20" y2="18"/></svg></button>
        </div>
        <div id="messages-area" class="messages-area">
            <div class="empty-state">
                <div class="empty-state-icon">💬</div>
                <div>点击文本消息可使用 AI 回复，点击媒体消息可查看/下载</div>
            </div>
        </div>
        <div class="input-area">
            <button id="plus-btn" class="plus-button"><svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg></button>
            <input type="text" id="message-input" class="message-input" placeholder="输入消息..." />
            <button id="send-btn" class="send-button"><svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg></button>
        </div>
        <div id="media-panel" class="media-panel">
            <div class="media-panel-inner">
                <div class="media-option" id="media-photo">
                    <div class="media-option-icon"><svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="#333" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/></svg></div>
                    <div class="media-option-label">相册</div>
                </div>
                <div class="media-option" id="media-camera">
                    <div class="media-option-icon"><svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="#333" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M23 19a2 2 0 01-2 2H3a2 2 0 01-2-2V8a2 2 0 012-2h4l2-3h6l2 3h4a2 2 0 012 2z"/><circle cx="12" cy="13" r="4"/></svg></div>
                    <div class="media-option-label">拍摄</div>
                </div>
                <div class="media-option" id="media-video">
                    <div class="media-option-icon"><svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="#333" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><polygon points="23 7 16 12 23 17 23 7"/><rect x="1" y="5" width="15" height="14" rx="2"/></svg></div>
                    <div class="media-option-label">视频</div>
                </div>
                <div class="media-option" id="media-file">
                    <div class="media-option-icon"><svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="#333" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg></div>
                    <div class="media-option-label">文件</div>
                </div>
            </div>
        </div>
        <input type="file" id="file-photo" accept="image/*" style="display:none" />
        <input type="file" id="file-camera" accept="image/*" capture="environment" style="display:none" />
        <input type="file" id="file-video" accept="video/*" style="display:none" />
        <input type="file" id="file-video-capture" accept="video/*" capture="environment" style="display:none" />
        <input type="file" id="file-doc" accept="*/*" style="display:none" />
    </div>
</div>
<div id="settings-panel" class="settings-panel">
    <div id="settings-main" class="settings-page active">
        <div class="settings-nav-header">
            <button class="back-btn" id="settings-back-btn">‹</button>
            <span class="nav-title">设置</span>
        </div>
        <div class="settings-scroll">
            <div class="settings-group">
                <div class="settings-item" id="settings-theme-item">
                    <div class="settings-item-icon" style="background:#F0E6FF;color:#7C3AED;">Zyn</div>
                    <div class="settings-item-content">
                        <div class="settings-item-label">深色模式</div>
                    </div>
                    <div class="settings-item-action">
                        <button class="theme-toggle" id="theme-toggle-btn"><div class="theme-toggle-knob"></div></button>
                    </div>
                </div>
            </div>
            <div class="settings-group">
                <div class="settings-item" id="settings-api-item">
                    <div class="settings-item-icon" style="background:#E8F8EF;color:#07C160;">Zyn</div>
                    <div class="settings-item-content">
                        <div class="settings-item-label">AI 回复设置</div>
                        <div class="settings-item-desc">配置 AI 自动回复参数</div>
                    </div>
                    <div class="settings-item-arrow">›</div>
                </div>
            </div>
            <div class="settings-group">
                <div class="settings-item" id="settings-about-item">
                    <div class="settings-item-icon" style="background:#FFF4E6;color:#FA8C16;">Zyn</div>
                    <div class="settings-item-content">
                        <div class="settings-item-label">关于</div>
                        <div class="settings-item-desc">查看作者与版本信息</div>
                    </div>
                    <div class="settings-item-arrow">›</div>
                </div>
            </div>
        </div>
    </div>
    <div id="settings-api" class="settings-page">
        <div class="settings-nav-header">
            <button class="back-btn" id="api-back-btn">‹</button>
            <span class="nav-title">AI 回复设置</span>
        </div>
        <div class="settings-scroll">
            <div class="settings-body">
                <div class="setting-item">
                    <label class="setting-checkbox">
                        <input type="checkbox" id="ai-enabled"> 启用 AI 自动回复
                    </label>
                </div>
                <div class="setting-item">
                    <label class="setting-label">API URL</label>
                    <input type="text" id="api-url" class="setting-input" placeholder="https://api.openai.com/v1/chat/completions">
                </div>
                <div class="setting-item">
                    <label class="setting-label">API Key</label>
                    <input type="password" id="api-key" class="setting-input" placeholder="sk-...">
                </div>
                <div class="setting-item">
                    <label class="setting-label">模型名称</label>
                    <input type="text" id="model-name" class="setting-input" placeholder="gpt-3.5-turbo">
                </div>
                <div class="setting-item">
                    <label class="setting-label">主动发送间隔(秒)</label>
                    <input type="number" id="active-interval" class="setting-input" value="60" min="10" max="3600">
                </div>
                <div class="setting-row">
                    <div class="setting-item">
                        <label class="setting-label">最少字数</label>
                        <input type="number" id="min-words" class="setting-input" value="10" min="5" max="500">
                    </div>
                    <div class="setting-item">
                        <label class="setting-label">最多字数</label>
                        <input type="number" id="max-words" class="setting-input" value="200" min="20" max="1000">
                    </div>
                </div>
                <div class="setting-item">
                    <label class="setting-label">系统提示词</label>
                    <textarea id="system-prompt" class="setting-input" rows="3" placeholder="你是一个微信聊天助手..."></textarea>
                </div>
                <button class="settings-save">保存设置</button>
            </div>
        </div>
    </div>
    <div id="settings-about" class="settings-page">
        <div class="settings-nav-header">
            <button class="back-btn" id="about-back-btn">‹</button>
            <span class="nav-title">关于</span>
        </div>
        <div class="settings-scroll">
            <div class="settings-body">
                <div class="about-logo">
                    <div class="about-logo-circle">Zyn</div>
                    <div class="about-logo-name">Zyn iLink ChatBox</div>
                </div>
                <div class="about-info">
                    <div class="about-row">
                        <div class="about-label">作者名称</div>
                        <div class="about-value" id="about-author">加载中...</div>
                    </div>
                    <div class="about-row">
                        <div class="about-label">脚本版本号</div>
                        <div class="about-value" id="about-version">加载中...</div>
                    </div>
                </div>
            </div>
        </div>
    </div>
</div>
<div id="ai-modal" class="ai-modal">
    <div class="ai-modal-content">
        <div class="ai-modal-header">
            <span>Zyn AI 回复助手</span>
            <button class="ai-modal-close" id="ai-modal-close">×</button>
        </div>
        <div class="ai-modal-body">
            <div class="ai-modal-label">原消息：</div>
            <div class="ai-modal-msg-preview" id="ai-modal-msg-preview"></div>
            <label class="ai-modal-label">回复要求（可选）：</label>
            <textarea id="ai-instruction" class="ai-instruction-input" rows="3" placeholder="例如：帮我反驳他、用温和的语气回复、加个表情包、怼回去..."></textarea>
        </div>
        <div class="ai-modal-footer">
            <button class="ai-modal-btn cancel" id="ai-modal-cancel">取消</button>
            <button class="ai-modal-btn send" id="ai-modal-send">发送 AI 回复</button>
        </div>
    </div>
</div>
<div id="toast" class="toast"></div>
<div id="media-upload-progress" class="media-upload-progress">
    <div class="media-upload-box">
        <div class="media-upload-spinner"></div>
        <div class="media-upload-text">正在发送...</div>
    </div>
</div>
<div id="nickname-modal" class="nickname-modal">
    <div class="nickname-modal-content">
        <div class="nickname-modal-title">设置备注名</div>
        <div id="nickname-modal-userid" class="nickname-modal-userid"></div>
        <input type="text" id="nickname-input" class="nickname-modal-input" placeholder="输入备注名..." />
        <div class="nickname-modal-btns">
            <button id="nickname-cancel-btn" class="nickname-modal-btn cancel">取消</button>
            <button id="nickname-save-btn" class="nickname-modal-btn save">保存</button>
        </div>
    </div>
</div>
<script>
''' + bot._generate_wasm_wrapper(session_token) + '''
</script>
</body>
</html>'''
                self.send_response(200)
                self.send_header('Content-type', 'text/html; charset=utf-8')
                self.send_header('Set-Cookie', 'session_token=' + session_token + '; Path=/; SameSite=Lax')
                self.end_headers()
                self.wfile.write(html.encode('utf-8'))
            
            def _serve_status(self):
                status = {
                    'logged_in': bot.token is not None,
                    'login_done': bot._login_done,
                    'current_user': bot._current_user,
                    'bot_id': bot.bot_id,
                    'user_count': len(bot._context_tokens),
                    'users': list(bot._context_tokens.keys()),
                    'message_count': len(bot._messages)
                }
                self._send_json(status)
            
            def _serve_qrcode(self):
                if bot._login_done and bot.token:
                    self._send_json({
                        'error': 'already_logged_in',
                        'message': '已连接',
                        'login_done': True,
                        'redirect_to_chat': True
                    })
                    return
                
                if not bot._qrcode_matrix:
                    self._send_json({'error': 'no_qrcode', 'message': '正在获取二维码...'})
                    return
                
                qr_data = {
                    'matrix': bot._qrcode_matrix,
                    'qrcode_key': bot._qrcode_key,
                    'login_done': bot._login_done
                }
                self._send_json(qr_data)
            
            def _serve_messages(self):
                params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                since = params.get('since', [None])[0]
                user_filter = params.get('user', [None])[0]
                
                messages = []
                for msg in bot._messages:
                    if since and msg.get('id', 0) <= int(since):
                        continue
                    if user_filter:
                        if msg.get('type') == 'in' and msg.get('from') != user_filter:
                            continue
                        if msg.get('type') == 'out' and msg.get('to') != user_filter:
                            continue
                    msg_copy = dict(msg)
                    bot._enrich_msg_with_cache_id(msg_copy)
                    messages.append(msg_copy)
                
                self._send_json({
                    'messages': messages,
                    'current_user': bot._current_user
                })
            
            def _serve_users(self):
                users = []
                for uid in bot._context_tokens:
                    users.append({
                        'id': uid,
                        'is_current': uid == bot._current_user
                    })
                self._send_json(users)
            
            def _serve_ai_config(self):
                safe_config = {
                    "enabled": bot.ai_config.get("enabled"),
                    "api_url": bot.ai_config.get("api_url", ""),
                    "api_key": bot.ai_config.get("api_key", ""),
                    "active_interval": bot.ai_config.get("active_interval"),
                    "model": bot.ai_config.get("model"),
                    "min_words": bot.ai_config.get("min_words"),
                    "max_words": bot.ai_config.get("max_words"),
                    "system_prompt": bot.ai_config.get("system_prompt")
                }
                self._send_json(safe_config)

            def _serve_about(self):
                self._send_json({
                    "version": bot.SCRIPT_VERSION,
                    "author": bot.AUTHOR_NAME
                })
            
            def _serve_cached_media(self, cache_key):
                try:
                    if not cache_key or not all(c in '0123456789abcdef' for c in cache_key.lower()):
                        self.send_error(400)
                        return
                    cached = bot._get_cached_media(cache_key)
                    if not cached:
                        self.send_error(404)
                        return
                    media_data, mime, filename = cached
                    params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                    is_download = params.get('download', [''])[0] == '1'
                    self.send_response(200)
                    self.send_header('Content-Type', mime)
                    self.send_header('Content-Length', str(len(media_data)))
                    self.send_header('Cache-Control', 'public, max-age=31536000')
                    self.send_header('Access-Control-Allow-Origin', '*')
                    if filename:
                        disposition = 'attachment' if is_download else 'inline'
                        self.send_header('Content-Disposition', disposition + '; filename="' + filename + '"')
                    self.end_headers()
                    self.wfile.write(media_data)
                except BrokenPipeError:
                    pass
                except Exception as e:
                    print(f"[WEB] 缓存媒体服务异常: {e}")
            
            def _handle_save_ai_config(self, data):
                try:
                    print(f"[WEB] 收到 AI 配置保存请求: enabled={data.get('enabled')}, api_url={data.get('api_url', '')[:50]}, api_key={'已设置' if data.get('api_key') else '未设置'}")
                    
                    bot.ai_config["enabled"] = data.get("enabled", False)
                    bot.ai_config["api_url"] = data.get("api_url", "")
                    bot.ai_config["api_key"] = data.get("api_key", "")
                    bot.ai_config["model"] = data.get("model", "gpt-3.5-turbo")
                    bot.ai_config["active_interval"] = data.get("active_interval", 60)
                    bot.ai_config["min_words"] = data.get("min_words", 10)
                    bot.ai_config["max_words"] = data.get("max_words", 200)
                    bot.ai_config["system_prompt"] = data.get("system_prompt", "")
                    
                    bot._save_ai_config()
                    
                    if data.get('enabled'):
                        for user_id in bot._context_tokens.keys():
                            bot._schedule_active_message(user_id)
                    else:
                        for timer in bot._active_timers.values():
                            timer.cancel()
                        bot._active_timers.clear()
                    
                    self._send_json({'success': True, 'config': bot.ai_config})
                except Exception as e:
                    print(f"[WEB] 保存 AI 配置失败: {e}")
                    self._send_json({'success': False, 'error': str(e)})
            
            def _handle_send(self, data):
                try:
                    text = data.get('text', '').strip()
                    
                    print(f"[WEB] 收到发送请求: text='{text}', current_user={bot._current_user}")
                    
                    if not text:
                        self._send_json({'success': False, 'error': '消息不能为空'})
                        return
                    
                    if not bot._current_user:
                        self._send_json({'success': False, 'error': '没有选择用户'})
                        return
                    
                    success = bot.send_text(bot._current_user, text)
                    
                    if success:
                        self._send_json({'success': True, 'message': {'text': text, 'time': datetime.now().strftime('%H:%M:%S'), 'type': 'out'}})
                    else:
                        self._send_json({'success': False, 'error': '发送失败'})
                        
                except Exception as e:
                    print(f"[WEB] 发送异常: {e}")
                    self._send_json({'success': False, 'error': str(e)})
            
            def _handle_send_media(self, data):
                try:
                    media_type = data.get('media_type', '')
                    filename = data.get('filename', 'file')
                    file_data_b64 = data.get('file_data', '')
                    thumbnail_b64 = data.get('thumbnail', '')
                    
                    if not file_data_b64:
                        self._send_json({'success': False, 'error': '文件数据为空'})
                        return
                    
                    if not bot._current_user:
                        self._send_json({'success': False, 'error': '没有选择用户'})
                        return
                    
                    try:
                        file_bytes = base64.b64decode(file_data_b64)
                    except Exception as e:
                        self._send_json({'success': False, 'error': '文件数据解码失败'})
                        return
                    
                    print(f"[WEB] 收到媒体发送请求: type={media_type}, filename={filename}, size={len(file_bytes)} bytes, user={bot._current_user}")
                    
                    success = False
                    media_type_int = 0
                    media_data_url = ""
                    
                    if media_type == 'image':
                        if thumbnail_b64:
                            media_data_url = 'data:image/jpeg;base64,' + thumbnail_b64
                        success = bot.send_image(bot._current_user, file_bytes, filename,
                                                 media_data=media_data_url)
                        media_type_int = 2
                    elif media_type == 'video':
                        if thumbnail_b64:
                            media_data_url = 'data:image/jpeg;base64,' + thumbnail_b64
                        success = bot.send_video(bot._current_user, file_bytes, filename,
                                                 media_data=media_data_url)
                        media_type_int = 5
                    elif media_type == 'file':
                        success = bot.send_file(bot._current_user, file_bytes, filename)
                        media_type_int = 4
                    else:
                        self._send_json({'success': False, 'error': f'不支持的媒体类型: {media_type}'})
                        return
                    
                    if success:
                        type_name = bot.MEDIA_TYPE_NAMES.get(media_type_int, "文件")
                        msg_data = {
                            'text': f'[{type_name}] {filename}',
                            'time': datetime.now().strftime('%H:%M:%S'),
                            'type': 'out',
                            'media_type': media_type_int,
                            'media_filename': filename,
                            'media_data': media_data_url
                        }
                        if bot._messages:
                            for m in reversed(bot._messages):
                                if m.get('type') == 'out' and m.get('media_type') == media_type_int and not m.get('media_cache_id'):
                                    msg_data['id'] = m.get('id')
                                    if file_bytes and media_type_int in (2, 5):
                                        mime = bot._detect_mime(file_bytes)
                                        if mime == 'application/octet-stream':
                                            mime = 'video/mp4' if media_type_int == 5 else 'image/jpeg'
                                        cache_key = hashlib.md5(file_bytes).hexdigest()
                                        bot._save_media_cache(cache_key, file_bytes, mime, filename)
                                        msg_data['media_cache_id'] = cache_key
                                        m['media_cache_id'] = cache_key
                                        if m.get('media_cdn'):
                                            try:
                                                cdn_info = json.loads(m['media_cdn']) if isinstance(m['media_cdn'], str) else m['media_cdn']
                                                cdn_cache_key = bot._media_cache_key(cdn_info)
                                                if cdn_cache_key != cache_key:
                                                    bot._save_media_cache(cdn_cache_key, file_bytes, mime, filename)
                                            except Exception:
                                                pass
                                    break
                        self._send_json({'success': True, 'message': msg_data})
                    else:
                        self._send_json({'success': False, 'error': '媒体发送失败'})
                        
                except Exception as e:
                    print(f"[WEB] 媒体发送异常: {e}")
                    self._send_json({'success': False, 'error': str(e)})
            
            def _handle_download_media(self, data):
                try:
                    cdn_info_str = data.get('cdn_info', '')
                    if not cdn_info_str:
                        self._send_json({'success': False, 'error': '缺少 CDN 信息'})
                        return
                    
                    if isinstance(cdn_info_str, dict):
                        cdn_info = cdn_info_str
                    else:
                        try:
                            cdn_info = json.loads(cdn_info_str)
                        except (json.JSONDecodeError, TypeError) as je:
                            print(f"[WEB] CDN 信息 JSON 解析失败: {je}, raw={str(cdn_info_str)[:200]}")
                            self._send_json({'success': False, 'error': 'CDN 信息格式错误'})
                            return
                    
                    cache_key = bot._media_cache_key(cdn_info)
                    
                    media_data = bot.download_media(cdn_info)
                    
                    if media_data:
                        mime = bot._detect_mime(media_data)
                        self._send_json({
                            'success': True,
                            'cache_key': cache_key,
                            'mime': mime
                        })
                    else:
                        self._send_json({'success': False, 'error': '下载失败'})
                        
                except Exception as e:
                    print(f"[WEB] 媒体下载异常: {e}")
                    self._send_json({'success': False, 'error': str(e)})

            def _handle_switch_user(self, data):
                try:
                    user_id = data.get('user_id')
                    
                    if user_id and user_id in bot._context_tokens:
                        bot.set_current_user(user_id)
                        self._send_json({'success': True, 'current_user': user_id})
                    else:
                        self._send_json({'success': False, 'error': '无效的用户'})
                        
                except Exception as e:
                    self._send_json({'success': False, 'error': str(e)})
            
            def _serve_history(self):
                try:
                    params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                    
                    user_id = params.get('user', [None])[0]
                    limit_str = params.get('limit', ['200'])[0]
                    
                    try:
                        limit = min(int(limit_str), 500)
                    except (ValueError, TypeError):
                        limit = 200
                    
                    if user_id:
                        history_msgs = bot.get_user_messages(user_id, limit)
                    else:
                        all_msgs = bot._messages if bot._messages else []
                        history_msgs = all_msgs[-limit:]
                    
                    enriched = []
                    for msg in history_msgs:
                        msg_copy = dict(msg)
                        bot._enrich_msg_with_cache_id(msg_copy)
                        enriched.append(msg_copy)
                    
                    self._send_json({
                        'messages': enriched,
                        'total': len(bot._messages),
                        'found': len(history_msgs),
                        'user_id': user_id or '',
                        'limit': limit
                    })
                except Exception as e:
                    self._send_json({
                        'messages': [],
                        'total': 0,
                        'found': 0,
                        'user_id': '',
                        'limit': 200,
                        'error': str(e)
                    })
            
            def _send_json(self, data, status=200):
                try:
                    self.send_response(status)
                    self.send_header('Content-type', 'application/json; charset=utf-8')
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.end_headers()
                    self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))
                except BrokenPipeError:
                    pass
                except Exception:
                    pass
        
        return WebHandler
    
    def _print_ascii_qrcode(self, qrcode_url: str):
        qr = qrcode.QRCode(border=1)
        qr.add_data(qrcode_url)
        qr.make(fit=True)
        buffer = io.StringIO()
        qr.print_ascii(out=buffer, invert=True)
        output = buffer.getvalue()
        
        if sys.platform == "win32":
            try:
                sys.stdout.reconfigure(encoding='utf-8')
                print(output)
            except Exception:
                print(output.encode('utf-8', errors='replace').decode('utf-8'))
        elif is_termux():
            try:
                sys.stdout.reconfigure(encoding='utf-8', errors='replace')
                print(output)
            except Exception:
                safe_output = output.encode('ascii', errors='replace').decode('ascii')
                print(safe_output)
        else:
            print(output)
    
    def login_with_qrcode(self) -> bool:
        print("正在获取连接二维码...")
        try:
            url = f"{self.ILINK_BASE_URL}/ilink/bot/get_bot_qrcode?bot_type=3"
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                data = json.loads(resp.read().decode('utf-8'))
        except Exception as e:
            print(f"获取二维码失败: {e}")
            return False
        
        self._qrcode_key = data.get("qrcode")
        qrcode_url = data.get("qrcode_img_content")
        
        if not self._qrcode_key:
            print("获取二维码失败")
            return False
        
        self._qrcode_matrix = self._get_qrcode_matrix(qrcode_url)
        self._print_ascii_qrcode(qrcode_url)
        print("请使用微信扫码并确认连接...")
        print("Zyn")
        
        while not self._login_done:
            if sys.stdin.isatty():
                if sys.platform == "win32":
                    try:
                        import msvcrt
                        if msvcrt.kbhit():
                            cmd = sys.stdin.readline().strip()
                            if cmd.lower() in ["/http", "/web"]:
                                self._open_browser()
                                continue
                    except (ImportError, AttributeError):
                        pass
                elif is_termux():
                    try:
                        try:
                            import select as sel_module
                            try:
                                rlist, _, _ = sel_module.select([sys.stdin], [], [], 0.1)
                                if rlist:
                                    cmd = sys.stdin.readline().strip()
                                    if cmd.lower() in ["/http", "/web"]:
                                        self._open_browser()
                                        continue
                            except (OSError, ValueError, ImportError):
                                pass
                        except Exception:
                            pass
                    except Exception:
                        pass
                else:
                    try:
                        rlist, _, _ = select.select([sys.stdin], [], [], 0.1)
                        if rlist:
                            cmd = sys.stdin.readline().strip()
                            if cmd.lower() in ["/http", "/web"]:
                                self._open_browser()
                                continue
                    except (OSError, ValueError):
                        pass
            
            try:
                status_url = f"{self.ILINK_BASE_URL}/ilink/bot/get_qrcode_status?qrcode={self._qrcode_key}"
                status_req = urllib.request.Request(status_url, headers={"iLink-App-ClientVersion": "1"})
                with urllib.request.urlopen(status_req, timeout=5) as status_resp:
                    status = json.loads(status_resp.read().decode('utf-8'))
            except Exception as e:
                time.sleep(1)
                continue
            
            if status.get("status") == "scaned":
                print("已扫码，请在手机上确认...")
            elif status.get("status") == "confirmed":
                self.token = status.get("bot_token")
                self.bot_id = status.get("ilink_bot_id")
                self.user_id = status.get("ilink_user_id")
                print(f"连接成功!")
                print(f"   bot_id: {self.bot_id}")
                print(f"   user_id: {self.user_id}")
                
                print("正在拉取历史消息，恢复会话...")
                self._fetch_and_restore_conversations()
                
                self._save_config()
                self._login_done = True
                print(f"[WEB] 连接成功！网页端应该会自动跳转到聊天界面")
                print(f"[WEB] 如果没有跳转，请刷新浏览器页面: http://localhost:{self._web_port}")
                return True
            elif status.get("status") == "expired":
                print("二维码已过期")
                return False
            time.sleep(2)
        
        return False
    
    def _fetch_and_restore_conversations(self):
        for _ in range(5):
            body = {"get_updates_buf": self._cursor}
            result = self._post("getupdates", body, timeout=5)
            if result.get("get_updates_buf"):
                self._cursor = result["get_updates_buf"]
            messages = result.get("msgs", [])
            for msg in messages:
                from_user = msg.get("from_user_id")
                ctx_token = msg.get("context_token")
                if from_user and ctx_token:
                    if from_user not in self._context_tokens:
                        print(f"恢复会话: {from_user}")
                    self._context_tokens[from_user] = ctx_token
                    if self._current_user is None:
                        self._current_user = from_user
                    
                    text = ""
                    for item in msg.get("item_list", []):
                        if item.get("type") == 1:
                            text = item.get("text_item", {}).get("text", "")
                    if text:
                        new_msg = {
                            'from': from_user,
                            'to': 'me',
                            'text': text,
                            'time': datetime.now().strftime('%H:%M:%S'),
                            'type': 'in'
                        }
                        self._add_message_to_history(new_msg)
            if not messages:
                break
        if self._context_tokens:
            print(f"已恢复 {len(self._context_tokens)} 个会话，{len(self._messages)} 条本地消息")
            print(f"当前会话用户: {self._current_user}")
            for user_id in self._context_tokens.keys():
                self._on_new_user(user_id)
        else:
            print("没有找到历史会话")
    
    def _build_headers(self) -> dict:
        random_uin = random.randint(0, 0xFFFFFFFF)
        wechat_uin = base64.b64encode(str(random_uin).encode()).decode()
        return {
            "Content-Type": "application/json",
            "AuthorizationType": "ilink_bot_token",
            "Authorization": f"Bearer {self.token}",
            "X-WECHAT-UIN": wechat_uin,
        }
    
    def _post(self, endpoint: str, body: dict, timeout: int = 30) -> dict:
        if is_termux():
            timeout = max(timeout, 30)
            if "getupdates" in endpoint:
                timeout = 30
        
        body["base_info"] = {"channel_version": "1.0.3"}
        headers = self._build_headers()
        url = f"{self.ILINK_BASE_URL}/ilink/bot/{endpoint}"
        
        data = json.dumps(body).encode('utf-8')
        req = urllib.request.Request(url, data=data, headers=headers, method='POST')
        
        max_retries = 2 if is_termux() else 0
        
        for attempt in range(max_retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=timeout) as response:
                    result = response.read().decode('utf-8')
                    if result.strip() == "{}":
                        return {"ret": 0}
                    return json.loads(result)
            except (urllib.error.URLError, Exception) as e:
                is_timeout = (
                    isinstance(e, urllib.error.URLError) and isinstance(e.reason, TimeoutError)
                ) or "timeout" in str(e).lower() or "timed out" in str(e).lower()
                
                if is_timeout:
                    if attempt < max_retries:
                        print(f"[TERMUX] 网络超时，重试 ({attempt + 1}/{max_retries})...")
                        time.sleep(2)
                        continue
                    return {"ret": -1, "errmsg": "timeout"}
                
                if attempt < max_retries:
                    print(f"[TERMUX] 请求失败: {e}，重试 ({attempt + 1}/{max_retries})...")
                    time.sleep(3)
                    continue
                    
                return {"ret": -1, "errmsg": str(e)}
        
        return {"ret": -1, "errmsg": "max retries exceeded"}
    
    _MEDIA_ITEM_KEYS = ["image_item", "video_item", "file_item", "voice_item"]
    
    def _extract_cdn_media(self, item: dict) -> Optional[dict]:
        for ik in self._MEDIA_ITEM_KEYS:
            mi = item.get(ik)
            if mi and isinstance(mi, dict) and mi.get("media"):
                cdn_media = dict(mi["media"])
                if not cdn_media.get("aes_key") and mi.get("aeskey"):
                    cdn_media["aes_key"] = base64.b64encode(mi["aeskey"].encode('utf-8')).decode('utf-8')
                return cdn_media
        return None
    
    def _process_message_items(self, item_list: list) -> tuple:
        text = ""
        media_info = None
        
        for item in item_list:
            if item.get("text_item"):
                text_item = item["text_item"]
                if isinstance(text_item, dict):
                    text = text_item.get("text", "")
                    
            if item.get("image_item"):
                img_item = item["image_item"]
                if isinstance(img_item, dict):
                    media_info = {
                        "type": "image",
                        "filename": img_item.get("filename", "image.jpg"),
                        "item": item
                    }
                    
            elif item.get("video_item"):
                video_item = item["video_item"]
                if isinstance(video_item, dict):
                    media_info = {
                        "type": "video",
                        "filename": video_item.get("filename", "video.mp4"),
                        "duration": video_item.get("duration", 0),
                        "item": item
                    }
                    
            elif item.get("file_item"):
                file_item = item["file_item"]
                if isinstance(file_item, dict):
                    media_info = {
                        "type": "file",
                        "filename": file_item.get("filename", "file.bin"),
                        "description": file_item.get("description", ""),
                        "item": item
                    }
                    
            elif item.get("voice_item"):
                voice_item = item["voice_item"]
                if isinstance(voice_item, dict):
                    media_info = {
                        "type": "voice",
                        "filename": voice_item.get("filename", "voice.silk"),
                        "duration": voice_item.get("duration", 0),
                        "item": item
                    }
        
        return text, media_info
    
    def start_polling(self):
        def poll():
            while self._running:
                try:
                    body = {"get_updates_buf": self._cursor}
                    result = self._post("getupdates", body, timeout=25)
                    
                    if result.get("get_updates_buf"):
                        self._cursor = result["get_updates_buf"]
                        self._save_config()
                    
                    messages = result.get("msgs", [])
                    for msg in messages:
                        from_user = msg.get("from_user_id")
                        ctx_token = msg.get("context_token")
                        
                        text, media_info = self._process_message_items(msg.get("item_list", []))
                        
                        msg_text = text
                        msg_type = 'in'
                        msg_metadata = {}
                        
                        if media_info:
                            media_type_int = self.MEDIA_TYPE_MAP.get(media_info["type"], 0)
                            media_prefix = self.MEDIA_TYPE_PREFIXES.get(media_info["type"], f"[{media_info['type']}]")
                            
                            if text:
                                msg_text = f"{media_prefix} {text}"
                            else:
                                msg_text = f"{media_prefix} {media_info.get('filename', '')}"
                            
                            msg_metadata = {
                                'media_type': media_type_int,
                                'media_filename': media_info.get('filename', ''),
                                'media_duration': media_info.get('duration', 0),
                                'has_media': True
                            }
                            
                            media_item = media_info.get("item", {})
                            cdn_media = self._extract_cdn_media(media_item)
                            if cdn_media:
                                msg_metadata['media_cdn'] = json.dumps(cdn_media)
                                _prefetch_fn = media_info.get('filename', '')
                                threading.Thread(target=self._prefetch_media, args=(cdn_media, _prefetch_fn), daemon=True).start()
                            
                            print(f"\n[收到{media_info['type']}] {from_user}: {media_info.get('filename', '')}")
                        elif text:
                            print(f"\n[收到消息] {from_user}: {text}")
                        
                        if msg_text:
                            new_msg = {
                                'from': from_user,
                                'to': 'me',
                                'text': msg_text,
                                'time': datetime.now().strftime('%H:%M:%S'),
                                'type': msg_type,
                                **msg_metadata
                            }
                            
                            self._add_message_to_history(new_msg)
                            
                            if self._message_callback:
                                self._message_callback(new_msg)
                            
                            if text:  # 只有文本消息才触发 AI 回复
                                threading.Thread(target=self._auto_ai_reply, args=(from_user, text), daemon=True).start()
                        
                        if from_user and ctx_token:
                            is_new = from_user not in self._context_tokens
                            self._context_tokens[from_user] = ctx_token
                            if not self._current_user:
                                self._current_user = from_user
                            self._save_config()
                            if is_new:
                                self._on_new_user(from_user)
                except Exception as e:
                    time.sleep(0.5)
        thread = threading.Thread(target=poll, daemon=True)
        thread.start()
    
    def send_text(self, to_user_id: str, text: str) -> bool:
        context_token = self._context_tokens.get(to_user_id)
        if not context_token:
            print(f"[发送失败] 没有 {to_user_id} 的会话，让对方先发一条消息")
            return False
        
        client_id = f"msg-{uuid.uuid4().hex[:16]}"
        body = {
            "msg": {
                "from_user_id": "",
                "to_user_id": to_user_id,
                "client_id": client_id,
                "message_type": 2,
                "message_state": 2,
                "context_token": context_token,
                "item_list": [{"type": 1, "text_item": {"text": text}}]
            }
        }
        result = self._post("sendmessage", body)
        
        errcode = result.get("errcode")
        ret = result.get("ret")
        
        if ret == 0 or errcode == 0:
            print(f"[发送成功] 给 {to_user_id}: {text[:50]}...")
            out_msg = {
                'from': 'me',
                'to': to_user_id,
                'text': text,
                'time': datetime.now().strftime('%H:%M:%S'),
                'type': 'out'
            }
            self._add_message_to_history(out_msg)
            return True
        
        if errcode in self.EXPIRED_CODES or ret in self.EXPIRED_CODES:
            print(f"[发送失败] 会话已过期，需要对方重新发消息")
            self._context_tokens.pop(to_user_id, None)
            self._save_config()
            return False
        
        if ret == -1:
            print(f"[发送失败] {result.get('errmsg', '未知错误')}")
            return False
        
        print(f"[发送成功] 给 {to_user_id}: {text[:50]}...")
        out_msg = {
            'from': 'me',
            'to': to_user_id,
            'text': text,
            'time': datetime.now().strftime('%H:%M:%S'),
            'type': 'out'
        }
        self._add_message_to_history(out_msg)
        return True
    
    CDN_BASE = "https://novac2c.cdn.weixin.qq.com/c2c"

    def _random_hex(self, num_bytes: int) -> str:
        raw = os.urandom(num_bytes)
        return raw.hex()

    def _md5_hex(self, data: bytes) -> str:
        return hashlib.md5(data).hexdigest()

    _AES_SBOX = [
        0x63,0x7c,0x77,0x7b,0xf2,0x6b,0x6f,0xc5,0x30,0x01,0x67,0x2b,0xfe,0xd7,0xab,0x76,
        0xca,0x82,0xc9,0x7d,0xfa,0x59,0x47,0xf0,0xad,0xd4,0xa2,0xaf,0x9c,0xa4,0x72,0xc0,
        0xb7,0xfd,0x93,0x26,0x36,0x3f,0xf7,0xcc,0x34,0xa5,0xe5,0xf1,0x71,0xd8,0x31,0x15,
        0x04,0xc7,0x23,0xc3,0x18,0x96,0x05,0x9a,0x07,0x12,0x80,0xe2,0xeb,0x27,0xb2,0x75,
        0x09,0x83,0x2c,0x1a,0x1b,0x6e,0x5a,0xa0,0x52,0x3b,0xd6,0xb3,0x29,0xe3,0x2f,0x84,
        0x53,0xd1,0x00,0xed,0x20,0xfc,0xb1,0x5b,0x6a,0xcb,0xbe,0x39,0x4a,0x4c,0x58,0xcf,
        0xd0,0xef,0xaa,0xfb,0x43,0x4d,0x33,0x85,0x45,0xf9,0x02,0x7f,0x50,0x3c,0x9f,0xa8,
        0x51,0xa3,0x40,0x8f,0x92,0x9d,0x38,0xf5,0xbc,0xb6,0xda,0x21,0x10,0xff,0xf3,0xd2,
        0xcd,0x0c,0x13,0xec,0x5f,0x97,0x44,0x17,0xc4,0xa7,0x7e,0x3d,0x64,0x5d,0x19,0x73,
        0x60,0x81,0x4f,0xdc,0x22,0x2a,0x90,0x88,0x46,0xee,0xb8,0x14,0xde,0x5e,0x0b,0xdb,
        0xe0,0x32,0x3a,0x0a,0x49,0x06,0x24,0x5c,0xc2,0xd3,0xac,0x62,0x91,0x95,0xe4,0x79,
        0xe7,0xc8,0x37,0x6d,0x8d,0xd5,0x4e,0xa9,0x6c,0x56,0xf4,0xea,0x65,0x7a,0xae,0x08,
        0xba,0x78,0x25,0x2e,0x1c,0xa6,0xb4,0xc6,0xe8,0xdd,0x74,0x1f,0x4b,0xbd,0x8b,0x8a,
        0x70,0x3e,0xb5,0x66,0x48,0x03,0xf6,0x0e,0x61,0x35,0x57,0xb9,0x86,0xc1,0x1d,0x9e,
        0xe1,0xf8,0x98,0x11,0x69,0xd9,0x8e,0x94,0x9b,0x1e,0x87,0xe9,0xce,0x55,0x28,0xdf,
        0x8c,0xa1,0x89,0x0d,0xbf,0xe6,0x42,0x68,0x41,0x99,0x2d,0x0f,0xb0,0x54,0xbb,0x16,
    ]
    _AES_INV_SBOX = [
        0x52,0x09,0x6a,0xd5,0x30,0x36,0xa5,0x38,0xbf,0x40,0xa3,0x9e,0x81,0xf3,0xd7,0xfb,
        0x7c,0xe3,0x39,0x82,0x9b,0x2f,0xff,0x87,0x34,0x8e,0x43,0x44,0xc4,0xde,0xe9,0xcb,
        0x54,0x7b,0x94,0x32,0xa6,0xc2,0x23,0x3d,0xee,0x4c,0x95,0x0b,0x42,0xfa,0xc3,0x4e,
        0x08,0x2e,0xa1,0x66,0x28,0xd9,0x24,0xb2,0x76,0x5b,0xa2,0x49,0x6d,0x8b,0xd1,0x25,
        0x72,0xf8,0xf6,0x64,0x86,0x68,0x98,0x16,0xd4,0xa4,0x5c,0xcc,0x5d,0x65,0xb6,0x92,
        0x6c,0x70,0x48,0x50,0xfd,0xed,0xb9,0xda,0x5e,0x15,0x46,0x57,0xa7,0x8d,0x9d,0x84,
        0x90,0xd8,0xab,0x00,0x8c,0xbc,0xd3,0x0a,0xf7,0xe4,0x58,0x05,0xb8,0xb3,0x45,0x06,
        0xd0,0x2c,0x1e,0x8f,0xca,0x3f,0x0f,0x02,0xc1,0xaf,0xbd,0x03,0x01,0x13,0x8a,0x6b,
        0x3a,0x91,0x11,0x41,0x4f,0x67,0xdc,0xea,0x97,0xf2,0xcf,0xce,0xf0,0xb4,0xe6,0x73,
        0x96,0xac,0x74,0x22,0xe7,0xad,0x35,0x85,0xe2,0xf9,0x37,0xe8,0x1c,0x75,0xdf,0x6e,
        0x47,0xf1,0x1a,0x71,0x1d,0x29,0xc5,0x89,0x6f,0xb7,0x62,0x0e,0xaa,0x18,0xbe,0x1b,
        0xfc,0x56,0x3e,0x4b,0xc6,0xd2,0x79,0x20,0x9a,0xdb,0xc0,0xfe,0x78,0xcd,0x5a,0xf4,
        0x1f,0xdd,0xa8,0x33,0x88,0x07,0xc7,0x31,0xb1,0x12,0x10,0x59,0x27,0x80,0xec,0x5f,
        0x60,0x51,0x7f,0xa9,0x19,0xb5,0x4a,0x0d,0x2d,0xe5,0x7a,0x9f,0x93,0xc9,0x9c,0xef,
        0xa0,0xe0,0x3b,0x4d,0xae,0x2a,0xf5,0xb0,0xc8,0xeb,0xbb,0x3c,0x83,0x53,0x99,0x61,
        0x17,0x2b,0x04,0x7e,0xba,0x77,0xd6,0x26,0xe1,0x69,0x14,0x63,0x55,0x21,0x0c,0x7d,
    ]
    _AES_RCON = [0x01,0x02,0x04,0x08,0x10,0x20,0x40,0x80,0x1b,0x36]

    @staticmethod
    def _xtime(a):
        return ((a << 1) ^ 0x1b) & 0xff if a & 0x80 else (a << 1) & 0xff

    @staticmethod
    def _gmul(a, b):
        p = 0
        for _ in range(8):
            if b & 1:
                p ^= a
            hi = a & 0x80
            a = (a << 1) & 0xff
            if hi:
                a ^= 0x1b
            b >>= 1
        return p

    @classmethod
    def _aes_key_expansion(cls, key: bytes) -> list:
        Nk = len(key) // 4
        Nr = Nk + 6
        W = []
        for i in range(Nk):
            W.append(list(key[4*i:4*i+4]))
        for i in range(Nk, 4*(Nr+1)):
            t = list(W[i-1])
            if i % Nk == 0:
                t = t[1:] + t[:1]
                t = [cls._AES_SBOX[b] for b in t]
                t[0] ^= cls._AES_RCON[i//Nk - 1]
            elif Nk > 6 and i % Nk == 4:
                t = [cls._AES_SBOX[b] for b in t]
            W.append([W[i-Nk][j] ^ t[j] for j in range(4)])
        return W

    @classmethod
    def _aes_encrypt_block(cls, block: bytes, round_keys: list) -> bytes:
        Nr = len(round_keys) // 4 - 1
        s = [[0]*4 for _ in range(4)]
        for i in range(16):
            s[i%4][i//4] = block[i]
        for c in range(4):
            for r in range(4):
                s[r][c] ^= round_keys[c][r]
        for rnd in range(1, Nr):
            s = [[cls._AES_SBOX[s[r][c]] for c in range(4)] for r in range(4)]
            for r in range(1, 4):
                s[r] = s[r][r:] + s[r][:r]
            for c in range(4):
                a = [s[r][c] for r in range(4)]
                s[0][c] = cls._xtime(a[0]) ^ cls._xtime(a[1]) ^ a[1] ^ a[2] ^ a[3]
                s[1][c] = a[0] ^ cls._xtime(a[1]) ^ cls._xtime(a[2]) ^ a[2] ^ a[3]
                s[2][c] = a[0] ^ a[1] ^ cls._xtime(a[2]) ^ cls._xtime(a[3]) ^ a[3]
                s[3][c] = cls._xtime(a[0]) ^ a[0] ^ a[1] ^ a[2] ^ cls._xtime(a[3])
            for c in range(4):
                for r in range(4):
                    s[r][c] ^= round_keys[rnd*4+c][r]
        s = [[cls._AES_SBOX[s[r][c]] for c in range(4)] for r in range(4)]
        for r in range(1, 4):
            s[r] = s[r][r:] + s[r][:r]
        for c in range(4):
            for r in range(4):
                s[r][c] ^= round_keys[Nr*4+c][r]
        out = []
        for i in range(16):
            out.append(s[i%4][i//4])
        return bytes(out)

    @classmethod
    def _aes_decrypt_block(cls, block: bytes, round_keys: list) -> bytes:
        Nr = len(round_keys) // 4 - 1
        s = [[0]*4 for _ in range(4)]
        for i in range(16):
            s[i%4][i//4] = block[i]
        for c in range(4):
            for r in range(4):
                s[r][c] ^= round_keys[Nr*4+c][r]
        for rnd in range(Nr-1, 0, -1):
            for r in range(1, 4):
                s[r] = s[r][-r:] + s[r][:-r]
            s = [[cls._AES_INV_SBOX[s[r][c]] for c in range(4)] for r in range(4)]
            for c in range(4):
                for r in range(4):
                    s[r][c] ^= round_keys[rnd*4+c][r]
            for c in range(4):
                a = [s[r][c] for r in range(4)]
                s[0][c] = cls._gmul(a[0],14) ^ cls._gmul(a[1],11) ^ cls._gmul(a[2],13) ^ cls._gmul(a[3],9)
                s[1][c] = cls._gmul(a[0],9) ^ cls._gmul(a[1],14) ^ cls._gmul(a[2],11) ^ cls._gmul(a[3],13)
                s[2][c] = cls._gmul(a[0],13) ^ cls._gmul(a[1],9) ^ cls._gmul(a[2],14) ^ cls._gmul(a[3],11)
                s[3][c] = cls._gmul(a[0],11) ^ cls._gmul(a[1],13) ^ cls._gmul(a[2],9) ^ cls._gmul(a[3],14)
        for r in range(1, 4):
            s[r] = s[r][-r:] + s[r][:-r]
        s = [[cls._AES_INV_SBOX[s[r][c]] for c in range(4)] for r in range(4)]
        for c in range(4):
            for r in range(4):
                s[r][c] ^= round_keys[c][r]
        out = []
        for i in range(16):
            out.append(s[i%4][i//4])
        return bytes(out)

    @staticmethod
    def _pkcs7_pad(data: bytes, block_size: int = 16) -> bytes:
        pad_len = block_size - (len(data) % block_size)
        return data + bytes([pad_len] * pad_len)

    @staticmethod
    def _pkcs7_unpad(data: bytes) -> bytes:
        if not data:
            raise ValueError("Empty data")
        pad_len = data[-1]
        if pad_len < 1 or pad_len > 16:
            raise ValueError(f"Invalid padding: {pad_len}")
        if data[-pad_len:] != bytes([pad_len] * pad_len):
            raise ValueError("Invalid PKCS7 padding")
        return data[:-pad_len]

    def _aes_ecb_encrypt(self, plain: bytes, key: bytes) -> bytes:
        if _HAS_PYCRYPTODOME:
            cipher = _CryptoAES.new(key, _CryptoAES.MODE_ECB)
            padded = self._pkcs7_pad(plain)
            return cipher.encrypt(padded)
        round_keys = self._aes_key_expansion(key)
        padded = self._pkcs7_pad(plain)
        out = bytearray()
        for i in range(0, len(padded), 16):
            out.extend(self._aes_encrypt_block(padded[i:i+16], round_keys))
        return bytes(out)

    def _aes_ecb_decrypt(self, encrypted: bytes, key: bytes) -> bytes:
        if _HAS_PYCRYPTODOME:
            cipher = _CryptoAES.new(key, _CryptoAES.MODE_ECB)
            decrypted = cipher.decrypt(encrypted)
            return self._pkcs7_unpad(decrypted)
        round_keys = self._aes_key_expansion(key)
        if len(encrypted) % 16 != 0:
            raise ValueError("Encrypted data length must be multiple of 16")
        out = bytearray()
        for i in range(0, len(encrypted), 16):
            out.extend(self._aes_decrypt_block(encrypted[i:i+16], round_keys))
        return self._pkcs7_unpad(bytes(out))

    def _upload_media(self, file_bytes: bytes, filename: str, media_type: int, to_user_id: str) -> Optional[dict]:
        try:
            print(f"[媒体上传] 正在上传 {filename}, 类型={media_type}, 大小={len(file_bytes)} bytes")

            aes_key_hex = self._random_hex(16)
            aes_key_bytes = bytes.fromhex(aes_key_hex)

            encrypted = self._aes_ecb_encrypt(file_bytes, aes_key_bytes)

            filekey = self._random_hex(16)
            raw_md5 = self._md5_hex(file_bytes)

            body = {
                "filekey": filekey,
                "media_type": media_type,
                "to_user_id": to_user_id,
                "rawsize": len(file_bytes),
                "rawfilemd5": raw_md5,
                "filesize": len(encrypted),
                "no_need_thumb": True,
                "aeskey": aes_key_hex
            }

            result = self._post("getuploadurl", body)

            ret = result.get("ret")
            errcode = result.get("errcode")

            if ret is not None and ret != 0:
                print(f"[媒体上传失败] getuploadurl 失败: ret={ret}, errcode={errcode}, errmsg={result.get('errmsg', '')}")
                return None
            if errcode is not None and errcode != 0:
                print(f"[媒体上传失败] getuploadurl 失败: ret={ret}, errcode={errcode}, errmsg={result.get('errmsg', '')}")
                return None

            upload_param = result.get("upload_param")
            if not upload_param:
                print(f"[媒体上传失败] 未获取到 upload_param, 返回数据: {json.dumps(result, ensure_ascii=False)[:300]}")
                return None

            cdn_url = self.CDN_BASE + "/upload?encrypted_query_param=" + urllib.parse.quote(upload_param, safe='') + "&filekey=" + urllib.parse.quote(filekey, safe='')

            print(f"[媒体上传] 获取到上传参数，正在上传到 CDN...")

            req = urllib.request.Request(
                cdn_url,
                data=encrypted,
                method='POST',
                headers={'Content-Type': 'application/octet-stream'}
            )

            with urllib.request.urlopen(req, timeout=120) as resp:
                encrypted_param = resp.headers.get('x-encrypted-param', '')
                if not encrypted_param:
                    resp_body = resp.read()
                    print(f"[媒体上传失败] CDN 响应缺少 x-encrypted-param 头, status={resp.status}, body={resp_body[:200]}")
                    return None

                aes_key_b64 = base64.b64encode(aes_key_hex.encode('utf-8')).decode('utf-8')

                cdn_media = {
                    "encrypt_query_param": encrypted_param,
                    "aes_key": aes_key_b64,
                    "encrypt_type": 1
                }

                uploaded = {
                    "filekey": filekey,
                    "media": cdn_media,
                    "aes_key_hex": aes_key_hex,
                    "raw_size": len(file_bytes),
                    "encrypted_size": len(encrypted),
                    "md5": raw_md5,
                    "filename": filename
                }

                print(f"[媒体上传成功] filekey={filekey}, enc_size={len(encrypted)}")
                return uploaded

        except Exception as e:
            print(f"[媒体上传异常] {e}")
            import traceback
            traceback.print_exc()
            return None

    def _send_media_message(self, to_user_id: str, media_item: dict,
                            description: str = "", media_data: str = "",
                            media_filename: str = "", media_duration: int = 0) -> bool:
        context_token = self._context_tokens.get(to_user_id)
        if not context_token:
            print(f"[发送失败] 没有 {to_user_id} 的会话，让对方先发一条消息")
            return False

        if description:
            self.send_text(to_user_id, description)

        client_id = f"ilink-sdk:{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}"

        body = {
            "msg": {
                "from_user_id": "",
                "to_user_id": to_user_id,
                "client_id": client_id,
                "message_type": 2,
                "message_state": 2,
                "context_token": context_token,
                "item_list": [media_item]
            }
        }

        result = self._post("sendmessage", body)

        errcode = result.get("errcode")
        ret = result.get("ret")

        success = (ret is None or ret == 0) and (errcode is None or errcode == 0)

        if errcode is not None and errcode in self.EXPIRED_CODES:
            success = False
        if ret is not None and ret in self.EXPIRED_CODES:
            success = False

        if success:
            type_name = self.MEDIA_TYPE_NAMES.get(media_item.get("type", 0), "媒体")
            print(f"[发送成功] {type_name} 给 {to_user_id}")
            out_msg = {
                'from': 'me',
                'to': to_user_id,
                'text': f"[{type_name}]" + (f" {description}" if description else ""),
                'time': datetime.now().strftime('%H:%M:%S'),
                'type': 'out',
                'media_type': media_item.get("type"),
                'media_data': media_data,
                'media_filename': media_filename or description,
                'media_duration': media_duration
            }
            cdn_media = self._extract_cdn_media(media_item)
            if cdn_media:
                out_msg['media_cdn'] = json.dumps(cdn_media)
            self._add_message_to_history(out_msg)
            return True

        if errcode in self.EXPIRED_CODES or ret in self.EXPIRED_CODES:
            print(f"[发送失败] 会话已过期，需要对方重新发消息")
            self._context_tokens.pop(to_user_id, None)
            self._save_config()
            return False

        print(f"[发送失败] ret={ret}, errcode={errcode}, errmsg={result.get('errmsg', '')}")
        return False

    def send_image(self, to_user_id: str, image_bytes: bytes,
                   filename: str = "image.jpg", description: str = "",
                   media_data: str = "") -> bool:
        print(f"[发送图片] 准备发送图片给 {to_user_id}: {filename} ({len(image_bytes)} bytes)")

        uploaded = self._upload_media(image_bytes, filename, media_type=1, to_user_id=to_user_id)
        if not uploaded:
            print("[发送图片失败] 上传失败")
            return False

        image_item = {
            "media": uploaded["media"],
            "aeskey": uploaded["aes_key_hex"],
            "mid_size": uploaded["encrypted_size"]
        }

        media_item = {
            "type": 2,
            "image_item": image_item
        }

        return self._send_media_message(to_user_id, media_item, description,
                                        media_data=media_data, media_filename=filename)

    def send_file(self, to_user_id: str, file_bytes: bytes,
                  filename: str = "file.bin", description: str = "",
                  media_data: str = "") -> bool:
        print(f"[发送文件] 准备发送文件给 {to_user_id}: {filename} ({len(file_bytes)} bytes)")

        uploaded = self._upload_media(file_bytes, filename, media_type=3, to_user_id=to_user_id)
        if not uploaded:
            print("[发送文件失败] 上传失败")
            return False

        file_item = {
            "media": uploaded["media"],
            "file_name": filename,
            "md5": uploaded["md5"],
            "len": str(uploaded["raw_size"])
        }

        media_item = {
            "type": 4,
            "file_item": file_item
        }

        return self._send_media_message(to_user_id, media_item, description,
                                        media_filename=filename)

    def send_voice(self, to_user_id: str, voice_bytes: bytes,
                   filename: str = "voice.silk", duration_ms: int = 1000,
                   sample_rate: int = 16000) -> bool:
        print(f"[发送语音] 准备发送语音给 {to_user_id}: {filename} ({len(voice_bytes)} bytes, {duration_ms}ms)")

        uploaded = self._upload_media(voice_bytes, filename, media_type=4, to_user_id=to_user_id)
        if not uploaded:
            print("[发送语音失败] 上传失败")
            return False

        voice_item = {
            "media": uploaded["media"],
            "encode_type": 6,
            "bits_per_sample": 16,
            "playtime": duration_ms,
            "sample_rate": sample_rate
        }

        media_item = {
            "type": 3,
            "voice_item": voice_item
        }

        return self._send_media_message(to_user_id, media_item,
                                        media_filename=filename, media_duration=duration_ms)

    def send_video(self, to_user_id: str, video_bytes: bytes,
                   filename: str = "video.mp4", duration_ms: int = 5000,
                   description: str = "", media_data: str = "") -> bool:
        print(f"[发送视频] 准备发送视频给 {to_user_id}: {filename} ({len(video_bytes)} bytes, {duration_ms}ms)")

        uploaded = self._upload_media(video_bytes, filename, media_type=2, to_user_id=to_user_id)
        if not uploaded:
            print("[发送视频失败] 上传失败")
            return False

        video_item = {
            "media": uploaded["media"],
            "video_size": uploaded["encrypted_size"],
            "play_length": duration_ms,
            "video_md5": uploaded["md5"]
        }

        media_item = {
            "type": 5,
            "video_item": video_item
        }

        return self._send_media_message(to_user_id, media_item, description,
                                        media_data=media_data, media_filename=filename,
                                        media_duration=duration_ms)

    def _media_cache_key(self, cdn_media_info: dict) -> str:
        eqp = cdn_media_info.get("encrypt_query_param") or cdn_media_info.get("encrypted_query_param") or ""
        return hashlib.md5(eqp.encode('utf-8')).hexdigest()

    def _enrich_msg_with_cache_id(self, msg: dict) -> dict:
        if msg.get('media_cdn') and msg.get('media_type'):
            try:
                cdn_info = json.loads(msg['media_cdn']) if isinstance(msg['media_cdn'], str) else msg['media_cdn']
                cache_key = self._media_cache_key(cdn_info)
                if self._get_cached_media(cache_key):
                    msg['media_cache_id'] = cache_key
            except Exception:
                pass
        return msg

    def _media_cache_path(self, cache_key: str) -> Path:
        return self._media_cache_dir / cache_key

    def _media_meta_path(self, cache_key: str) -> Path:
        return self._media_cache_dir / (cache_key + ".meta")

    def _get_cached_media(self, cache_key: str) -> Optional[tuple]:
        data_path = self._media_cache_path(cache_key)
        meta_path = self._media_meta_path(cache_key)
        if data_path.exists() and meta_path.exists():
            try:
                media_data = data_path.read_bytes()
                meta = json.loads(meta_path.read_text('utf-8'))
                return (media_data, meta.get('mime', 'application/octet-stream'), meta.get('filename', ''))
            except Exception:
                return None
        return None

    def _save_media_cache(self, cache_key: str, media_data: bytes, mime: str, filename: str = ""):
        try:
            self._media_cache_path(cache_key).write_bytes(media_data)
            meta = {'mime': mime, 'filename': filename, 'size': len(media_data)}
            self._media_meta_path(cache_key).write_text(json.dumps(meta, ensure_ascii=False), 'utf-8')
        except Exception as e:
            print(f"[媒体缓存] 保存失败: {e}")

    def _prefetch_media(self, cdn_media_info: dict, filename: str = ""):
        try:
            cache_key = self._media_cache_key(cdn_media_info)
            if self._get_cached_media(cache_key):
                return
            print(f"[媒体预取] 开始下载: {cache_key[:12]}...")
            result = self.download_media(cdn_media_info, filename=filename)
            if result:
                print(f"[媒体预取] 完成: {cache_key[:12]}..., {len(result)} bytes")
            else:
                print(f"[媒体预取] 失败: {cache_key[:12]}...")
        except Exception as e:
            print(f"[媒体预取] 异常: {e}")

    def _detect_mime(self, data: bytes) -> str:
        if data[:8] == b'\x89PNG\r\n\x1a\n':
            return 'image/png'
        if data[:4] == b'GIF8':
            return 'image/gif'
        if data[:4] == b'RIFF' and len(data) > 12 and data[8:12] == b'WEBP':
            return 'image/webp'
        if data[:2] == b'\xff\xd8':
            return 'image/jpeg'
        if data[:4] == b'RIFF' and len(data) > 12 and data[8:12] == b'WAVE':
            return 'audio/wav'
        if len(data) > 3 and (data[:3] == b'ID3' or data[:2] in (b'\xff\xfb', b'\xff\xf3', b'\xff\xf2')):
            return 'audio/mpeg'
        if data[:4] == b'fLaC':
            return 'audio/flac'
        if data[:4] == b'OggS':
            return 'audio/ogg'
        if len(data) > 9 and data[:9] == b'#!SILK_V3':
            return 'audio/silk'
        if len(data) > 5 and data[:5] == b'#!AMR':
            return 'audio/amr'
        if len(data) > 8 and data[:4] == b'\x00\x00\x00':
            box_type = data[4:8]
            if box_type == b'ftyp':
                return 'video/mp4'
            if box_type == b'MThd':
                return 'audio/midi'
        if data[:4] == b'\x1a\x45\xdf\xa3':
            return 'video/webm'
        return 'application/octet-stream'

    _silk_lib = None
    _silk_lib_lock = threading.Lock()

    def _get_silk_lib(self):
        if self._silk_lib is not None:
            return self._silk_lib
        with self._silk_lib_lock:
            if self._silk_lib is not None:
                return self._silk_lib
            lib_path = Path(__file__).parent / 'libsilk_decoder.so'
            if not lib_path.exists():
                print("[SILK] libsilk_decoder.so 未找到")
                return None
            try:
                import ctypes
                lib = ctypes.CDLL(str(lib_path))
                lib.SKP_Silk_SDK_Get_Decoder_Size.restype = ctypes.c_int
                lib.SKP_Silk_SDK_Get_Decoder_Size.argtypes = [ctypes.POINTER(ctypes.c_int32)]
                lib.SKP_Silk_SDK_InitDecoder.restype = ctypes.c_int
                lib.SKP_Silk_SDK_InitDecoder.argtypes = [ctypes.c_void_p]
                lib.SKP_Silk_SDK_Decode.restype = ctypes.c_int
                lib.SKP_Silk_SDK_Decode.argtypes = [
                    ctypes.c_void_p,
                    ctypes.c_void_p,
                    ctypes.c_int,
                    ctypes.POINTER(ctypes.c_uint8),
                    ctypes.c_int,
                    ctypes.POINTER(ctypes.c_int16),
                    ctypes.POINTER(ctypes.c_int16),
                ]
                self._silk_lib = lib
                print("[SILK] libsilk_decoder.so 加载成功")
                return lib
            except Exception as e:
                print(f"[SILK] 加载 libsilk_decoder.so 失败: {e}")
                return None

    def _silk_to_wav(self, silk_data: bytes) -> Optional[bytes]:
        import ctypes
        if silk_data[:1] == b'\x02' and len(silk_data) > 10 and silk_data[1:10] == b'#!SILK_V3':
            silk_data = silk_data[1:]
        if silk_data[:9] != b'#!SILK_V3':
            print("[SILK转WAV] 非 SILK V3 格式")
            return self._ffmpeg_to_wav(silk_data)
        lib = self._get_silk_lib()
        if lib is None:
            print("[SILK转WAV] SILK 解码库不可用，尝试 ffmpeg")
            return self._ffmpeg_to_wav(silk_data)
        try:
            dec_size = ctypes.c_int32(0)
            lib.SKP_Silk_SDK_Get_Decoder_Size(ctypes.byref(dec_size))
            dec_state = ctypes.create_string_buffer(dec_size.value)
            ret = lib.SKP_Silk_SDK_InitDecoder(dec_state)
            if ret != 0:
                print(f"[SILK转WAV] InitDecoder 失败: {ret}")
                return self._ffmpeg_to_wav(silk_data)

            class DecControl(ctypes.Structure):
                _fields_ = [
                    ("API_sampleRate", ctypes.c_int32),
                    ("frameSize", ctypes.c_int),
                    ("framesPerPacket", ctypes.c_int),
                    ("moreInternalDecoderFrames", ctypes.c_int),
                    ("inBandFECOffset", ctypes.c_int),
                ]

            MAX_API_FS_KHZ = 48
            FRAME_LENGTH_MS = 20
            MAX_INPUT_FRAMES = 5
            MAX_BYTES_PER_FRAME = 1024
            max_frame_samples = (FRAME_LENGTH_MS * MAX_API_FS_KHZ) << 1

            pcm_all = bytearray()
            for sample_rate in [24000, 16000, 12000, 8000]:
                lib.SKP_Silk_SDK_InitDecoder(dec_state)
                dec_ctrl = DecControl()
                dec_ctrl.API_sampleRate = sample_rate
                dec_ctrl.framesPerPacket = 1

                buf = silk_data[9:]
                if buf[:1] == b'\n':
                    buf = buf[1:]
                pcm_all_sr = bytearray()
                offset = 0
                ok = True
                while offset + 2 <= len(buf):
                    n_bytes = struct.unpack('>h', buf[offset:offset + 2])[0]
                    offset += 2
                    if n_bytes < 0 or n_bytes > MAX_BYTES_PER_FRAME * MAX_INPUT_FRAMES:
                        break
                    if n_bytes == 0:
                        continue
                    if offset + n_bytes > len(buf):
                        ok = False
                        break
                    payload = (ctypes.c_uint8 * n_bytes).from_buffer_copy(buf[offset:offset + n_bytes])
                    offset += n_bytes
                    out_buf = (ctypes.c_int16 * (max_frame_samples * MAX_INPUT_FRAMES))()
                    out_len = ctypes.c_int16(0)
                    ret = lib.SKP_Silk_SDK_Decode(
                        dec_state, ctypes.byref(dec_ctrl), 0,
                        payload, n_bytes, out_buf, ctypes.byref(out_len)
                    )
                    if ret != 0:
                        ok = False
                        break
                    total = out_len.value
                    while dec_ctrl.moreInternalDecoderFrames:
                        extra_buf = (ctypes.c_int16 * max_frame_samples)()
                        extra_len = ctypes.c_int16(0)
                        ret2 = lib.SKP_Silk_SDK_Decode(
                            dec_state, ctypes.byref(dec_ctrl), 0,
                            payload, n_bytes, extra_buf, ctypes.byref(extra_len)
                        )
                        if ret2 != 0 or extra_len.value <= 0:
                            break
                        pcm_all_sr.extend(extra_buf[:extra_len.value])
                        total += extra_len.value
                    pcm_all_sr.extend(out_buf[:out_len.value])
                if ok and len(pcm_all_sr) > 0:
                    pcm_all = pcm_all_sr
                    break

            if not pcm_all:
                print("[SILK转WAV] 解码无输出，尝试 ffmpeg")
                return self._ffmpeg_to_wav(silk_data)

            pcm_data = bytes(pcm_all)
            num_channels = 1
            bits_per_sample = 16
            byte_rate = sample_rate * num_channels * bits_per_sample // 8
            block_align = num_channels * bits_per_sample // 8
            data_size = len(pcm_data)
            wav_buf = io.BytesIO()
            wav_buf.write(b'RIFF')
            wav_buf.write(struct.pack('<I', 36 + data_size))
            wav_buf.write(b'WAVE')
            wav_buf.write(b'fmt ')
            wav_buf.write(struct.pack('<I', 16))
            wav_buf.write(struct.pack('<H', 1))
            wav_buf.write(struct.pack('<H', num_channels))
            wav_buf.write(struct.pack('<I', sample_rate))
            wav_buf.write(struct.pack('<I', byte_rate))
            wav_buf.write(struct.pack('<H', block_align))
            wav_buf.write(struct.pack('<H', bits_per_sample))
            wav_buf.write(b'data')
            wav_buf.write(struct.pack('<I', data_size))
            wav_buf.write(pcm_data)
            print(f"[SILK转WAV] 转换成功: {len(silk_data)} bytes SILK -> {wav_buf.tell()} bytes WAV, 采样率={sample_rate}")
            return wav_buf.getvalue()
        except Exception as e:
            print(f"[SILK转WAV] 转换失败: {e}")
            return self._ffmpeg_to_wav(silk_data)

    def _ffmpeg_to_wav(self, audio_data: bytes) -> Optional[bytes]:
        tmp_in = None
        tmp_out = None
        try:
            tmp_in = self._media_cache_dir / ('_ffmpeg_tmp_in_' + uuid.uuid4().hex[:12])
            tmp_out = self._media_cache_dir / ('_ffmpeg_tmp_out_' + uuid.uuid4().hex[:12] + '.wav')
            tmp_in.write_bytes(audio_data)
            result = subprocess.run(
                ['ffmpeg', '-y', '-i', str(tmp_in), '-f', 'wav', '-ar', '24000', '-ac', '1', str(tmp_out)],
                capture_output=True, timeout=30
            )
            if tmp_out.exists() and tmp_out.stat().st_size > 44:
                wav_data = tmp_out.read_bytes()
                print(f"[ffmpeg转WAV] 转换成功: {len(audio_data)} bytes -> {len(wav_data)} bytes")
                return wav_data
            print(f"[ffmpeg转WAV] 转换失败: {result.stderr.decode('utf-8', errors='replace')[:200]}")
            return None
        except Exception as e:
            print(f"[ffmpeg转WAV] 异常: {e}")
            return None
        finally:
            for tmp in (tmp_in, tmp_out):
                if tmp:
                    try:
                        if tmp.exists(): tmp.unlink()
                    except Exception:
                        pass

    def download_media(self, cdn_media_info: dict, filename: str = "") -> Optional[bytes]:
        cache_key = self._media_cache_key(cdn_media_info)

        cached = self._get_cached_media(cache_key)
        if cached:
            return cached[0]

        with self._media_download_lock:
            if cache_key in self._media_downloading:
                wait_event = self._media_downloading[cache_key]
            else:
                wait_event = None

        if wait_event:
            wait_event.wait(timeout=60)
            cached = self._get_cached_media(cache_key)
            if cached:
                return cached[0]
            return None

        event = threading.Event()
        with self._media_download_lock:
            self._media_downloading[cache_key] = event

        try:
            encrypt_query_param = cdn_media_info.get("encrypt_query_param")
            aes_key_b64 = cdn_media_info.get("aes_key")
            
            if not encrypt_query_param:
                encrypt_query_param = cdn_media_info.get("encrypted_query_param")
            if not encrypt_query_param:
                return None
            
            if not aes_key_b64:
                aes_key_hex = cdn_media_info.get("aeskey") or cdn_media_info.get("aes_key_hex")
                if aes_key_hex:
                    aes_key_b64 = base64.b64encode(aes_key_hex.encode('utf-8')).decode('utf-8')
            
            if not aes_key_b64:
                return None

            download_url = self.CDN_BASE + "/download?encrypted_query_param=" + urllib.parse.quote(encrypt_query_param, safe='')

            print(f"[媒体下载] 正在从 CDN 下载...")
            req = urllib.request.Request(download_url)

            with urllib.request.urlopen(req, timeout=60) as resp:
                data = resp.read()

                decoded_key = base64.b64decode(aes_key_b64)
                if len(decoded_key) == 16:
                    aes_key_bytes = decoded_key
                else:
                    aes_key_hex = decoded_key.decode('utf-8')
                    aes_key_bytes = bytes.fromhex(aes_key_hex)

                decrypted = self._aes_ecb_decrypt(data, aes_key_bytes)
                print(f"[媒体下载成功] 解密后大小: {len(decrypted)} bytes")

                mime = self._detect_mime(decrypted)
                if mime == 'audio/silk':
                    wav_data = self._silk_to_wav(decrypted)
                    if wav_data:
                        decrypted = wav_data
                        mime = 'audio/wav'
                        filename = filename.replace('.silk', '.wav') if filename else 'voice.wav'
                elif mime == 'audio/amr':
                    wav_data = self._ffmpeg_to_wav(decrypted)
                    if wav_data:
                        decrypted = wav_data
                        mime = 'audio/wav'
                        filename = filename.replace('.amr', '.wav') if filename else 'voice.wav'

                self._save_media_cache(cache_key, decrypted, mime, filename)

                return decrypted

        except Exception as e:
            print(f"[媒体下载异常] {e}")
            return None
        finally:
            with self._media_download_lock:
                self._media_downloading.pop(cache_key, None)
            event.set()

    def download_media_from_message_item(self, message_item: dict) -> Optional[bytes]:
        cdn_media_info = self._extract_cdn_media(message_item)

        if cdn_media_info and cdn_media_info.get("encrypt_query_param"):
            return self.download_media(cdn_media_info)

        print("[下载失败] 消息项中未找到有效的媒体信息")
        return None
    
    def list_users(self) -> list:
        return list(self._context_tokens.keys())
    
    def get_current_user(self):
        return self._current_user
    
    def set_current_user(self, user_id: str):
        if user_id in self._context_tokens:
            self._current_user = user_id
            self._save_config()
            print(f"已切换到: {user_id}")
    
    def stop(self):
        self._running = False
        for timer in self._active_timers.values():
            timer.cancel()
        self._active_timers.clear()
        if self._http_server:
            self._http_server.shutdown()

def main():
    print("╔" + "═" * 58 + "╗")
    print("║" + " " * 12 + "Zynsync iLink ChatBox" + " " * 18 + "║")
    print("║" + " " * 16 + "使用微信官方接口" + " " * 22 + "║")
    print("║" + " " * 20 + "v2.0.9" + " " * 26 + "║")
    print("╚" + "═" * 58 + "╝")
    
    if is_termux():
        print("\n[TERMUX] 运行环境: Android/Termux")
        print("[TERMUX] 网络模式: 可能需要代理或 VPN 访问微信服务器")
        print("[TERMUX] 提示: 如果网络不稳定，程序会自动重试")
        print()
    
    bot = WeChatiLinkBot()
    
    bot.start_web_interface()
    
    if is_termux():
        print(f"\n[Zyn] 📱 网页地址: http://localhost:{bot._web_port}")
        print("[TERMUX] 💡 使用方法:")
        print("   方法1: 在手机浏览器访问上述地址")
        print("   方法2: 在电脑浏览器访问 http://<你的IP>:{bot._web_port}")
        print("   (需确保手机和电脑在同一网络)")
        print("[TERMUX] 输入 /web 可再次显示地址\n")
    
    if bot.load_config():
        print("[zyn]已获取到连接缓存")
    else:
        print("[zyn]首次运行，请扫码连接（可在网页或终端扫码）")
        if not bot.login_with_qrcode():
            return
    
    bot.start_polling()
    
    print("[zyn]后台监听已启动，等待消息...")
    print(f"[zyn]网页地址: http://localhost:{bot._web_port}")
    
    users = bot.list_users()
    if users:
        print(f"\n已保存 {len(users)} 个会话")
        for uid in users:
            marker = "[zyn]" if uid == bot.get_current_user() else "   "
            print(f"{marker}{uid}")
    else:
        print("\n暂未有任何会话")
        print("[zyn]让好友给这个Bot发一条消息后，程序会自动记录")
    
    print("\n" + "┌" + "─" * 58 + "┐")
    print("│ 直接输入消息 -> 回复给当前用户" + " " * 23 + "│")
    print("│ /users  查看所有用户" + " " * 31 + "│")
    print("│ /switch 切换用户" + " " * 32 + "│")
    print("│ /web    打开网页聊天界面" + " " * 27 + "│")
    print("│ /quit   退出" + " " * 36 + "│")
    print("└" + "─" * 58 + "┘" + "\n")
    
    try:
        while True:
            user_input = input("send:").strip()
            if not user_input:
                continue
            if user_input == "/quit":
                break
            elif user_input == "/users":
                users = bot.list_users()
                if users:
                    print("[zyn]用户列表:")
                    for i, uid in enumerate(users, 1):
                        marker = "▶" if uid == bot.get_current_user() else "  "
                        print(f"{marker}{i}. {uid}")
                else:
                    print("[zyn]暂无用户")
                continue
            elif user_input.startswith("/switch "):
                target = user_input[8:].strip()
                bot.set_current_user(target)
                continue
            elif user_input == "/switch":
                users = bot.list_users()
                if len(users) <= 1:
                    print("[zyn]只有一个用户，无需切换")
                    continue
                print("[zyn]选择用户:")
                for i, uid in enumerate(users, 1):
                    print(f"  {i}. {uid}")
                try:
                    choice = input("[zyn]请输入序号: ").strip()
                    idx = int(choice) - 1
                    if 0 <= idx < len(users):
                        bot.set_current_user(users[idx])
                    else:
                        print("[zyn]无效序号")
                except ValueError:
                    print("[zyn]请输入数字")
                continue
            elif user_input == "/web":
                bot._open_browser()
                continue
            else:
                current = bot.get_current_user()
                if not current:
                    print("[zyn]没有可回复的用户，请让好友先发消息")
                    continue
                bot.send_text(current, user_input)
    except KeyboardInterrupt:
        print()
    finally:
        bot.stop()

if __name__ == "__main__":
    main()