"""出力フォルダの zip 化 (T-08)

生成済みの 5 ファイルを 1 つのフォルダにまとめ、zip 化する (§8 / F-12 / F-13 / req_add §2)。

zip を展開すると以下になる (§8 / AC-07 / req_add §2):
    <model_internal_name>/
    ├── function.yaml       (CPU 用)
    ├── function-gpu.yaml   (GPU 用)
    ├── main.py
    ├── model.onnx
    └── model_handler.py

zip ファイル名 (§8 / F-13):
    cvat-yolo-<model_internal_name>.zip

SVG / .pt / README / icon.svg / deploy_*.sh 等は含めない (§8 / AC-08)。
そのため出力フォルダの中身を無条件に含めるのではなく、期待する 4 ファイルのみを
明示的にアーカイブする。

依存ライブラリ不要（標準ライブラリ zipfile のみ）。
"""

from __future__ import annotations

import zipfile
from pathlib import Path

from app.schemas import ModelType

# 共通で生成される 4 ファイル。
_COMMON_FILES: tuple[str, ...] = (
    "function.yaml",
    "function-gpu.yaml",
    "main.py",
    "model_handler.py",
)

# DLC でアップロード物から同梱する固定名 (main.py の保存名と一致させる)。
DLC_PT_NAME = "model.pt"
DLC_CONFIG_NAME = "pytorch_config.yaml"

# YOLO: 4 共通 + model.onnx。DLC: 4 共通 + snapshot(.pt) + pytorch_config.yaml。
YOLO_FILES: tuple[str, ...] = _COMMON_FILES + ("model.onnx",)
DLC_FILES: tuple[str, ...] = _COMMON_FILES + (DLC_PT_NAME, DLC_CONFIG_NAME)

# 後方互換 (既定は YOLO)。既存呼び出しはこれを使う。
EXPECTED_FILES: tuple[str, ...] = YOLO_FILES

ZIP_NAME_PREFIX = "cvat-yolo-"


def expected_files(model_type: ModelType | str = ModelType.YOLO_POSE) -> tuple[str, ...]:
    """モデル種別ごとに zip/保存へ含める固定ファイル一覧を返す。"""
    mt = ModelType(model_type) if not isinstance(model_type, ModelType) else model_type
    return DLC_FILES if mt is ModelType.DLC else YOLO_FILES


class PackagingError(Exception):
    """zip 作成に失敗した場合に送出する (F-13 / F-15)。"""


def zip_filename(internal_name: str) -> str:
    """内部名から zip ファイル名を組み立てる (§8)。"""
    return f"{ZIP_NAME_PREFIX}{internal_name}.zip"


def build_zip(
    model_dir: str | Path,
    zip_path: str | Path,
    *,
    internal_name: str | None = None,
    files: tuple[str, ...] | None = None,
) -> Path:
    """`model_dir` 内の対象ファイルを `<internal_name>/` 配下として zip 化する。

    Args:
        model_dir: 対象ファイルが入った出力フォルダ (例: .../output/<internal_name>)。
        zip_path: 出力する zip のパス。
        internal_name: アーカイブ内のトップフォルダ名。未指定なら model_dir 名を使う。
        files: 同梱する固定ファイル名。未指定なら YOLO 用 (EXPECTED_FILES)。
            DLC 等は expected_files(model_type) を渡す。

    Returns:
        作成した zip の Path。

    Raises:
        PackagingError: 必須ファイルが欠けている場合。
    """
    model_dir = Path(model_dir)
    zip_path = Path(zip_path)
    internal_name = internal_name or model_dir.name
    target_files = files if files is not None else EXPECTED_FILES

    missing = [name for name in target_files if not (model_dir / name).is_file()]
    if missing:
        raise PackagingError(
            f"zip 化に必要なファイルが不足しています: {', '.join(missing)}"
        )

    zip_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for name in target_files:
                zf.write(model_dir / name, arcname=f"{internal_name}/{name}")
    except OSError as exc:
        raise PackagingError("zipファイルの作成に失敗しました") from exc

    return zip_path
