"""データモデル定義 (T-02)

- ジョブの状態 enum (§F-07 の 9 状態)
- Redis に保存するジョブレコード (§16.2 / F-06)
- API のレスポンスモデル (§19)

SVG 解析結果 (ParsedSvg) は T-05 (svg_parser) で定義する。
"""

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


def _now_iso() -> str:
    """JST でなく UTC の ISO8601 文字列。表示側で必要に応じ変換する。"""
    return datetime.now(timezone.utc).isoformat()


class JobStatus(str, Enum):
    """ジョブの状態。要件 §F-07 に定義された 9 状態。"""

    QUEUED = "queued"
    RUNNING = "running"
    PARSING_SVG = "parsing_svg"
    EXPORTING_ONNX = "exporting_onnx"
    GENERATING_FILES = "generating_files"
    CREATING_ZIP = "creating_zip"
    SUCCESS = "success"
    FAILED = "failed"
    EXPIRED = "expired"


# 状態 -> 画面表示ラベル (§F-07 画面表示例)
STATUS_LABELS_JA: dict[JobStatus, str] = {
    JobStatus.QUEUED: "待機中",
    JobStatus.RUNNING: "実行中",
    JobStatus.PARSING_SVG: "SVG解析中",
    JobStatus.EXPORTING_ONNX: "ONNX変換中",
    JobStatus.GENERATING_FILES: "ファイル生成中",
    JobStatus.CREATING_ZIP: "zip作成中",
    JobStatus.SUCCESS: "完了",
    JobStatus.FAILED: "失敗",
    JobStatus.EXPIRED: "期限切れ",
}


class JobRecord(BaseModel):
    """Redis に保存するジョブの全情報 (§16.2 / F-06)。

    keypoints / skeleton は骨格推定固有の情報 (§7.2)。SVG 解析仕様が未確定のため
    ゆるく型付けし、後で具体化する。
    """

    job_id: str
    status: JobStatus = JobStatus.QUEUED
    progress: int = 0
    message: str = ""

    # ユーザー入力 (§6)
    author: str
    display_name: str

    # SVG から取得 (§7)
    function_name: str                       # 正規化済みモデル内部名
    labels: list[str] = Field(default_factory=list)
    keypoints: list[str] | None = None
    skeleton: list[list[int]] | None = None  # keypoint index のペア列 (暫定表現)

    # ファイルパス (§13)
    pt_path: str
    svg_path: str
    zip_path: str | None = None

    # 配布制御 (§F-14 / §20.4)
    download_token: str

    # エラー情報 (§F-15)
    error: str | None = None

    # タイムスタンプ (§16.2)
    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)


class JobCreateResponse(BaseModel):
    """POST /jobs の成功レスポンス (§19.2)。"""

    job_id: str
    status: JobStatus
    status_url: str


class JobStatusResponse(BaseModel):
    """GET /jobs/{job_id} のレスポンス (§19.3 / F-07)。"""

    job_id: str
    status: JobStatus
    progress: int
    message: str
    label_ja: str = ""          # 画面表示用の日本語ラベル
    error: str | None = None
    download_url: str | None = None  # success 時のみ設定 (§F-14)
