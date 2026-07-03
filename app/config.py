"""アプリケーション設定 (T-02)

`.env` / 環境変数から値を読み込み、アプリ全体で共有する。
ユーザーに入力させない固定値・既定値 (§6 / §14) や、パス・上限・TTL・
Redis 接続情報などをここで一元管理する。

変数名は `.env.example` と一致させている。
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """環境変数で上書き可能な設定。すべて既定値を持つので .env が無くても起動する。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- サーバ (§3.2) ---
    app_host: str = "0.0.0.0"
    app_port: int = 8000

    # --- ストレージ (web / worker 共有 volume §11.4 / §13) ---
    storage_dir: str = "/storage"

    # --- Redis (§11.2 / §16) ---
    redis_host: str = "redis"
    redis_port: int = 6379
    redis_db: int = 0
    rq_queue_name: str = "jobs"

    # --- アップロード上限 (バイト) (§14.3 / §14.4 / §20.4) ---
    max_svg_size: int = 5 * 1024 * 1024        # 5 MB
    max_pt_size: int = 500 * 1024 * 1024       # 500 MB

    # --- 一時ファイル TTL (秒) (§17.1) ---
    ttl_success: int = 3600                    # 成功: 1 時間
    ttl_failed: int = 1800                     # 失敗: 30 分

    # --- ONNX 変換の既定値 (§6 / §10.4) ---
    onnx_opset: int = 12
    image_size: int = 640
    # end2end NMS を埋め込む。model_handler.py が NMS 適用済み形式を前提とするため True。
    onnx_nms: bool = True

    # --- 推論パラメータ既定値 (テンプレートに埋め込む §6) ---
    conf_threshold: float = 0.25
    iou_threshold: float = 0.45

    @property
    def redis_url(self) -> str:
        """RQ / redis クライアント用の接続 URL。"""
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"


@lru_cache
def get_settings() -> Settings:
    """設定シングルトン。プロセス内で 1 度だけ読み込む。"""
    return Settings()


# 利便性のためのモジュールレベル参照
settings = get_settings()
