"""Redis 接続と RQ キュー (T-04)

web / worker の双方から使う。接続先は `config.settings` から取得する (§11.2 / §16.1)。
重い処理 (ONNX 変換・ファイル生成) は Web リクエスト内で実行せず、このキューへ
enqueue して worker が順番に処理する (§16.1 / §16.4)。
"""

from __future__ import annotations

import redis
from rq import Queue

from app.config import settings


def get_redis_connection() -> redis.Redis:
    """settings の接続情報から Redis クライアントを生成する。"""
    return redis.Redis.from_url(settings.redis_url)


def get_queue(connection: redis.Redis | None = None) -> Queue:
    """ジョブ投入用の RQ キューを返す。

    connection を渡さなければ settings から生成する。テストでは fakeredis 等の
    互換コネクションを渡せる。
    """
    conn = connection or get_redis_connection()
    return Queue(settings.rq_queue_name, connection=conn)
