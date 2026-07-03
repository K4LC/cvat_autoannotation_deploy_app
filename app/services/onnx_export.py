"""ONNX 変換 (T-06)

アップロードされた YOLO 系 `.pt` を ONNX 形式へ変換し、`model.onnx` として
指定ディレクトリへ配置する (§10.4 / F-08 / §23.5)。

出力ファイル名は必ず `model.onnx` に固定する (§23.5)。main.py / model_handler.py も
このファイル名を前提とする。

ultralytics(torch 同梱・重量級) はモジュール読み込み時ではなく変換実行時に遅延
import する。テストでは model_factory を差し替えることで、ultralytics 無しでも
移動/リネーム/例外処理を検証できる。
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Callable

from app.config import settings

# 出力モデルファイル名（固定 §23.5）
OUTPUT_MODEL_NAME = "model.onnx"


class OnnxExportError(Exception):
    """ONNX 変換に失敗した場合に送出する (F-08 / F-15)。"""


def _default_yolo_factory(pt_path: str):
    """本番用: ultralytics の YOLO をロードする（遅延 import）。"""
    from ultralytics import YOLO

    return YOLO(pt_path)


def export_to_onnx(
    pt_path: str | Path,
    out_dir: str | Path,
    *,
    opset: int | None = None,
    imgsz: int | None = None,
    nms: bool | None = None,
    model_factory: Callable[[str], object] | None = None,
) -> Path:
    """`.pt` を ONNX へ変換し `<out_dir>/model.onnx` を生成する。

    Args:
        pt_path: 入力の .pt ファイルパス。
        out_dir: 出力先ディレクトリ（無ければ作成）。
        opset: ONNX opset。未指定なら settings.onnx_opset。
        imgsz: 入力画像サイズ。未指定なら settings.image_size。
        nms: end2end NMS を埋め込むか。未指定なら settings.onnx_nms。
            model_handler.py は NMS 適用済みの (1, N, 6+kpt*3) 形式を前提とするため、
            通常は True にする（False だと生出力 (1, 56, 8400) となり後処理が破綻する）。
        model_factory: YOLO ローダの差し替え（テスト用）。

    Returns:
        生成された model.onnx の Path。

    Raises:
        OnnxExportError: 変換に失敗、または出力が得られなかった場合。
    """
    pt_path = Path(pt_path)
    out_dir = Path(out_dir)
    opset = opset if opset is not None else settings.onnx_opset
    imgsz = imgsz if imgsz is not None else settings.image_size
    nms = nms if nms is not None else settings.onnx_nms
    factory = model_factory or _default_yolo_factory

    if not pt_path.exists():
        raise OnnxExportError(f"入力の.ptファイルが見つかりません: {pt_path}")

    try:
        model = factory(str(pt_path))
        exported = model.export(format="onnx", opset=opset, imgsz=imgsz, nms=nms)
    except Exception as exc:  # ultralytics 由来の各種例外をまとめて扱う
        raise OnnxExportError("ONNX変換に失敗しました") from exc

    if not exported:
        raise OnnxExportError("ONNX変換に失敗しました（出力パスが得られませんでした）")

    src = Path(exported)
    if not src.exists():
        raise OnnxExportError(f"ONNX変換の出力が見つかりません: {src}")

    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / OUTPUT_MODEL_NAME
    shutil.move(str(src), str(dest))
    return dest
