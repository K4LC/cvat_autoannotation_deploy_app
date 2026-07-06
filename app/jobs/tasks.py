"""Worker タスク (T-09)

RQ の worker が実行する重い処理 (§11.2 / §16.1)。ジョブの状態を JobStore 経由で
段階的に更新しながら (§F-07)、以下を順に実行する:

    parsing_svg      -> SVG 解析 (svg_parser)
    exporting_onnx   -> .pt を model.onnx へ変換 (onnx_export)
    generating_files -> function.yaml / main.py / model_handler.py 生成 (generator)
    creating_zip     -> cvat-yolo-<internal>.zip 作成 (packager, 併用のため維持)
    saving_to_cvat   -> serverless/mymodel 配下へ保存 (deployer, CVAT_BASE_PATH 設定時)
    deploying        -> deploy_{cpu,gpu}.sh 実行 (deployer, req_add02 §8)
    success          -> 完了

いずれかの段階で失敗したら failed に更新し、エラーメッセージを保存する (F-15)。
deploy の終了コード != 0 も failed とし、ログ tail 等を保存する (§9.3/§9.4)。
CVAT_BASE_PATH 未設定時は saving_to_cvat 以降をスキップし zip のみで完了する。

一時ディレクトリ構成 (§13 / req_add02 §9.5):
    <storage>/jobs/<job_id>/
    ├── input/{model.pt, model.svg}
    ├── output/<function_name>/{function.yaml, function-gpu.yaml, main.py, model.onnx, model_handler.py}
    ├── logs/{deploy_stdout.log, deploy_stderr.log, deploy_result.json}
    └── cvat-yolo-<function_name>.zip

テスト用に redis 接続と ONNX ローダを注入できる（本番呼び出しは process_job(job_id) のみ）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from app.config import settings
from app.jobs.queue import get_redis_connection
from app.jobs.store import JobStore
from app.schemas import JobStatus
from app.services.deployer import (
    DeployError,
    result_to_fields,
    run_deploy,
    save_to_cvat,
)
from app.services.generator import build_context, render_all
from app.services.onnx_export import OnnxExportError, export_to_onnx
from app.services.packager import PackagingError, build_zip, zip_filename
from app.services.svg_parser import SvgParseError, parse_svg


def job_dir(job_id: str) -> Path:
    """ジョブの一時ディレクトリ (§13)。"""
    return Path(settings.storage_dir) / "jobs" / job_id


def process_job(
    job_id: str,
    *,
    connection=None,
    onnx_model_factory: Callable[[str], object] | None = None,
    deploy_runner: Callable[..., object] | None = None,
) -> str:
    """1 ジョブを処理する。

    生成 (SVG解析→ONNX変換→ファイル生成→zip) の後、`CVAT_BASE_PATH` が設定されて
    いれば CVAT の serverless/mymodel 配下へ保存し、deploy script を実行する
    (req_add02 §7〜§9)。未設定なら zip のみ生成して完了する（後方互換）。

    Args:
        job_id: 対象ジョブ ID。
        connection: redis 接続（省略時は settings から生成）。
        onnx_model_factory: ONNX 変換の YOLO ローダ差し替え（テスト用）。
        deploy_runner: deploy script 実行の subprocess ランナー差し替え（テスト用）。

    Returns:
        保存先フォルダ（デプロイ時）または zip のパス文字列。

    Raises:
        処理失敗時は例外を送出する（送出前に status=failed を保存済み）。
        ただしデプロイの終了コード != 0 は例外でなく status=failed で表現し正常 return する。
    """
    conn = connection or get_redis_connection()
    store = JobStore(conn)

    record = store.get(job_id)
    if record is None:
        raise ValueError(f"ジョブが見つかりません: {job_id}")

    base = job_dir(job_id)
    output_dir = base / "output" / record.function_name
    zip_path = base / zip_filename(record.function_name)

    try:
        store.set_status(job_id, JobStatus.RUNNING, progress=5, message="処理を開始しました")

        # 1) SVG 解析
        store.set_status(job_id, JobStatus.PARSING_SVG, progress=15, message="SVG解析中")
        parsed = parse_svg(record.svg_path)

        # 2) ONNX 変換
        store.set_status(job_id, JobStatus.EXPORTING_ONNX, progress=40, message="ONNX変換中")
        export_to_onnx(record.pt_path, output_dir, model_factory=onnx_model_factory)

        # 3) テンプレートファイル生成
        store.set_status(job_id, JobStatus.GENERATING_FILES, progress=70, message="ファイル生成中")
        context = build_context(
            author=record.author,
            display_name=record.display_name,
            function_name=record.function_name,
            svg_label=record.svg_label,
            parsed=parsed,
        )
        render_all(output_dir, context)

        # 4) zip 作成 (併用のため維持 req_add02 §18.6)
        store.set_status(job_id, JobStatus.CREATING_ZIP, progress=85, message="zip作成中")
        build_zip(output_dir, zip_path, internal_name=record.function_name)

        # CVAT_BASE_PATH 未設定なら CVAT 保存 + 自動デプロイをスキップし zip のみで完了
        # (後方互換)。
        if not settings.cvat_base_path:
            store.set_status(
                job_id,
                JobStatus.SUCCESS,
                progress=100,
                message="完了",
                zip_path=str(zip_path),
            )
            return str(zip_path)

        # 5) CVAT serverless/mymodel 配下へ保存 (req_add02 §7)
        store.set_status(
            job_id,
            JobStatus.SAVING_TO_CVAT,
            progress=90,
            message="CVATへ保存中",
            zip_path=str(zip_path),
        )
        exported = save_to_cvat(
            output_dir, record.function_name, settings.cvat_mymodel_dir
        )

        # 6) deploy script 実行 (req_add02 §8)
        store.set_status(
            job_id,
            JobStatus.DEPLOYING,
            progress=95,
            message="デプロイ中",
            exported_folder_path=str(exported),
        )
        result = run_deploy(
            target=record.deploy_target.value,
            exported_folder=exported,
            serverless_dir=settings.cvat_serverless_dir,
            log_dir=base / "logs",
            timeout=settings.deploy_timeout_seconds,
            **({"runner": deploy_runner} if deploy_runner is not None else {}),
        )
        deploy_fields = result_to_fields(result)

        # 7) 成否判定 (§9.2 / §9.3): 終了コード 0 で成功、それ以外は failed。
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

    except DeployError as exc:
        # CVAT 保存 / deploy 実行の既知失敗 (script不在・権限・タイムアウト等 §9.6/§9.7)。
        # 可能なら得られたログ情報も保存する。
        fields = result_to_fields(exc.result) if exc.result is not None else {}
        store.set_status(
            job_id, JobStatus.FAILED, message=str(exc), error=str(exc), **fields
        )
        raise
    except (SvgParseError, OnnxExportError, PackagingError) as exc:
        # ユーザー向けメッセージが明確な既知の失敗
        store.set_status(job_id, JobStatus.FAILED, message=str(exc), error=str(exc))
        raise
    except Exception as exc:
        # 想定外の失敗
        store.set_status(
            job_id,
            JobStatus.FAILED,
            message="処理中にエラーが発生しました",
            error=str(exc),
        )
        raise
