"""Detect the official macOS managed keys without decoding their configuration."""

import ctypes
import sys
from pathlib import Path

MANAGED_ROOTS = (Path("/etc/codex"), Path("/Library/Application Support/OpenAI/Codex"))


def managed_policy_present() -> bool:
    if any(path.exists() for path in MANAGED_ROOTS):
        return True
    if sys.platform != "darwin":
        return False
    core = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
    core.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
    core.CFStringCreateWithCString.restype = ctypes.c_void_p
    core.CFPreferencesCopyAppValue.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    core.CFPreferencesCopyAppValue.restype = ctypes.c_void_p
    core.CFRelease.argtypes = [ctypes.c_void_p]
    domain = core.CFStringCreateWithCString(None, b"com.openai.codex", 0x08000100)
    if not domain:
        raise RuntimeError("管理者ポリシーの存在確認に失敗しました。")
    try:
        for name in (b"config_toml_base64", b"requirements_toml_base64"):
            key = core.CFStringCreateWithCString(None, name, 0x08000100)
            if not key:
                raise RuntimeError("管理者ポリシーの存在確認に失敗しました。")
            try:
                value = core.CFPreferencesCopyAppValue(key, domain)
                if value:
                    core.CFRelease(value)
                    return True
            finally:
                core.CFRelease(key)
        return False
    finally:
        core.CFRelease(domain)
