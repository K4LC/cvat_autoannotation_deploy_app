"""アプリケーション設定 (T-02)

`.env` / 環境変数から値を読み込み、アプリ全体で共有する。
ユーザーに入力させない固定値・既定値 (§6 / §14) や、パス・上限・TTL・
Redis 接続情報などをここで一元管理する。

変数名は `.env.example` と一致させている。
"""

from functools import lru_cache
from pathlib import Path

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
    cleanup_interval: int = 300                # 掃除の実行間隔: 5 分

    # --- ONNX 変換の既定値 (§6 / §10.4) ---
    onnx_opset: int = 12
    image_size: int = 640
    # end2end NMS は埋め込まない（False=生出力 (1,4+1+kpt*3,N)）。
    # model_handler.py 側で NMS とキーポイント復元を行う。nms=True はモデルにより
    # キーポイントを落とす (1,300,6) ことがあり不安定なため False を既定とする。
    onnx_nms: bool = False

    # --- 推論パラメータ既定値 (テンプレートに埋め込む §6) ---
    conf_threshold: float = 0.25
    iou_threshold: float = 0.45

    # --- CVAT serverless 配下への保存 / 自動デプロイ (req_add02 §4/§5/§8) ---
    # サーバ内かつ Docker コンテナ外のホスト側 CVAT ルート。docker-compose で
    # host==container の同一パスに bind mount する前提 (§5.2)。
    # 空文字のときは CVAT 保存 + 自動デプロイをスキップし、zip のみ生成する
    # (後方互換)。
    cvat_base_path: str = ""
    # deploy script 実行のタイムアウト秒 (§9.6)。
    deploy_timeout_seconds: int = 600
    # deploy 専用 RQ キュー名。deploy script は docker/nuctl を必要とするため、
    # このキューは WSL ホスト側の deploy ワーカーが処理する (別ワーカー分離)。
    deploy_queue_name: str = "deploy"

    @property
    def redis_url(self) -> str:
        """RQ / redis クライアント用の接続 URL。"""
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"

    @property
    def cvat_serverless_dir(self) -> Path:
        """CVAT の serverless ディレクトリ (§5.1)。deploy script の cwd。"""
        return Path(self.cvat_base_path) / "cvat" / "serverless"

    @property
    def cvat_mymodel_dir(self) -> Path:
        """生成フォルダの保存先 <serverless>/mymodel (§4.1 / §7)。"""
        return self.cvat_serverless_dir / "mymodel"

    def deploy_script_path(self, target: str) -> Path:
        """CPU/GPU に応じた deploy script のパス (§8.1)。

        target は "cpu" / "gpu"。<serverless>/deploy_{cpu,gpu}.sh を返す。
        """
        return self.cvat_serverless_dir / f"deploy_{target}.sh"


@lru_cache
def get_settings() -> Settings:
    """設定シングルトン。プロセス内で 1 度だけ読み込む。"""
    return Settings()


# 利便性のためのモジュールレベル参照
settings = get_settings()
