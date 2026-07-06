"""設定 (app/config.py) の追加項目テスト — req_add02 §4/§5/§8 (ステップ1)。

CVAT_BASE_PATH / DEPLOY_TIMEOUT_SECONDS の読み込みと、
serverless / mymodel / deploy script パスを組み立てるプロパティを検証する。

依存は pydantic-settings のみ (Redis や FastAPI 等は不要)。
"""

from __future__ import annotations

from pathlib import Path

from app.config import Settings


def test_new_settings_defaults() -> None:
    """新規項目の既定値。cvat_base_path 未指定なら空 = zip のみ動作 (後方互換)。"""
    s = Settings(cvat_base_path="", deploy_timeout_seconds=600)
    assert s.cvat_base_path == ""
    assert s.deploy_timeout_seconds == 600


def test_cvat_path_properties() -> None:
    """CVAT_BASE_PATH から serverless / mymodel パスを組み立てる (§4.1/§5.1/§7)。"""
    s = Settings(cvat_base_path="/home/user/projects")
    assert s.cvat_serverless_dir == Path("/home/user/projects/cvat/serverless")
    assert s.cvat_mymodel_dir == Path("/home/user/projects/cvat/serverless/mymodel")


def test_deploy_script_path_cpu_gpu() -> None:
    """CPU/GPU に応じた deploy script パス (§8.1)。"""
    s = Settings(cvat_base_path="/home/user/projects")
    assert s.deploy_script_path("cpu") == Path(
        "/home/user/projects/cvat/serverless/deploy_cpu.sh"
    )
    assert s.deploy_script_path("gpu") == Path(
        "/home/user/projects/cvat/serverless/deploy_gpu.sh"
    )


def test_deploy_timeout_type_coercion() -> None:
    """env 由来の文字列でも int に変換される (pydantic-settings)。"""
    s = Settings(deploy_timeout_seconds="900")  # type: ignore[arg-type]
    assert s.deploy_timeout_seconds == 900
    assert isinstance(s.deploy_timeout_seconds, int)
