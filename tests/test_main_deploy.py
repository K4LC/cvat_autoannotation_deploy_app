"""POST /jobs / GET /jobs のデプロイ関連テスト — req_add02 §3/§13/§15 (ステップ5)。

FastAPI TestClient を使い、依存 (store/queue) を差し替える。parse_svg と
storage/CVAT パスは monkeypatch する。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import app.config as config_mod
import app.main as main
from app.jobs.store import JobStore
from app.schemas import DeployTarget, JobRecord, JobStatus


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


class FakeQueue:
    def __init__(self) -> None:
        self.enqueued = []

    def enqueue(self, func, *args, **kwargs):
        self.enqueued.append((func, args, kwargs))


@pytest.fixture
def client(monkeypatch, tmp_path):
    conn = FakeConn()
    store = JobStore(conn)
    queue = FakeQueue()

    main.app.dependency_overrides[main.get_store] = lambda: store
    main.app.dependency_overrides[main.get_job_queue] = lambda: queue

    # storage を tmp に (アップロード保存先)
    monkeypatch.setattr(config_mod.settings, "storage_dir", str(tmp_path / "storage"))
    # 既定は CVAT 未設定 (事前チェックをスキップ)
    monkeypatch.setattr(config_mod.settings, "cvat_base_path", "")
    # SVG 解析はダミー
    monkeypatch.setattr(
        main, "parse_svg", lambda p: SimpleNamespace(labels=[], keypoints=None, skeleton=None)
    )

    c = TestClient(main.app)
    c._conn = conn  # type: ignore[attr-defined]
    c._store = store  # type: ignore[attr-defined]
    c._queue = queue  # type: ignore[attr-defined]
    yield c
    main.app.dependency_overrides.clear()


def _files():
    return {
        "svg": ("model.svg", b"<svg/>", "image/svg+xml"),
        "pt": ("model.pt", b"weights", "application/octet-stream"),
    }


def _data(**over):
    base = {
        "author": "Alice",
        "display_name": "Human Pose",
        "svg_label": "person",
        "deploy_target": "cpu",
    }
    base.update(over)
    return base


def _saved_record(client) -> JobRecord:
    job_id = client._queue.enqueued[0][1][0]
    return client._store.get(job_id)


def test_create_job_default_cpu(client):
    res = client.post("/jobs", data=_data(), files=_files())
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "queued"
    rec = _saved_record(client)
    assert rec.deploy_target == DeployTarget.CPU
    assert rec.cvat_base_path == ""
    assert rec.deploy_script_path is None


def test_create_job_gpu(client):
    res = client.post("/jobs", data=_data(deploy_target="gpu"), files=_files())
    assert res.status_code == 200, res.text
    assert _saved_record(client).deploy_target == DeployTarget.GPU


def test_create_job_invalid_deploy_target(client):
    res = client.post("/jobs", data=_data(deploy_target="tpu"), files=_files())
    assert res.status_code == 400
    assert "CPU または GPU" in res.json()["detail"]


def test_create_job_precheck_serverless_missing(client, monkeypatch, tmp_path):
    # CVAT を設定するが serverless ディレクトリは無い -> 400
    monkeypatch.setattr(config_mod.settings, "cvat_base_path", str(tmp_path / "cvat_root"))
    res = client.post("/jobs", data=_data(), files=_files())
    assert res.status_code == 400
    assert "serverless" in res.json()["detail"]


def test_create_job_precheck_script_missing(client, monkeypatch, tmp_path):
    root = tmp_path / "cvat_root"
    (root / "cvat" / "serverless").mkdir(parents=True)  # serverless はあるが script 無し
    monkeypatch.setattr(config_mod.settings, "cvat_base_path", str(root))
    res = client.post("/jobs", data=_data(), files=_files())
    assert res.status_code == 400
    assert "deploy スクリプト" in res.json()["detail"]


def test_create_job_precheck_ok_records_script_path(client, monkeypatch, tmp_path):
    root = tmp_path / "cvat_root"
    serverless = root / "cvat" / "serverless"
    serverless.mkdir(parents=True)
    (serverless / "deploy_cpu.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(config_mod.settings, "cvat_base_path", str(root))

    res = client.post("/jobs", data=_data(), files=_files())
    assert res.status_code == 200, res.text
    rec = _saved_record(client)
    assert rec.deploy_script_path == str(serverless / "deploy_cpu.sh")
    assert rec.cvat_base_path == str(root)


def _seed(client, **over) -> str:
    rec = JobRecord(
        job_id="j1",
        author="a",
        display_name="Human Pose",
        svg_label="person",
        function_name="human-pose-202607061530",
        pt_path="/x/model.pt",
        svg_path="/x/model.svg",
        download_token="tok",
        **over,
    )
    client._store.save(rec)
    return "j1"


def test_get_job_exposes_deploy_fields(client):
    _seed(
        client,
        status=JobStatus.FAILED,
        deploy_target=DeployTarget.GPU,
        exported_folder_path="/cvat/serverless/mymodel/human-pose-202607061530",
        deploy_script_path="/cvat/serverless/deploy_gpu.sh",
        deploy_return_code=1,
        deploy_stdout_tail="out",
        deploy_stderr_tail="err",
    )
    body = client.get("/jobs/j1").json()
    assert body["deploy_target"] == "gpu"
    assert body["deploy_return_code"] == 1
    assert body["deploy_stderr_tail"] == "err"
    assert body["exported_folder_path"].endswith("human-pose-202607061530")
    assert body["download_url"] is None  # 失敗時はダウンロード不可


def test_get_job_download_url_only_when_zip_present(client):
    # SUCCESS だが zip_path 無し (デプロイ運用) -> download_url は None
    _seed(client, status=JobStatus.SUCCESS, zip_path=None)
    assert client.get("/jobs/j1").json()["download_url"] is None

    # SUCCESS かつ zip_path あり -> download_url が付く
    client._store.set_status("j1", JobStatus.SUCCESS, zip_path="/x/out.zip")
    assert client.get("/jobs/j1").json()["download_url"] is not None
