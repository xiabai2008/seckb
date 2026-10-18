from __future__ import annotations

import ipaddress
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from seckb.config import Settings

VALID_TARGETS = ("search", "collect", "all")
OLLAMA_PROBE = "http://127.0.0.1:11434/api/tags"
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


def _default_runner(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=60, check=False, shell=False
    )


def _loopback_probe_url(url: str) -> str | None:
    """把探测地址收敛到本机 http 端点，其余一律返回 None（不发起请求）。

    Ollama 与 Meilisearch 都按设计跑在本机；探针接收 URL 参数，若不校验就
    等同于一个任意地址请求器。除协议与主机名外，解析结果也逐个校验，避免
    主机名指向本机以外的地址。
    """
    parts = urlsplit(url)
    if parts.scheme != "http" or parts.hostname not in LOOPBACK_HOSTS:
        return None
    port = parts.port or 80
    try:
        infos = socket.getaddrinfo(parts.hostname, port, type=socket.SOCK_STREAM)
    except OSError:
        return None
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            return None
        if not ip.is_loopback:
            return None
    return f"http://{parts.hostname}:{port}{parts.path or '/'}"


def _default_probe(url: str) -> bool:
    target = _loopback_probe_url(url)
    if target is None:
        return False
    try:
        return 200 <= httpx.get(target, timeout=4).status_code < 300
    except Exception:  # noqa: BLE001 - 服务未启动即为探测失败
        return False


def _user_env(name: str) -> str:
    if os.name != "nt":
        return os.environ.get(name, "")
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _ = winreg.QueryValueEx(key, name)
            return str(value)
    except OSError:
        return os.environ.get(name, "")


def _opencode_api_key() -> str:
    key = os.environ.get("OPENCODE_API_KEY") or _user_env("OPENCODE_API_KEY")
    if key:
        return key
    auth = Path.home() / ".local" / "share" / "opencode" / "auth.json"
    try:
        data = json.loads(auth.read_text(encoding="utf-8"))
        return str(data.get("opencode-go", {}).get("key", ""))
    except (OSError, json.JSONDecodeError):
        return ""


class ServiceManager:
    """知识库后端的启停管理：Ollama / Meilisearch（检索）+ daemon（自动采集富化）。"""

    def __init__(
        self,
        settings: Settings,
        *,
        repo_root: Path | None = None,
        runner: Callable[[list[str]], subprocess.CompletedProcess] | None = None,
        probe: Callable[[str], bool] | None = None,
        ollama_exe: str | None = None,
        meili_exe: Path | None = None,
        ready_timeout: float = 8.0,
    ) -> None:
        self.settings = settings
        self.repo_root = Path(repo_root) if repo_root else Path(__file__).resolve().parent.parent
        self._runner = runner or _default_runner
        self._probe = probe or _default_probe
        self._ollama_exe_override = ollama_exe
        self._meili_exe_override = meili_exe
        self.ready_timeout = ready_timeout

    @property
    def python(self) -> str:
        return sys.executable

    @property
    def spawn_script(self) -> Path:
        return self.repo_root / "scripts" / "spawn.py"

    @property
    def daemon_ctl(self) -> Path:
        return self.repo_root / "scripts" / "daemon_ctl.py"

    @property
    def logs_dir(self) -> Path:
        return self.settings.kb_root / "meta" / "logs"

    @property
    def meili_base(self) -> str:
        meili = (self.settings.enrich or {}).get("meili") or {}
        return str(meili.get("base_url", "http://127.0.0.1:9011")).rstrip("/")

    def _meili_key(self) -> str:
        return os.environ.get("MEILI_MASTER_KEY") or _user_env("MEILI_MASTER_KEY")

    def _ollama_exe(self) -> str | None:
        if self._ollama_exe_override:
            return self._ollama_exe_override
        candidate = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"
        if candidate.exists():
            return str(candidate)
        return shutil.which("ollama")

    def _meili_exe(self) -> Path:
        return self._meili_exe_override or (
            self.settings.kb_root / "meta" / "bin" / "meilisearch.exe"
        )

    def _daemon_running(self) -> bool:
        result = self._runner([self.python, str(self.daemon_ctl), "status"])
        return getattr(result, "returncode", 1) == 0

    def _spawn(self, exe: str, args: list[str], log_name: str) -> dict:
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        cmd = [
            self.python,
            str(self.spawn_script),
            "--out",
            str(self.logs_dir / f"{log_name}.out.log"),
            "--err",
            str(self.logs_dir / f"{log_name}.err.log"),
            "--",
            exe,
            *args,
        ]
        result = self._runner(cmd)
        return {
            "returncode": getattr(result, "returncode", 1),
            "stdout": (getattr(result, "stdout", "") or "").strip(),
        }

    def status(self) -> dict:
        ollama_ok = self._probe(OLLAMA_PROBE)
        meili_ok = self._probe(f"{self.meili_base}/health")
        daemon_ok = self._daemon_running()
        return {
            "ollama": {"running": ollama_ok, "url": "http://127.0.0.1:11434"},
            "meilisearch": {"running": meili_ok, "url": self.meili_base},
            "daemon": {"running": daemon_ok},
            "serve": {"running": True},
            "retrieval_ready": ollama_ok and meili_ok,
        }

    def _start_search(self, actions: list[dict]) -> None:
        if self._probe(OLLAMA_PROBE):
            actions.append({"target": "ollama", "action": "already-running"})
        else:
            exe = self._ollama_exe()
            if not exe:
                actions.append({"target": "ollama", "action": "failed", "detail": "未找到 ollama.exe"})
            else:
                outcome = self._spawn(exe, ["serve"], "ollama")
                actions.append(
                    {
                        "target": "ollama",
                        "action": "started" if outcome["returncode"] == 0 else "failed",
                        "detail": outcome["stdout"] or f"exit={outcome['returncode']}",
                    }
                )
        if self._probe(f"{self.meili_base}/health"):
            actions.append({"target": "meilisearch", "action": "already-running"})
            return
        exe_path = self._meili_exe()
        if not exe_path.exists():
            actions.append(
                {"target": "meilisearch", "action": "failed", "detail": f"未找到 {exe_path}"}
            )
            return
        port = self.meili_base.rsplit(":", 1)[-1]
        outcome = self._spawn(
            str(exe_path),
            [
                "--db-path",
                str(self.settings.kb_root / "meta" / "meili"),
                "--master-key",
                self._meili_key(),
                "--http-addr",
                f"127.0.0.1:{port}",
            ],
            "meili",
        )
        actions.append(
            {
                "target": "meilisearch",
                "action": "started" if outcome["returncode"] == 0 else "failed",
                "detail": outcome["stdout"] or f"exit={outcome['returncode']}",
            }
        )

    def _start_collect(self, actions: list[dict]) -> None:
        if self._daemon_running():
            actions.append({"target": "daemon", "action": "already-running"})
            return
        cmd = [self.python, str(self.daemon_ctl), "start"]
        api_key = _opencode_api_key()
        if api_key:
            cmd += ["--api-key", api_key]
        result = self._runner(cmd)
        actions.append(
            {
                "target": "daemon",
                "action": "started" if getattr(result, "returncode", 1) == 0 else "failed",
                "detail": (
                    (getattr(result, "stdout", "") or getattr(result, "stderr", "") or "")
                    .strip()
                    .splitlines()[-1:]
                    or [""]
                )[0],
            }
        )

    def _stop_processes(self, images: list[str], actions: list[dict]) -> None:
        for image in images:
            result = self._runner(["taskkill", "/IM", image, "/F"])
            stopped = getattr(result, "returncode", 1) == 0
            actions.append({"target": image, "action": "stopped" if stopped else "not-running"})

    def _ready_for(self, what: str) -> bool:
        if what == "collect":
            return self._daemon_running()
        if what == "search":
            return self._probe(OLLAMA_PROBE) and self._probe(f"{self.meili_base}/health")
        return (
            self._probe(OLLAMA_PROBE)
            and self._probe(f"{self.meili_base}/health")
            and self._daemon_running()
        )

    def start(self, what: str) -> dict:
        if what not in VALID_TARGETS:
            raise ValueError(f"未知目标: {what}（可选 search / collect / all）")
        actions: list[dict] = []
        if what in ("search", "all"):
            self._start_search(actions)
        if what in ("collect", "all"):
            self._start_collect(actions)
        deadline = time.time() + self.ready_timeout
        while time.time() < deadline and not self._ready_for(what):
            time.sleep(0.8)
        return {"what": what, "actions": actions, "status": self.status()}

    def stop(self, what: str) -> dict:
        if what not in VALID_TARGETS:
            raise ValueError(f"未知目标: {what}（可选 search / collect / all）")
        actions: list[dict] = []
        if what in ("search", "all"):
            self._stop_processes(["meilisearch.exe", "ollama.exe", "ollama app.exe"], actions)
        if what in ("collect", "all"):
            result = self._runner([self.python, str(self.daemon_ctl), "stop"])
            stopped = getattr(result, "returncode", 1) == 0
            actions.append(
                {
                    "target": "daemon",
                    "action": "stopped" if stopped else "not-running",
                    "detail": (getattr(result, "stdout", "") or "").strip(),
                }
            )
        return {"what": what, "actions": actions, "status": self.status()}
