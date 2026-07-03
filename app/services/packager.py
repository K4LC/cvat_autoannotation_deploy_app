"""出力フォルダの zip 化 (T-08)

生成済みの 4 ファイルを 1 つのフォルダにまとめ、zip 化する (§8 / F-12 / F-13)。

zip を展開すると以下になる (§8 / AC-07):
    <model_internal_name>/
    ├── function.yaml
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

# zip に含める 4 ファイル (§5.2)。これ以外は含めない。
EXPECTED_FILES: tuple[str, ...] = (
    "function.yaml",
    "main.py",
    "model.onnx",
    "model_handler.py",
)

ZIP_NAME_PREFIX = "cvat-yolo-"


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
) -> Path:
    """`model_dir` 内の 4 ファイルを `<internal_name>/` 配下として zip 化する。

    Args:
        model_dir: 4 ファイルが入った出力フォルダ (例: .../output/<internal_name>)。
        zip_path: 出力する zip のパス。
        internal_name: アーカイブ内のトップフォルダ名。未指定なら model_dir 名を使う。

    Returns:
        作成した zip の Path。

    Raises:
        PackagingError: 必須ファイルが欠けている場合。
    """
    model_dir = Path(model_dir)
    zip_path = Path(zip_path)
    internal_name = internal_name or model_dir.name

    missing = [name for name in EXPECTED_FILES if not (model_dir / name).is_file()]
    if missing:
        raise PackagingError(
            f"zip 化に必要なファイルが不足しています: {', '.join(missing)}"
        )

    zip_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for name in EXPECTED_FILES:
                zf.write(model_dir / name, arcname=f"{internal_name}/{name}")
    except OSError as exc:
        raise PackagingError("zipファイルの作成に失敗しました") from exc

    return zip_path
