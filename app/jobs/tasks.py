"""Worker タスク (T-09)

RQ の worker が実行する重い処理 (§11.2 / §16.1)。ジョブの状態を JobStore 経由で
段階的に更新しながら (§F-07)、以下を順に実行する:

    parsing_svg      -> SVG 解析 (svg_parser)
    exporting_onnx   -> .pt を model.onnx へ変換 (onnx_export)
    generating_files -> function.yaml / main.py / model_handler.py 生成 (generator)
    creating_zip     -> cvat-yolo-<internal>.zip 作成 (packager)
    success          -> 完了 (zip_path を保存)

いずれかの段階で失敗したら failed に更新し、エラーメッセージを保存する (F-15)。

一時ディレクトリ構成 (§13):
    <storage>/jobs/<job_id>/
    ├── input/{model.pt, model.svg}
    ├── output/<function_name>/{function.yaml, main.py, model.onnx, model_handler.py}
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
) -> str:
    """1 ジョブを処理して zip を生成する。

    Args:
        job_id: 対象ジョブ ID。
        connection: redis 接続（省略時は settings から生成）。
        onnx_model_factory: ONNX 変換の YOLO ローダ差し替え（テスト用）。

    Returns:
        生成した zip のパス文字列。

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

        # 2) ONNX 変換
        store.set_status(job_id, JobStatus.EXPORTING_ONNX, progress=40, message="ONNX変換中")
        export_to_onnx(record.pt_path, output_dir, model_factory=onnx_model_factory)

        # 3) テンプレートファイル生成
        store.set_status(job_id, JobStatus.GENERATING_FILES, progress=70, message="ファイル生成中")
        context = build_context(
            author=record.author,
            display_name=record.display_name,
            function_name=record.function_name,
            parsed=parsed,
        )
        render_all(output_dir, context)

        # 4) zip 作成
        store.set_status(job_id, JobStatus.CREATING_ZIP, progress=90, message="zip作成中")
        build_zip(output_dir, zip_path, internal_name=record.function_name)

        # 5) 完了
        store.set_status(
            job_id,
            JobStatus.SUCCESS,
            progress=100,
            message="完了",
            zip_path=str(zip_path),
        )
        return str(zip_path)

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
