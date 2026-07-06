"""データモデル (app/schemas.py) の追加項目テスト — req_add02 §11/§12/§15 (ステップ2)。

- JobStatus に saving_to_cvat / deploying を追加したこと
- DeployTarget enum
- JobRecord の新フィールドと JSON ラウンドトリップ (JobStore は model_dump_json/
  model_validate_json で Redis に保存するため、往復で失われないことが重要)
- JobStatusResponse の新フィールド

依存は pydantic のみ。
"""

from __future__ import annotations

from app.schemas import (
    STATUS_LABELS_JA,
    DeployTarget,
    JobRecord,
    JobStatus,
    JobStatusResponse,
)


def _minimal_record(**overrides) -> JobRecord:
    base = dict(
        job_id="job-1",
        author="作者",
        display_name="Human Pose",
        svg_label="person",
        function_name="human-pose-202607061530",
        pt_path="/storage/jobs/job-1/input/model.pt",
        svg_path="/storage/jobs/job-1/input/model.svg",
        download_token="tok",
    )
    base.update(overrides)
    return JobRecord(**base)


def test_new_statuses_exist() -> None:
    assert JobStatus.SAVING_TO_CVAT.value == "saving_to_cvat"
    assert JobStatus.DEPLOYING.value == "deploying"


def test_status_labels_cover_all_statuses() -> None:
    """全 JobStatus に日本語ラベルがある (新状態を足したら必ずラベルも足す不変条件)。"""
    assert set(STATUS_LABELS_JA) == set(JobStatus)
    assert STATUS_LABELS_JA[JobStatus.SAVING_TO_CVAT] == "CVATへ保存中"
    assert STATUS_LABELS_JA[JobStatus.DEPLOYING] == "デプロイ中"


def test_deploy_target_enum() -> None:
    assert DeployTarget.CPU.value == "cpu"
    assert DeployTarget.GPU.value == "gpu"


def test_job_record_new_field_defaults() -> None:
    r = _minimal_record()
    assert r.deploy_target == DeployTarget.CPU
    assert r.cvat_base_path == ""
    assert r.deploy_script_path is None
    assert r.exported_folder_path is None
    assert r.deploy_return_code is None
    assert r.deploy_stdout_tail == ""
    assert r.deploy_stderr_tail == ""
    assert r.deploy_stdout_log_path is None
    assert r.deploy_stderr_log_path is None
    assert r.deploy_result_path is None
    # zip_path は併用のため維持
    assert r.zip_path is None


def test_job_record_json_roundtrip_preserves_deploy_fields() -> None:
    """Redis 保存を模した JSON 往復で新フィールドが保持されること。"""
    r = _minimal_record(
        deploy_target=DeployTarget.GPU,
        cvat_base_path="/home/user/projects",
        deploy_script_path="/home/user/projects/cvat/serverless/deploy_gpu.sh",
        exported_folder_path="/home/user/projects/cvat/serverless/mymodel/human-pose-202607061530",
        deploy_return_code=1,
        deploy_stdout_tail="out",
        deploy_stderr_tail="err",
    )
    restored = JobRecord.model_validate_json(r.model_dump_json())
    assert restored.deploy_target == DeployTarget.GPU
    assert restored.cvat_base_path == "/home/user/projects"
    assert restored.deploy_script_path.endswith("deploy_gpu.sh")
    assert restored.exported_folder_path.endswith("human-pose-202607061530")
    assert restored.deploy_return_code == 1
    assert restored.deploy_stdout_tail == "out"
    assert restored.deploy_stderr_tail == "err"


def test_status_response_new_field_defaults() -> None:
    resp = JobStatusResponse(
        job_id="job-1", status=JobStatus.DEPLOYING, progress=96, message="デプロイ中"
    )
    assert resp.deploy_target is None
    assert resp.exported_folder_path is None
    assert resp.deploy_script_path is None
    assert resp.deploy_return_code is None
    assert resp.deploy_stdout_tail == ""
    assert resp.deploy_stderr_tail == ""
