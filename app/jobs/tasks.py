"""Worker タスク (T-09)

RQ の worker が実行する重い処理 (§11.2 / §16.1)。ジョブの状態を JobStore 経由で
段階的に更新しながら (§F-07)、以下を順に実行する:

    parsing_svg      -> SVG 解析 (svg_parser)
    exporting_onnx   -> .pt を model.onnx へ変換 (onnx_export)
    generating_files -> function.yaml / main.py / model_handler.py 生成 (generator)
    creating_zip     -> cvat-yolo-<internal>.zip 作成 (packager, 併用のため維持)
    saving_to_cvat   -> serverless/mymodel 配下へ保存 (deployer, CVAT_BASE_PATH 設定時)
    deploying        -> deploy キューへ委譲 (WSL ホストの deploy ワーカーが sh 実行 §8)
    success          -> 完了 (deploy ワーカーが最終判定)

いずれかの段階で失敗したら failed に更新し、エラーメッセージを保存する (F-15)。
deploy script の実行は docker/nuctl を要するため WSL ホスト側の deploy ワーカー
(app/jobs/deploy_tasks.py) が担当し、成否 (§9.2/§9.3) を Redis に書き戻す。
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

import shutil
from pathlib import Path
from typing import Callable

from app.config import settings
from app.jobs.queue import get_queue, get_redis_connection
from app.jobs.store import JobStore
from app.schemas import JobStatus, ModelType
from app.services.deployer import DeployError, save_to_cvat
from app.services.generator import build_context, render_all
from app.services.onnx_export import OnnxExportError, export_to_onnx
from app.services.packager import (
    DLC_CONFIG_NAME,
    DLC_PT_NAME,
    PackagingError,
    build_zip,
    expected_files,
    zip_filename,
)
from app.services.svg_parser import SvgParseError, parse_svg


def job_dir(job_id: str) -> Path:
    """ジョブの一時ディレクトリ (§13)。"""
    return Path(settings.storage_dir) / "jobs" / job_id


def _prepare_dlc_model(record, output_dir: Path) -> None:
    """DLC は ONNX 変換せず、アップロード済み .pt と pytorch_config を同梱する。

    nuclio 関数内で DLC(PyTorch) が直接推論するため、snapshot(.pt) と
    pytorch_config.yaml を出力フォルダへコピーする（固定名）。
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    pt_src = Path(record.pt_path)
    if not pt_src.is_file():
        raise OnnxExportError(f"入力の.ptファイルが見つかりません: {pt_src}")
    if not record.dlc_config_path or not Path(record.dlc_config_path).is_file():
        raise OnnxExportError(
            "DLCモデルには pytorch_config.yaml が必要ですが見つかりません"
        )

    shutil.copy2(pt_src, output_dir / DLC_PT_NAME)
    shutil.copy2(Path(record.dlc_config_path), output_dir / DLC_CONFIG_NAME)


def process_job(
    job_id: str,
    *,
    connection=None,
    onnx_model_factory: Callable[[str], object] | None = None,
) -> str:
    """1 ジョブを処理する。

    生成 (SVG解析→ONNX変換→ファイル生成→zip) の後、`CVAT_BASE_PATH` が設定されて
    いれば CVAT の serverless/mymodel 配下へ保存し、deploy を `deploy` キューへ委譲
    する (req_add02 §7〜§9)。未設定なら zip のみ生成して完了する（後方互換）。
    実際の deploy script 実行は WSL ホスト側の deploy ワーカーが行う。

    Args:
        job_id: 対象ジョブ ID。
        connection: redis 接続（省略時は settings から生成）。
        onnx_model_factory: ONNX 変換の YOLO ローダ差し替え（テスト用）。

    Returns:
        保存先フォルダ（デプロイ時）または zip のパス文字列。

    Raises:
        処理失敗時は例外を送出する（送出前に status=failed を保存済み）。
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

        # 2) モデル準備。YOLO は ONNX 変換、DLC は .pt+config をそのまま同梱する。
        if record.model_type is ModelType.DLC:
            store.set_status(
                job_id, JobStatus.EXPORTING_ONNX, progress=40, message="モデル準備中"
            )
            _prepare_dlc_model(record, output_dir)
        else:
            store.set_status(
                job_id, JobStatus.EXPORTING_ONNX, progress=40, message="ONNX変換中"
            )
            export_to_onnx(record.pt_path, output_dir, model_factory=onnx_model_factory)

        # 3) テンプレートファイル生成 (モデル種別でテンプレート集合を切替)
        store.set_status(job_id, JobStatus.GENERATING_FILES, progress=70, message="ファイル生成中")
        context = build_context(
            author=record.author,
            display_name=record.display_name,
            function_name=record.function_name,
            svg_label=record.svg_label,
            parsed=parsed,
        )
        render_all(output_dir, context, model_type=record.model_type)

        files = expected_files(record.model_type)

        # 4) zip 作成 (併用のため維持 req_add02 §18.6)
        store.set_status(job_id, JobStatus.CREATING_ZIP, progress=85, message="zip作成中")
        build_zip(output_dir, zip_path, internal_name=record.function_name, files=files)

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
            output_dir, record.function_name, settings.cvat_mymodel_dir, files=files
        )

        # 6) deploy は docker/nuctl を要するため、WSL ホスト側の deploy ワーカーへ委譲する
        #    (別キュー: settings.deploy_queue_name)。ここでは enqueue して待機状態にするだけ
        #    (req_add02 §8 / deploy 分離)。
        store.set_status(
            job_id,
            JobStatus.DEPLOYING,
            progress=95,
            message="デプロイ待機中（deployワーカーの起動が必要です）",
            exported_folder_path=str(exported),
        )
        deploy_queue = get_queue(connection=conn, name=settings.deploy_queue_name)
        deploy_queue.enqueue("app.jobs.deploy_tasks.run_deploy_job", job_id)
        return str(exported)

    except DeployError as exc:
        # CVAT 保存の既知失敗 (必須ファイル不足など)。deploy 実行自体は別ワーカーが担う。
        store.set_status(job_id, JobStatus.FAILED, message=str(exc), error=str(exc))
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
