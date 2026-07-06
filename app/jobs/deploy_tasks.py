"""deploy 専用ワーカータスク (req_add02 §8 / WSL ホスト側で実行)

`deploy_{cpu,gpu}.sh` は内部で `docker build` と `nuctl deploy` を呼ぶため、
docker/nuctl バイナリのある **WSL ホスト**で動く軽量ワーカーが処理する。
Docker の worker (`app/jobs/tasks.py`) は生成〜mymodel 保存までを行い、
このタスクを `deploy` キューへ enqueue する。

このモジュールは torch / jinja2 / fastapi を import しないこと。ホストの軽量な
venv (redis / rq / pydantic / pydantic-settings のみ) で動かせるようにするため、
依存は store / schemas / config / services.deployer に限定する。
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from app.config import settings
from app.jobs.queue import get_redis_connection
from app.jobs.store import JobStore
from app.schemas import JobStatus
from app.services.deployer import DeployError, result_to_fields, run_deploy


def run_deploy_job(
    job_id: str,
    *,
    connection=None,
    runner: Callable[..., object] | None = None,
) -> str:
    """1 ジョブ分の deploy script を実行し、結果を Redis に書き戻す。

    Docker worker が mymodel へ保存し status=DEPLOYING にした後に enqueue される。
    終了コード 0 で SUCCESS、それ以外は FAILED。script 不在/権限/タイムアウト等の
    DeployError も FAILED とし、可能なら得られたログ tail を保存する (§9.3/§9.4)。

    Args:
        job_id: 対象ジョブ ID。
        connection: redis 接続（省略時は settings から生成）。
        runner: subprocess ランナー差し替え（テスト用）。

    Returns:
        保存先フォルダのパス文字列。

    Raises:
        DeployError: script 実行に失敗した場合（送出前に status=failed を保存済み）。
        ValueError: ジョブが見つからない / 保存先が未設定の場合。
    """
    conn = connection or get_redis_connection()
    store = JobStore(conn)

    record = store.get(job_id)
    if record is None:
        raise ValueError(f"ジョブが見つかりません: {job_id}")
    if not record.exported_folder_path:
        raise ValueError(f"保存先フォルダが未設定です: {job_id}")

    exported = Path(record.exported_folder_path)
    log_dir = Path(settings.storage_dir) / "jobs" / job_id / "logs"

    try:
        result = run_deploy(
            target=record.deploy_target.value,
            exported_folder=exported,
            serverless_dir=settings.cvat_serverless_dir,
            log_dir=log_dir,
            timeout=settings.deploy_timeout_seconds,
            **({"runner": runner} if runner is not None else {}),
        )
    except DeployError as exc:
        fields = result_to_fields(exc.result) if exc.result is not None else {}
        store.set_status(
            job_id, JobStatus.FAILED, message=str(exc), error=str(exc), **fields
        )
        raise

    deploy_fields = result_to_fields(result)
    if result.return_code == 0:
        store.set_status(
            job_id,
            JobStatus.SUCCESS,
            progress=100,
            message="生成とデプロイが完了しました",
            **deploy_fields,
        )
    else:
        store.set_status(
            job_id,
            JobStatus.FAILED,
            message="デプロイに失敗しました。deploy scriptのログを確認してください",
            error=f"deploy script が終了コード {result.return_code} で失敗しました",
            **deploy_fields,
        )
    return str(exported)
