"""ジョブ状態ストア (T-04)

ジョブの状態・進捗・パス・ダウンロードトークンなどを Redis に保存/取得する
(§16.2 / §16.3)。キーは `job:<job_id>`。値は JobRecord を JSON 化して格納する。

同時利用時はジョブごとに一意の job_id で分離されるため、キーが衝突しない (§16.3)。
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone

from app.schemas import JobRecord, JobStatus

JOB_KEY_PREFIX = "job:"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobStore:
    """Redis 上のジョブレコードを読み書きする薄いラッパ。

    connection は redis.Redis 互換であればよい（テストでは fakeredis を渡せる）。
    """

    def __init__(self, connection) -> None:
        self.conn = connection

    @staticmethod
    def key(job_id: str) -> str:
        return f"{JOB_KEY_PREFIX}{job_id}"

    @staticmethod
    def generate_token() -> str:
        """ダウンロード用トークンを発行する (§20.4 / F-14)。"""
        return secrets.token_urlsafe(32)

    def save(self, record: JobRecord, ttl: int | None = None) -> JobRecord:
        """レコードを保存する。updated_at を現在時刻へ更新する。

        ttl (秒) を渡すと Redis キーに有効期限を設定する (§17.1)。
        """
        record.updated_at = _now_iso()
        data = record.model_dump_json()
        key = self.key(record.job_id)
        if ttl is not None:
            self.conn.set(key, data, ex=ttl)
        else:
            self.conn.set(key, data)
        return record

    def get(self, job_id: str) -> JobRecord | None:
        """レコードを取得する。存在しなければ None。"""
        raw = self.conn.get(self.key(job_id))
        if raw is None:
            return None
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8")
        return JobRecord.model_validate_json(raw)

    def set_status(
        self,
        job_id: str,
        status: JobStatus,
        progress: int | None = None,
        message: str | None = None,
        **fields,
    ) -> JobRecord | None:
        """状態(と任意で進捗・メッセージ・追加フィールド)を更新する。

        worker が処理段階ごとに呼ぶ (§F-07 の状態遷移)。存在しなければ None。
        追加フィールド例: zip_path, error 等。
        """
        record = self.get(job_id)
        if record is None:
            return None
        record.status = status
        if progress is not None:
            record.progress = progress
        if message is not None:
            record.message = message
        for name, value in fields.items():
            setattr(record, name, value)
        return self.save(record)

    def exists(self, job_id: str) -> bool:
        return bool(self.conn.exists(self.key(job_id)))

    def delete(self, job_id: str) -> None:
        """ジョブレコードを削除する (§17 一時ファイル管理と併用)。"""
        self.conn.delete(self.key(job_id))
