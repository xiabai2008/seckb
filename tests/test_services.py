from pathlib import Path

from seckb.services import ServiceManager


class FakeResult:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class FakeRunner:
    def __init__(self, daemon_running: bool = False, taskkill_ok: bool = True) -> None:
        self.calls: list[list[str]] = []
        self.daemon_running = daemon_running
        self.taskkill_ok = taskkill_ok

    def __call__(self, cmd: list[str]) -> FakeResult:
        self.calls.append(list(cmd))
        joined = " ".join(cmd)
        if "daemon_ctl.py" in joined and cmd[-1] == "status":
            return FakeResult(0 if self.daemon_running else 1, "daemon 运行中" if self.daemon_running else "daemon 未运行")
        if "daemon_ctl.py" in joined:
            return FakeResult(0, "daemon 已启动")
        if cmd and cmd[0] == "taskkill":
            return FakeResult(0 if self.taskkill_ok else 1, "")
        return FakeResult(0, "12345")

    def find(self, needle: str) -> list[list[str]]:
        return [call for call in self.calls if needle in " ".join(call)]


class FakeProbe:
    def __init__(self, urls: dict[str, bool] | None = None) -> None:
        self.urls = urls or {}

    def __call__(self, url: str) -> bool:
        return bool(self.urls.get(url, False))


def make_manager(kb, runner: FakeRunner, probe: FakeProbe) -> ServiceManager:
    meili_exe = kb.root / "meta" / "bin" / "meilisearch.exe"
    meili_exe.parent.mkdir(parents=True, exist_ok=True)
    meili_exe.write_bytes(b"stub")
    ollama_exe = kb.root / "ollama-stub.exe"
    ollama_exe.write_bytes(b"stub")
    return ServiceManager(
        kb.settings,
        repo_root=Path(__file__).resolve().parents[1],
        runner=runner,
        probe=probe,
        ollama_exe=str(ollama_exe),
        meili_exe=meili_exe,
        ready_timeout=0,
    )


def test_status_reports_each_service(kb):
    runner = FakeRunner(daemon_running=True)
    probe = FakeProbe({"http://127.0.0.1:11434/api/tags": True})
    manager = make_manager(kb, runner, probe)
    probe.urls[f"{manager.meili_base}/health"] = True
    status = manager.status()
    assert status["ollama"]["running"] is True
    assert status["meilisearch"]["running"] is True
    assert status["daemon"]["running"] is True
    assert status["serve"]["running"] is True
    assert status["retrieval_ready"] is True


def test_status_reports_down_when_probes_fail(kb):
    runner = FakeRunner(daemon_running=False)
    manager = make_manager(kb, runner, FakeProbe())
    status = manager.status()
    assert status["ollama"]["running"] is False
    assert status["meilisearch"]["running"] is False
    assert status["daemon"]["running"] is False
    assert status["retrieval_ready"] is False


def test_start_search_spawns_missing_backends(kb):
    runner = FakeRunner()
    manager = make_manager(kb, runner, FakeProbe())
    result = manager.start("search")
    actions = {item["target"]: item["action"] for item in result["actions"]}
    assert actions["ollama"] == "started"
    assert actions["meilisearch"] == "started"
    spawn_calls = runner.find("spawn.py")
    assert len(spawn_calls) == 2
    assert any("ollama" in " ".join(call).lower() for call in spawn_calls)
    assert any("meilisearch.exe" in " ".join(call) for call in spawn_calls)
    daemon_calls = runner.find("daemon_ctl.py")
    assert daemon_calls
    assert all("start" not in call and "stop" not in call for call in daemon_calls)


def test_start_search_skips_running_backends(kb):
    runner = FakeRunner()
    probe = FakeProbe({"http://127.0.0.1:11434/api/tags": True})
    manager = make_manager(kb, runner, probe)
    probe.urls[f"{manager.meili_base}/health"] = True
    result = manager.start("search")
    actions = {item["target"]: item["action"] for item in result["actions"]}
    assert actions["ollama"] == "already-running"
    assert actions["meilisearch"] == "already-running"
    assert runner.find("spawn.py") == []


def test_start_collect_uses_daemon_ctl(kb):
    runner = FakeRunner(daemon_running=False)
    manager = make_manager(kb, runner, FakeProbe())
    result = manager.start("collect")
    assert result["actions"][0]["target"] == "daemon"
    assert result["actions"][0]["action"] == "started"
    start_calls = runner.find("daemon_ctl.py")
    assert any(call[2] == "start" for call in start_calls)


def test_start_all_stops_and_invalid_target(kb):
    runner = FakeRunner()
    manager = make_manager(kb, runner, FakeProbe())
    result = manager.start("all")
    targets = {item["target"] for item in result["actions"]}
    assert {"ollama", "meilisearch", "daemon"} <= targets
    try:
        manager.start("bogus")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")


def test_stop_search_kills_backend_processes(kb):
    runner = FakeRunner()
    manager = make_manager(kb, runner, FakeProbe())
    result = manager.stop("all")
    killed = [call[2] for call in runner.find("taskkill")]
    assert "meilisearch.exe" in killed
    assert "ollama.exe" in killed
    stop_calls = runner.find("daemon_ctl.py")
    assert any(call[-1] == "stop" for call in stop_calls)
    actions = {(item["target"], item["action"]) for item in result["actions"]}
    assert ("meilisearch.exe", "stopped") in actions
    assert ("daemon", "stopped") in actions
