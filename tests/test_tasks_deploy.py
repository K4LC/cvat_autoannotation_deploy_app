"""process_job の CVAT 保存 + 自動デプロイ組み込みテスト — req_add02 §12/§13 (ステップ4)。

重い段階 (SVG解析/ONNX変換/テンプレ生成) は軽量な fake に差し替え、
zip 作成・CVAT 保存・deploy 実行は実物を通す。deploy の subprocess のみ
`deploy_runner` で注入する。Redis は dict ベースの FakeConn で代替する。

検証:
- CVAT_BASE_PATH 設定時: SAVING_TO_CVAT→DEPLOYING→SUCCESS、deploy フィールド保存
- deploy 終了コード != 0: FAILED (例外でなく status で表現)
- deploy script 不在 (DeployError): FAILED + 例外送出
- CVAT_BASE_PATH 未設定: 保存/デプロイをスキップし zip のみで SUCCESS
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


def _seed_job(conn, base: Path, *, deploy_target=DeployTarget.CPU) -> str:
    """ジョブレコードを登録し、入力ファイルの体裁を整える。"""
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
    """重い段階を fake 化し、storage を tmp に向ける共通セットアップ。"""
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
    return SimpleNamespace(storage=storage, tmp=tmp_path)


def _set_cvat(monkeypatch, tmp_path) -> Path:
    """CVAT_BASE_PATH を tmp に向け、serverless ディレクトリを用意する。"""
    cvat_root = tmp_path / "cvat_root"
    serverless = cvat_root / "cvat" / "serverless"
    serverless.mkdir(parents=True)
    monkeypatch.setattr(tasks.settings, "cvat_base_path", str(cvat_root))
    monkeypatch.setattr(tasks.settings, "deploy_timeout_seconds", 60)
    return serverless


def test_full_flow_success(patched, monkeypatch, tmp_path):
    serverless = _set_cvat(monkeypatch, tmp_path)
    conn = FakeConn()
    base = tasks.job_dir("job-1")
    job_id = _seed_job(conn, base)

    calls = {}

    def runner(argv, **kwargs):
        calls["argv"] = argv
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    ret = tasks.process_job(job_id, connection=conn, deploy_runner=runner)

    rec = JobStore(conn).get(job_id)
    assert rec.status == JobStatus.SUCCESS
    assert rec.progress == 100
    assert rec.deploy_return_code == 0
    assert rec.deploy_stdout_tail == "ok"
    assert rec.deploy_script_path.endswith("deploy_cpu.sh")
    assert rec.exported_folder_path.endswith(FUNC)
    assert rec.zip_path is not None  # zip 併用
    # 実ファイルが mymodel 配下に 5 つ揃う
    exported = Path(rec.exported_folder_path)
    assert (serverless / "mymodel" / FUNC) == exported
    assert sorted(p.name for p in exported.iterdir()) == sorted(
        ["function.yaml", "function-gpu.yaml", "main.py", "model.onnx", "model_handler.py"]
    )
    assert calls["argv"] == ["./deploy_cpu.sh", f"./mymodel/{FUNC}"]
    assert ret == str(exported)


def test_gpu_target_runs_gpu_script(patched, monkeypatch, tmp_path):
    _set_cvat(monkeypatch, tmp_path)
    conn = FakeConn()
    job_id = _seed_job(conn, tasks.job_dir("job-1"), deploy_target=DeployTarget.GPU)

    calls = {}

    def runner(argv, **kwargs):
        calls["argv"] = argv
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    tasks.process_job(job_id, connection=conn, deploy_runner=runner)
    assert calls["argv"][0] == "./deploy_gpu.sh"


def test_deploy_nonzero_marks_failed(patched, monkeypatch, tmp_path):
    _set_cvat(monkeypatch, tmp_path)
    conn = FakeConn()
    job_id = _seed_job(conn, tasks.job_dir("job-1"))

    def runner(argv, **kwargs):
        return SimpleNamespace(returncode=2, stdout="", stderr="boom")

    # 終了コード != 0 は例外でなく status=failed で表現 -> 正常 return する
    tasks.process_job(job_id, connection=conn, deploy_runner=runner)

    rec = JobStore(conn).get(job_id)
    assert rec.status == JobStatus.FAILED
    assert rec.deploy_return_code == 2
    assert rec.deploy_stderr_tail == "boom"
    assert "デプロイに失敗" in rec.message


def test_deploy_script_missing_raises_and_marks_failed(patched, monkeypatch, tmp_path):
    _set_cvat(monkeypatch, tmp_path)
    conn = FakeConn()
    job_id = _seed_job(conn, tasks.job_dir("job-1"))

    def runner(argv, **kwargs):
        raise FileNotFoundError()

    from app.services.deployer import DeployError

    with pytest.raises(DeployError):
        tasks.process_job(job_id, connection=conn, deploy_runner=runner)

    rec = JobStore(conn).get(job_id)
    assert rec.status == JobStatus.FAILED
    assert "deploy_cpu.sh" in rec.message
    # 保存先までは進んでいる
    assert rec.exported_folder_path is not None


def test_skip_deploy_when_cvat_base_path_unset(patched, monkeypatch, tmp_path):
    # cvat_base_path を空に固定 (デプロイをスキップ)
    monkeypatch.setattr(tasks.settings, "cvat_base_path", "")
    conn = FakeConn()
    job_id = _seed_job(conn, tasks.job_dir("job-1"))

    called = {"runner": False}

    def runner(argv, **kwargs):
        called["runner"] = True
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    ret = tasks.process_job(job_id, connection=conn, deploy_runner=runner)

    rec = JobStore(conn).get(job_id)
    assert rec.status == JobStatus.SUCCESS
    assert rec.zip_path is not None
    assert rec.exported_folder_path is None
    assert rec.deploy_return_code is None
    assert called["runner"] is False  # deploy は実行されない
    assert ret == rec.zip_path
