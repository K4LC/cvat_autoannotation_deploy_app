"""deploy ワーカータスク run_deploy_job のテスト — req_add02 §8/§9 (deploy 分離)。

WSL ホスト側の deploy ワーカーが処理するタスク。subprocess は runner 注入で差し替え、
Redis は FakeConn で代替する。CVAT 保存先 (exported_folder_path) は record 済みの前提。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import app.jobs.deploy_tasks as dt
from app.jobs.store import JobStore
from app.schemas import DeployTarget, JobRecord, JobStatus

FUNC = "human-pose-202607061530"


class FakeConn:
    def __init__(self) -> None:
        self._d: dict[str, bytes] = {}

    def set(self, key, value, ex=None):
        if not isinstance(value, (bytes, bytearray)):
            value = str(value).encode("utf-8")
        self._d[key] = value

    def get(self, key):
        return self._d.get(key)

    def exists(self, key):
        return 1 if key in self._d else 0

    def delete(self, key):
        self._d.pop(key, None)


@pytest.fixture
def env(monkeypatch, tmp_path):
    """CVAT serverless + 保存済み exported フォルダ + storage を用意し record を seed。"""
    cvat_root = tmp_path / "cvat_root"
    serverless = cvat_root / "cvat" / "serverless"
    exported = serverless / "mymodel" / FUNC
    exported.mkdir(parents=True)
    monkeypatch.setattr(dt.settings, "cvat_base_path", str(cvat_root))
    monkeypatch.setattr(dt.settings, "storage_dir", str(tmp_path / "storage"))
    monkeypatch.setattr(dt.settings, "deploy_timeout_seconds", 60)
    return SimpleNamespace(serverless=serverless, exported=exported, tmp=tmp_path)


def _seed(conn, *, deploy_target=DeployTarget.CPU, exported=None) -> str:
    rec = JobRecord(
        job_id="job-1",
        author="a",
        display_name="Human Pose",
        svg_label="person",
        function_name=FUNC,
        pt_path="/x/model.pt",
        svg_path="/x/model.svg",
        download_token="tok",
        deploy_target=deploy_target,
        status=JobStatus.DEPLOYING,
        exported_folder_path=str(exported) if exported else None,
    )
    JobStore(conn).save(rec)
    return "job-1"


def _runner(returncode, stdout="", stderr="", capture=None):
    def run(argv, **kwargs):
        if capture is not None:
            capture["argv"] = argv
            capture["cwd"] = kwargs.get("cwd")
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)

    return run


def test_run_deploy_job_success(env):
    conn = FakeConn()
    job_id = _seed(conn, exported=env.exported)
    capture: dict = {}

    ret = dt.run_deploy_job(job_id, connection=conn, runner=_runner(0, stdout="ok", capture=capture))

    rec = JobStore(conn).get(job_id)
    assert rec.status == JobStatus.SUCCESS
    assert rec.progress == 100
    assert rec.deploy_return_code == 0
    assert rec.deploy_stdout_tail == "ok"
    assert rec.deploy_script_path.endswith("deploy_cpu.sh")
    assert capture["argv"] == ["./deploy_cpu.sh", f"./mymodel/{FUNC}"]
    assert capture["cwd"] == str(env.serverless)
    assert ret == str(env.exported)


def test_run_deploy_job_gpu(env):
    conn = FakeConn()
    job_id = _seed(conn, deploy_target=DeployTarget.GPU, exported=env.exported)
    capture: dict = {}
    dt.run_deploy_job(job_id, connection=conn, runner=_runner(0, capture=capture))
    assert capture["argv"][0] == "./deploy_gpu.sh"


def test_run_deploy_job_nonzero_failed(env):
    conn = FakeConn()
    job_id = _seed(conn, exported=env.exported)

    dt.run_deploy_job(job_id, connection=conn, runner=_runner(3, stderr="boom"))

    rec = JobStore(conn).get(job_id)
    assert rec.status == JobStatus.FAILED
    assert rec.deploy_return_code == 3
    assert rec.deploy_stderr_tail == "boom"
    assert "デプロイに失敗" in rec.message


def test_run_deploy_job_script_missing_raises(env):
    conn = FakeConn()
    job_id = _seed(conn, exported=env.exported)

    def run(argv, **kwargs):
        raise FileNotFoundError()

    from app.services.deployer import DeployError

    with pytest.raises(DeployError):
        dt.run_deploy_job(job_id, connection=conn, runner=run)

    rec = JobStore(conn).get(job_id)
    assert rec.status == JobStatus.FAILED
    assert "deploy_cpu.sh" in rec.message


def test_run_deploy_job_missing_exported_path(env):
    conn = FakeConn()
    job_id = _seed(conn, exported=None)  # 保存先未設定
    with pytest.raises(ValueError):
        dt.run_deploy_job(job_id, connection=conn, runner=_runner(0))


def test_run_deploy_job_uses_rq_job_connection_when_unset(env, monkeypatch):
    """connection 未指定時は RQ 現在ジョブの接続を流用する（REDIS_HOST 未設定でも動く）。"""
    conn = FakeConn()
    job_id = _seed(conn, exported=env.exported)

    # RQ の現在ジョブが FakeConn を持っているとみなす
    monkeypatch.setattr(dt, "get_current_job", lambda: SimpleNamespace(connection=conn))
    # get_redis_connection が呼ばれたら失敗させ、フォールバック経由でないことを保証
    monkeypatch.setattr(
        dt, "get_redis_connection", lambda: (_ for _ in ()).throw(AssertionError("should not be called"))
    )

    dt.run_deploy_job(job_id, runner=_runner(0, stdout="ok"))  # connection 未指定

    rec = JobStore(conn).get(job_id)
    assert rec.status == JobStatus.SUCCESS
    assert rec.deploy_return_code == 0
