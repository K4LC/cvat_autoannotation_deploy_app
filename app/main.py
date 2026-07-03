"""FastAPI アプリ本体 / ルーティング (T-10)

エンドポイント (§19):
  GET  /                    トップ(入力フォーム)画面
  POST /jobs                入力受付・検証・SVG解析・ジョブ登録・enqueue
  GET  /jobs/{job_id}       ジョブ状態(進捗)取得
  GET  /download/{job_id}   token 照合のうえ生成 zip を返す

セキュリティ (§14 / §20.4):
  - アップロードは拡張子(.svg/.pt)とサイズ上限を検証
  - job_id は UUID、保存名は固定(model.svg/model.pt)でユーザー入力をパスに使わない(§17.3)
  - download は download_token を照合
  - SVG 解析は defusedxml(svg_parser 側)で XXE 等を回避

重い処理(ONNX変換・生成・zip)は行わず、RQ へ enqueue して worker に委譲する(§20.3)。
"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from rq import Queue

from app.config import settings
from app.jobs.queue import get_queue, get_redis_connection
from app.jobs.store import JobStore
from app.jobs.tasks import job_dir, process_job
from app.schemas import (
    STATUS_LABELS_JA,
    JobCreateResponse,
    JobRecord,
    JobStatus,
    JobStatusResponse,
)
from app.services.naming import InvalidNameError, normalize_internal_name
from app.services.packager import zip_filename
from app.services.svg_parser import SvgParseError, parse_svg

APP_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = APP_DIR / "templates_web"
STATIC_DIR = APP_DIR / "static"

# アップロード保存時の固定ファイル名 (§F-03 / F-04 / §17.3)
SVG_FILENAME = "model.svg"
PT_FILENAME = "model.pt"

UPLOAD_CHUNK = 1024 * 1024  # 1MB

app = FastAPI(title="CVAT Pose Deploy File Generator")

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# --- 依存性 (テストで override 可能) ---
def get_connection():
    return get_redis_connection()


def get_store(conn=Depends(get_connection)) -> JobStore:
    return JobStore(conn)


def get_job_queue(conn=Depends(get_connection)) -> Queue:
    return get_queue(conn)


# --- ヘルパ ---
async def _save_upload(upload: UploadFile, dest: Path, max_size: int) -> int:
    """アップロードをチャンク保存し、サイズ上限を超えたら中断して例外を送出する。"""
    total = 0
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "wb") as f:
        while True:
            chunk = await upload.read(UPLOAD_CHUNK)
            if not chunk:
                break
            total += len(chunk)
            if total > max_size:
                f.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=413,
                    detail=f"ファイルサイズが上限({max_size}バイト)を超えています",
                )
            f.write(chunk)
    return total


def _check_extension(upload: UploadFile, ext: str) -> None:
    name = (upload.filename or "").lower()
    if not name.endswith(ext):
        raise HTTPException(status_code=400, detail=f"{ext} ファイルのみアップロード可能です")


def _download_url(record: JobRecord) -> str:
    return f"/download/{record.job_id}?token={record.download_token}"


# --- ルート ---
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """トップ(入力フォーム)画面 (§19.1 / §18.1)。"""
    return templates.TemplateResponse(request, "index.html")


@app.post("/jobs", response_model=JobCreateResponse)
async def create_job(
    author: str = Form(...),
    display_name: str = Form(...),
    svg: UploadFile = File(...),
    pt: UploadFile = File(...),
    store: JobStore = Depends(get_store),
    queue: Queue = Depends(get_job_queue),
):
    """入力を検証し、ジョブを作成して enqueue する (§19.2 / F-02〜F-06)。"""
    # 1) テキスト入力の検証 (§14.1 / §14.2)
    author = (author or "").strip()
    display_name = (display_name or "").strip()
    if not author:
        raise HTTPException(status_code=400, detail="作成者名を入力してください")
    if not display_name:
        raise HTTPException(status_code=400, detail="モデル表示名を入力してください")

    # 2) 拡張子の検証 (§14.3 / §14.4)
    _check_extension(svg, ".svg")
    _check_extension(pt, ".pt")

    # 3) モデル内部名を表示名から算出 (確定した設計判断)
    try:
        function_name = normalize_internal_name(display_name)
    except InvalidNameError:
        raise HTTPException(
            status_code=400,
            detail="モデル表示名から有効な内部名を作成できません（英数字を含めてください）",
        )

    # 4) job_id 発行・アップロード保存 (§F-03 / F-04 / §13)
    job_id = str(uuid.uuid4())
    base = job_dir(job_id)
    svg_path = base / "input" / SVG_FILENAME
    pt_path = base / "input" / PT_FILENAME
    try:
        await _save_upload(svg, svg_path, settings.max_svg_size)
        await _save_upload(pt, pt_path, settings.max_pt_size)

        # 5) SVG 解析(検証)。失敗ならジョブを作らずエラー (§F-05 / AC-03)
        try:
            parsed = parse_svg(svg_path)
        except SvgParseError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
    except HTTPException:
        shutil.rmtree(base, ignore_errors=True)
        raise

    # 6) ジョブ登録 (§F-06 / §16.2)
    record = JobRecord(
        job_id=job_id,
        status=JobStatus.QUEUED,
        author=author,
        display_name=display_name,
        function_name=function_name,
        labels=parsed.labels,
        keypoints=parsed.keypoints,
        skeleton=parsed.skeleton,
        pt_path=str(pt_path),
        svg_path=str(svg_path),
        download_token=JobStore.generate_token(),
        message=STATUS_LABELS_JA[JobStatus.QUEUED],
    )
    store.save(record)

    # 7) enqueue (§16.1)
    queue.enqueue(process_job, job_id)

    return JobCreateResponse(
        job_id=job_id,
        status=JobStatus.QUEUED,
        status_url=f"/jobs/{job_id}",
    )


@app.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job(job_id: str, store: JobStore = Depends(get_store)):
    """ジョブの現在状態を返す (§19.3 / F-07)。"""
    record = store.get(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="ジョブが見つかりません")

    return JobStatusResponse(
        job_id=record.job_id,
        status=record.status,
        progress=record.progress,
        message=record.message,
        label_ja=STATUS_LABELS_JA.get(record.status, ""),
        error=record.error,
        download_url=_download_url(record) if record.status == JobStatus.SUCCESS else None,
    )


@app.get("/download/{job_id}")
async def download(job_id: str, token: str = "", store: JobStore = Depends(get_store)):
    """token 照合のうえ生成 zip を返す (§19.4 / F-14)。"""
    record = store.get(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="ジョブが見つかりません")
    if not token or token != record.download_token:
        raise HTTPException(status_code=403, detail="ダウンロード権限がありません")
    if record.status != JobStatus.SUCCESS or not record.zip_path:
        raise HTTPException(status_code=409, detail="まだダウンロードできません")

    zip_path = Path(record.zip_path)
    if not zip_path.is_file():
        raise HTTPException(status_code=404, detail="生成ファイルが見つかりません")

    return FileResponse(
        path=str(zip_path),
        media_type="application/zip",
        filename=zip_filename(record.function_name),
    )
