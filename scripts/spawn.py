"""以 detached 方式启动任意子进程，输出 PID。

用途：绕开 PowerShell 5.1 的 Start-Process 在本机环境下的崩溃
（Env: 驱动器存在 Path / PATH 重复键，Start-Process 复制环境字典时报
"已添加项。字典中的关键字:Path 所添加的关键字:path"）。

用法：
  python scripts\\spawn.py --out a.log --err b.log -- <exe> [args...]
"""

from __future__ import annotations

import argparse
import subprocess
import sys

DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=None, help="stdout 追加写入的文件")
    parser.add_argument("--err", default=None, help="stderr 追加写入的文件")
    parser.add_argument("cmd", nargs=argparse.REMAINDER)
    args = parser.parse_args()

    cmd = list(args.cmd)
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    if not cmd:
        parser.error("缺少要执行的命令")

    kwargs: dict = {
        "stdin": subprocess.DEVNULL,
        "close_fds": True,
        "creationflags": DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
    }
    # 句柄要留给被拉起的进程持有，不能在这里用 with 关掉
    if args.out:
        kwargs["stdout"] = open(args.out, "ab", buffering=0)  # noqa: SIM115
    if args.err:
        kwargs["stderr"] = open(args.err, "ab", buffering=0)  # noqa: SIM115

    try:
        proc = subprocess.Popen(cmd, **kwargs)
    except OSError as exc:
        print(f"启动失败: {exc}", file=sys.stderr)
        return 1
    print(proc.pid)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
