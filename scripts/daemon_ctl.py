"""seckb 守护进程启停控制（Windows）。

存在的理由：本机 PowerShell 的 Env: 驱动器存在 Path / PATH 大小写重复项，
Start-Process 在复制环境字典时会抛 "已添加了相同键的项"，
导致 kb_start.ps1 里的 daemon 启动静默失败（$ErrorActionPreference=SilentlyContinue 吞掉了异常）。
本脚本直接用 subprocess + DETACHED_PROCESS 拉起，完全绕开 PowerShell 的参数绑定。

用法：
  .venv\\Scripts\\python.exe scripts\\daemon_ctl.py start [--api-key XXX]
  .venv\\Scripts\\python.exe scripts\\daemon_ctl.py stop
  .venv\\Scripts\\python.exe scripts\\daemon_ctl.py status
"""

from __future__ import annotations

import argparse
import ctypes
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PYTHON = REPO / ".venv" / "Scripts" / "python.exe"
LOG_DIR = Path("D:/SecurityKB/meta/logs")
PID_FILE = LOG_DIR / "daemon.pid"

PROCESS_TERMINATE = 0x0001
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
STILL_ACTIVE = 259
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200

kernel32 = ctypes.windll.kernel32


def _is_alive(pid: int) -> bool:
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return code.value == STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def _terminate(pid: int) -> bool:
    handle = kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
    if not handle:
        return False
    try:
        return bool(kernel32.TerminateProcess(handle, 1))
    finally:
        kernel32.CloseHandle(handle)


def _read_pid() -> int | None:
    if not PID_FILE.exists():
        return None
    try:
        return int(PID_FILE.read_text(encoding="utf-8").strip())
    except ValueError:
        return None


def cmd_status() -> int:
    pid = _read_pid()
    if pid and _is_alive(pid):
        print(f"daemon 运行中 (PID {pid})")
        return 0
    if pid:
        print(f"daemon 未运行（PID {pid} 已退出，残留 pid 文件）")
    else:
        print("daemon 未运行")
    return 1


def cmd_start(api_key: str | None) -> int:
    pid = _read_pid()
    if pid and _is_alive(pid):
        print(f"daemon 已在运行 (PID {pid})")
        return 0

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    if api_key:
        env["OPENCODE_API_KEY"] = api_key
    elif not env.get("OPENCODE_API_KEY"):
        print("警告：OPENCODE_API_KEY 为空，富化任务会被静默跳过", file=sys.stderr)

    out = open(LOG_DIR / "daemon.out.log", "ab", buffering=0)
    err = open(LOG_DIR / "daemon.err.log", "ab", buffering=0)
    proc = subprocess.Popen(
        [str(PYTHON), "-m", "seckb", "daemon"],
        cwd=str(REPO),
        stdin=subprocess.DEVNULL,
        stdout=out,
        stderr=err,
        env=env,
        creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
        close_fds=True,
    )
    PID_FILE.write_text(str(proc.pid), encoding="utf-8")

    for _ in range(20):
        time.sleep(0.25)
        if not _is_alive(proc.pid):
            print(f"daemon 启动后立即退出 (PID {proc.pid})，请查看 {LOG_DIR / 'daemon.err.log'}", file=sys.stderr)
            return 1
    print(f"daemon 已启动 (PID {proc.pid})")
    return 0


def cmd_stop() -> int:
    pid = _read_pid()
    if not pid:
        print("没有 pid 文件，未发现由本脚本启动的 daemon")
        return 1
    if not _is_alive(pid):
        PID_FILE.unlink(missing_ok=True)
        print("daemon 已不在运行，已清理 pid 文件")
        return 0
    if not _terminate(pid):
        print(f"终止 PID {pid} 失败，可能需要管理员权限", file=sys.stderr)
        return 1
    time.sleep(0.5)
    PID_FILE.unlink(missing_ok=True)
    print(f"daemon 已停止 (PID {pid})")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    p_start = sub.add_parser("start")
    p_start.add_argument("--api-key", default=None)
    sub.add_parser("stop")
    sub.add_parser("status")
    args = parser.parse_args()

    if args.command == "start":
        return cmd_start(args.api_key)
    if args.command == "stop":
        return cmd_stop()
    return cmd_status()


if __name__ == "__main__":
    raise SystemExit(main())
