"""一時ファイルの自動削除 (T-13)

生成済みファイル・アップロードファイルは永続保存せず、一定時間後に削除する (§17)。

削除方針 (§17.1):
  - 成功ジョブ (success)          : 完了から settings.ttl_success 後に削除（既定1時間）
  - 失敗ジョブ (failed / expired) : settings.ttl_failed 後に削除（既定30分）
  - 進行中 (queued/running 等)    : 削除しない
  - 残骸 (Redis に無いがディレクトリだけ残る) : ディレクトリ更新時刻を基準に削除

各ジョブについて、一時ディレクトリ (§13) と Redis キーの両方を削除する。

実行方法:
  - 単発:   python -c "from app.services.cleanup import cleanup_once; print(cleanup_once())"
  - 常駐:   python -m app.services.cleanup   (settings.cleanup_interval 間隔でループ)
  compose の cleanup サービスが後者を実行する。
"""

from __future__ import annotations

import shutil
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.config import settings
from app.jobs.queue import get_redis_connection
from app.jobs.store import JobStore
from app.schemas import JobStatus

# この状態のジョブは TTL 経過後に削除する。None のものは削除対象外（進行中）。
_TTL_BY_STATUS: dict[JobStatus, str] = {
    JobStatus.SUCCESS: "ttl_success",
    JobStatus.FAILED: "ttl_failed",
    JobStatus.EXPIRED: "ttl_failed",
}


def _jobs_root() -> Path:
    return Path(settings.storage_dir) / "jobs"


def _parse_iso(value: str) -> datetime:
    """保存済み ISO8601 文字列を aware datetime に戻す。"""
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _ttl_for(status: JobStatus) -> int | None:
    attr = _TTL_BY_STATUS.get(status)
    return getattr(settings, attr) if attr else None


def cleanup_once(connection=None, *, now: datetime | None = None) -> dict:
    """一時ディレクトリを1回走査し、期限切れジョブを削除する。

    Returns:
        {"deleted": n, "kept": n, "orphans": n} の統計。
    """
    conn = connection or get_redis_connection()
    store = JobStore(conn)
    now = now or datetime.now(timezone.utc)
    root = _jobs_root()

    stats = {"deleted": 0, "kept": 0, "orphans": 0}
    if not root.exists():
        return stats

    for job_dir in root.iterdir():
        if not job_dir.is_dir():
            continue
        job_id = job_dir.name
        record = store.get(job_id)

        # Redis に無い残骸: ディレクトリ更新時刻が古ければ削除 (§17.1)
        if record is None:
            mtime = datetime.fromtimestamp(job_dir.stat().st_mtime, tz=timezone.utc)
            if now - mtime > timedelta(seconds=settings.ttl_success):
                shutil.rmtree(job_dir, ignore_errors=True)
                stats["orphans"] += 1
            else:
                stats["kept"] += 1
            continue

        ttl = _ttl_for(record.status)
        if ttl is None:  # 進行中は残す
            stats["kept"] += 1
            continue

        age = now - _parse_iso(record.updated_at)
        if age > timedelta(seconds=ttl):
            shutil.rmtree(job_dir, ignore_errors=True)
            store.delete(job_id)
            stats["deleted"] += 1
        else:
            stats["kept"] += 1

    return stats


def run_forever(interval: int | None = None) -> None:
    """settings.cleanup_interval 間隔で cleanup_once を繰り返す常駐処理。"""
    interval = interval if interval is not None else settings.cleanup_interval
    conn = get_redis_connection()
    print(f"[cleanup] start (interval={interval}s, "
          f"ttl_success={settings.ttl_success}s, ttl_failed={settings.ttl_failed}s)")
    while True:
        try:
            stats = cleanup_once(conn)
            if stats["deleted"] or stats["orphans"]:
                print(f"[cleanup] {stats}")
        except Exception as exc:  # 掃除の失敗で常駐を止めない
            print(f"[cleanup] error: {exc}")
        time.sleep(interval)


if __name__ == "__main__":
    run_forever()
