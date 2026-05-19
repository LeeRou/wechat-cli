"""配置加载 — 从 ~/.wechat-cli/ 读取自包含配置"""

import glob as glob_mod
import json
import os
import platform
import sys

_SYSTEM = platform.system().lower()

if _SYSTEM == "linux":
    _DEFAULT_PROCESS = "wechat"
elif _SYSTEM == "darwin":
    _DEFAULT_PROCESS = "WeChat"
else:
    _DEFAULT_PROCESS = "Weixin.exe"

# CLI 状态目录
STATE_DIR = os.path.expanduser("~/.wechat-cli")
CONFIG_FILE = os.path.join(STATE_DIR, "config.json")
KEYS_FILE = os.path.join(STATE_DIR, "all_keys.json")


def _choose_candidate(candidates):
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        if not sys.stdin.isatty():
            return candidates[0]
        print("[!] 检测到多个微信数据目录:")
        for i, c in enumerate(candidates, 1):
            print(f"    {i}. {c}")
        print("    0. 跳过")
        try:
            while True:
                choice = input(f"请选择 [0-{len(candidates)}]: ").strip()
                if choice == "0":
                    return None
                if choice.isdigit() and 1 <= int(choice) <= len(candidates):
                    return candidates[int(choice) - 1]
                print("    无效输入")
        except (EOFError, KeyboardInterrupt):
            print()
            return None
    return None


def _get_windows_documents():
    """获取 Windows 实际的 Documents 文件夹路径 (处理重定向到 D 盘等情况)"""
    # 方法1: 通过 Windows Registry 读取
    import winreg
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
        )
        value, _ = winreg.QueryValueEx(key, "Personal")
        winreg.CloseKey(key)
        # 展开 %USERPROFILE% 等环境变量
        resolved = os.path.expandvars(value)
        if os.path.isdir(resolved):
            return resolved
    except (OSError, ImportError):
        pass

    # 方法2: 通过 USERPROFILE
    userprofile = os.environ.get("USERPROFILE", "")
    docs = os.path.join(userprofile, "Documents")
    if os.path.isdir(docs):
        return docs

    # 方法3: ~/Documents
    return os.path.expanduser("~/Documents")


def _resolve_windows_special_folder(name):
    """将 Windows 特殊文件夹名（如 MyDocument:）解析为实际路径"""
    name_lower = name.strip().lower().rstrip(":")
    if name_lower in ("mydocument", "mydocuments", "personal"):
        return _get_windows_documents()
    if name_lower == "desktop":
        return os.path.expanduser("~/Desktop")
    if name_lower == "appdata":
        return os.environ.get("APPDATA", "")
    if name_lower == "localappdata":
        return os.environ.get("LOCALAPPDATA", "")
    return None


def _auto_detect_db_dir_windows():
    """Windows 下自动检测微信数据目录 (支持 3.x 和 4.x)"""
    seen = set()
    candidates = []
    data_roots = []

    # 1. 从 xwechat config .ini 读取数据根目录
    appdata = os.environ.get("APPDATA", "")
    config_dir = os.path.join(appdata, "Tencent", "xwechat", "config")
    if os.path.isdir(config_dir):
        for ini_file in glob_mod.glob(os.path.join(config_dir, "*.ini")):
            try:
                content = None
                for enc in ("utf-8", "gbk", "ascii"):
                    try:
                        with open(ini_file, "r", encoding=enc) as f:
                            content = f.read(1024).strip()
                        break
                    except UnicodeDecodeError:
                        continue
                if not content or any(c in content for c in "\n\r\x00"):
                    continue
                # 尝试直接作为路径
                if os.path.isdir(content):
                    data_roots.append(content)
                    continue
                # 尝试解析 Windows 特殊文件夹名
                resolved = _resolve_windows_special_folder(content)
                if resolved and os.path.isdir(resolved):
                    data_roots.append(resolved)
            except OSError:
                continue

    # 2. 搜索 xwechat_files (微信 4.x 新版)
    search_roots = list(data_roots)  # 从 .ini 读到的路径
    # 额外兜底路径
    real_docs = _get_windows_documents()
    userprofile = os.environ.get("USERPROFILE", "")
    username = os.environ.get("USERNAME", "")
    for base in [
        real_docs,
        os.path.expanduser("~/Desktop"),
        os.path.join(userprofile, "Documents"),
    ]:
        if base and os.path.isdir(base) and base not in search_roots:
            search_roots.append(base)
    # 也搜其他盘上的同名用户目录（处理 Documents 重定向到 D:/E: 等情况）
    for drive in ["D:", "E:", "F:"]:
        alt_docs = os.path.join(drive + "\\", "Users", username, "Documents")
        if os.path.isdir(alt_docs) and alt_docs not in search_roots:
            search_roots.append(alt_docs)
        # 也搜盘根下的一级目录
        try:
            entries = os.listdir(drive + "\\")
            for entry in entries:
                p = os.path.join(drive + "\\", entry)
                if os.path.isdir(p) and p not in search_roots:
                    search_roots.append(p)
        except OSError:
            continue

    # 在所有根目录下搜 xwechat_files (新版)
    for root in search_roots:
        if not os.path.isdir(root):
            continue
        # 直接搜 xwechat_files
        xwf_pattern = os.path.join(root, "xwechat_files", "*", "db_storage")
        for match in glob_mod.glob(xwf_pattern):
            normalized = os.path.normcase(os.path.normpath(match))
            if os.path.isdir(match) and normalized not in seen:
                seen.add(normalized)
                candidates.append(match)

    # 3. 搜索旧版微信目录 (3.x)
    old_patterns = [
        os.path.join(root, "WeChat Files", "*", "db_storage")
        for root in search_roots if os.path.isdir(root)
    ]
    for pattern in old_patterns:
        for match in glob_mod.glob(pattern):
            normalized = os.path.normcase(os.path.normpath(match))
            if os.path.isdir(match) and normalized not in seen:
                seen.add(normalized)
                candidates.append(match)

    # 4. 最后尝试旧版微信默认文档路径
    legacy_doc = os.path.join(real_docs, "WeChat Files")
    if os.path.isdir(legacy_doc):
        for user_dir in os.listdir(legacy_doc):
            db_storage = os.path.join(legacy_doc, user_dir, "db_storage")
            normalized = os.path.normcase(os.path.normpath(db_storage))
            if os.path.isdir(db_storage) and normalized not in seen:
                seen.add(normalized)
                candidates.append(db_storage)

    # 5. 按最后修改时间排序（优先最新数据）
    def _mtime(path):
        msg_dir = os.path.join(path, "message")
        target = msg_dir if os.path.isdir(msg_dir) else path
        try:
            return os.path.getmtime(target)
        except OSError:
            return 0
    candidates.sort(key=_mtime, reverse=True)

    return _choose_candidate(candidates)


def _auto_detect_db_dir_linux():
    seen = set()
    candidates = []
    # xwechat_files (新版 4.x)
    search_roots = [os.path.expanduser("~/Documents/xwechat_files")]
    # 旧版 WeChat Files
    legacy = os.path.expanduser("~/Documents/WeChat Files")
    if os.path.isdir(legacy):
        search_roots.append(legacy)
    # sudo 场景
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user:
        import pwd
        try:
            sudo_home = pwd.getpwnam(sudo_user).pw_dir
        except KeyError:
            sudo_home = None
        if sudo_home:
            for sub in ("Documents/xwechat_files", "Documents/WeChat Files"):
                fallback = os.path.join(sudo_home, sub)
                if os.path.isdir(fallback) and fallback not in search_roots:
                    search_roots.append(fallback)
    # 旧版 wine 微信
    wine_path = os.path.expanduser("~/.local/share/weixin/data/db_storage")
    if os.path.isdir(wine_path):
        normalized = os.path.normcase(os.path.normpath(wine_path))
        if normalized not in seen:
            seen.add(normalized)
            candidates.append(wine_path)

    for root in search_roots:
        if not os.path.isdir(root):
            continue
        # 直接在根下搜 db_storage 子目录 (xwechat_files/<user>/db_storage 结构)
        if "xwechat_files" in root or "WeChat Files" in root:
            pattern = os.path.join(root, "*", "db_storage")
        else:
            pattern = os.path.join(root, "db_storage")
        for match in glob_mod.glob(pattern):
            normalized = os.path.normcase(os.path.normpath(match))
            if os.path.isdir(match) and normalized not in seen:
                seen.add(normalized)
                candidates.append(match)

    def _mtime(path):
        msg_dir = os.path.join(path, "message")
        target = msg_dir if os.path.isdir(msg_dir) else path
        try:
            return os.path.getmtime(target)
        except OSError:
            return 0
    candidates.sort(key=_mtime, reverse=True)
    return _choose_candidate(candidates)


def _auto_detect_db_dir_macos():
    """macOS 自动检测 (支持新版 4.x 和旧版 3.x)"""
    seen = set()
    candidates = []

    # 新版微信 4.x: ~/Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files/*/db_storage
    new_base = os.path.expanduser(
        "~/Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files"
    )
    search_roots = [new_base]

    # 旧版微信 3.x: ~/Library/Containers/com.tencent.xinWeChat/Data/Library/Application Support/com.tencent.xinWeChat/.../Msg
    legacy_base = os.path.expanduser(
        "~/Library/Containers/com.tencent.xinWeChat/Data/Library/Application Support/com.tencent.xinWeChat"
    )
    if os.path.isdir(legacy_base):
        search_roots.append(legacy_base)

    for root in search_roots:
        if not os.path.isdir(root):
            continue
        if "xwechat_files" in root:
            pattern = os.path.join(root, "*", "db_storage")
        else:
            # 旧版路径可能不同，也尝试 db_storage 直搜
            for sub in glob_mod.glob(os.path.join(root, "*", "*", "db_storage")):
                normalized = os.path.normcase(os.path.normpath(sub))
                if os.path.isdir(sub) and normalized not in seen:
                    seen.add(normalized)
                    candidates.append(sub)
            pattern = os.path.join(root, "db_storage")
        for match in glob_mod.glob(pattern):
            normalized = os.path.normcase(os.path.normpath(match))
            if os.path.isdir(match) and normalized not in seen:
                seen.add(normalized)
                candidates.append(match)

    return _choose_candidate(candidates)


def auto_detect_db_dir():
    if _SYSTEM == "windows":
        return _auto_detect_db_dir_windows()
    if _SYSTEM == "linux":
        return _auto_detect_db_dir_linux()
    if _SYSTEM == "darwin":
        return _auto_detect_db_dir_macos()
    return None


def load_config(config_path=None):
    """加载配置。默认从 ~/.wechat-cli/config.json 读取。"""
    if config_path is None:
        config_path = CONFIG_FILE

    cfg = {}
    if os.path.exists(config_path):
        try:
            with open(config_path, encoding="utf-8") as f:
                cfg = json.load(f)
        except json.JSONDecodeError:
            cfg = {}

    # db_dir 缺失时，自动检测
    db_dir = cfg.get("db_dir", "")
    if not db_dir:
        detected = auto_detect_db_dir()
        if detected:
            cfg["db_dir"] = detected
        else:
            raise FileNotFoundError(
                "未找到微信数据目录。\n"
                "请运行: wechat-cli init"
            )

    # 设置默认值
    state_dir = os.path.dirname(os.path.abspath(config_path))
    cfg.setdefault("keys_file", os.path.join(state_dir, "all_keys.json"))
    cfg.setdefault("decrypted_dir", os.path.join(state_dir, "decrypted"))
    cfg.setdefault("decoded_image_dir", os.path.join(state_dir, "decoded_images"))
    cfg.setdefault("wechat_process", _DEFAULT_PROCESS)

    # 所有路径确保为绝对路径
    for key in ("db_dir", "keys_file", "decrypted_dir", "decoded_image_dir"):
        if key in cfg and not os.path.isabs(cfg[key]):
            cfg[key] = os.path.join(state_dir, cfg[key])

    # 推导微信数据根目录
    db_dir = cfg.get("db_dir", "")
    if db_dir and os.path.basename(db_dir) == "db_storage":
        cfg["wechat_base_dir"] = os.path.dirname(db_dir)
    else:
        cfg["wechat_base_dir"] = db_dir

    return cfg
