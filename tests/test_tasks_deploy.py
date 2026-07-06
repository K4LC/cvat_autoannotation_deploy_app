"""process_job の CVAT 保存 + deploy 委譲テスト — req_add02 §12/§13 (deploy 分離)。

deploy は worker では実行せず "deploy" キューへ enqueue する設計。重い段階
(SVG解析/ONNX変換/テンプレ生成) は軽量 fake に差し替え、zip 作成・CVAT 保存は実物を
通す。deploy キューは FakeQueue で捕捉する。Redis は dict ベースの FakeConn で代替。

検証:
- CVAT_BASE_PATH 設定時: mymodel へ保存し status=DEPLOYING、deploy キューへ enqueue
- CVAT_BASE_PATH 未設定: 保存/デプロイをスキップし zip のみで SUCCESS（enqueue しない）
- 保存に必要なファイル不足 (DeployError): FAILED + 例外送出
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import app.jobs.tasks as tasks
from app.jobs.store import JobStore
from app.schemas import DeployTarget, JobRecord, JobStatus

FUNC = "human-pose-202607061530"


class FakeConn:
    """JobStore が使う set/get/exists/delete のみを備えた最小の Redis 代替。"""

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
        self.enqueued: list[tuple] = []

    def enqueue(self, func, *args, **kwargs):
        self.enqueued.append((func, args, kwargs))


def _seed_job(conn, base: Path, *, deploy_target=DeployTarget.CPU) -> str:
    job_id = "job-1"
    (base / "input").mkdir(parents=True, exist_ok=True)
    (base / "input" / "model.pt").write_text("pt", encoding="utf-8")
    (base / "input" / "model.svg").write_text("<svg/>", encoding="utf-8")
    record = JobRecord(
        job_id=job_id,
        author="a",
        display_name="Human Pose",
        svg_label="person",
        function_name=FUNC,
        pt_path=str(base / "input" / "model.pt"),
        svg_path=str(base / "input" / "model.svg"),
        download_token="tok",
        deploy_target=deploy_target,
    )
    JobStore(conn).save(record)
    return job_id


@pytest.fixture
def patched(monkeypatch, tmp_path):
    """重い段階を fake 化し、storage を tmp に向け、deploy キューを FakeQueue にする。"""
    storage = tmp_path / "storage"
    monkeypatch.setattr(tasks.settings, "storage_dir", str(storage))

    monkeypatch.setattr(tasks, "parse_svg", lambda path: SimpleNamespace())
    monkeypatch.setattr(tasks, "build_context", lambda **kw: {})

    def fake_export(pt_path, out_dir, **kw):
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "model.onnx").write_text("onnx", encoding="utf-8")

    def fake_render(out_dir, context, **kw):
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        for name in ("function.yaml", "function-gpu.yaml", "main.py", "model_handler.py"):
            (out / name).write_text(name, encoding="utf-8")

    monkeypatch.setattr(tasks, "export_to_onnx", fake_export)
    monkeypatch.setattr(tasks, "render_all", fake_render)

    fake_queue = FakeQueue()
    monkeypatch.setattr(tasks, "get_queue", lambda **kw: fake_queue)
    return SimpleNamespace(storage=storage, tmp=tmp_path, queue=fake_queue)


def _set_cvat(monkeypatch, tmp_path) -> Path:
    cvat_root = tmp_path / "cvat_root"
    serverless = cvat_root / "cvat" / "serverless"
    serverless.mkdir(parents=True)
    monkeypatch.setattr(tasks.settings, "cvat_base_path", str(cvat_root))
    monkeypatch.setattr(tasks.settings, "deploy_queue_name", "deploy")
    return serverless


def test_saves_and_enqueues_deploy(patched, monkeypatch, tmp_path):
    serverless = _set_cvat(monkeypatch, tmp_path)
    conn = FakeConn()
    job_id = _seed_job(conn, tasks.job_dir("job-1"))

    ret = tasks.process_job(job_id, connection=conn)

    rec = JobStore(conn).get(job_id)
    # deploy はまだ実行しない -> DEPLOYING で待機
    assert rec.status == JobStatus.DEPLOYING
    assert rec.exported_folder_path.endswith(FUNC)
    assert rec.zip_path is not None  # zip 併用
    exported = Path(rec.exported_folder_path)
    assert exported == serverless / "mymodel" / FUNC
    assert sorted(p.name for p in exported.iterdir()) == sorted(
        ["function.yaml", "function-gpu.yaml", "main.py", "model.onnx", "model_handler.py"]
    )
    # deploy キューへ run_deploy_job が積まれる
    assert len(patched.queue.enqueued) == 1
    func, args, _ = patched.queue.enqueued[0]
    assert func == "app.jobs.deploy_tasks.run_deploy_job"
    assert args == (job_id,)
    assert ret == str(exported)


def test_skip_when_cvat_base_path_unset(patched, monkeypatch, tmp_path):
    monkeypatch.setattr(tasks.settings, "cvat_base_path", "")
    conn = FakeConn()
    job_id = _seed_job(conn, tasks.job_dir("job-1"))

    ret = tasks.process_job(job_id, connection=conn)

    rec = JobStore(conn).get(job_id)
    assert rec.status == JobStatus.SUCCESS
    assert rec.zip_path is not None
    assert rec.exported_folder_path is None
    assert patched.queue.enqueued == []  # deploy へ委譲しない
    assert ret == rec.zip_path


def test_generation_failure_marks_failed_without_enqueue(patched, monkeypatch, tmp_path):
    _set_cvat(monkeypatch, tmp_path)
    conn = FakeConn()
    job_id = _seed_job(conn, tasks.job_dir("job-1"))

    # 生成物の 1 つを欠落させる。zip 作成 (build_zip) が保存より前に失敗する。
    orig_render = tasks.render_all

    def broken_render(out_dir, context, **kw):
        orig_render(out_dir, context, **kw)
        (Path(out_dir) / "model_handler.py").unlink()

    monkeypatch.setattr(tasks, "render_all", broken_render)

    from app.services.packager import PackagingError

    with pytest.raises(PackagingError):
        tasks.process_job(job_id, connection=conn)

    rec = JobStore(conn).get(job_id)
    assert rec.status == JobStatus.FAILED
    assert "model_handler.py" in rec.message
    assert patched.queue.enqueued == []  # 失敗時は deploy へ委譲しない
