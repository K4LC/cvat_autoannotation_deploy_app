"""DLC 対応の packager / generator テスト。

- expected_files がモデル種別ごとに正しい集合を返す
- generator が model_type=dlc で templates/dlc を選び、YOLO では従来テンプレを使う
"""

from __future__ import annotations

from pathlib import Path

from app.schemas import ModelType
from app.services import generator as g
from app.services.packager import DLC_FILES, YOLO_FILES, expected_files


def test_expected_files_by_model_type():
    assert expected_files(ModelType.YOLO_POSE) == YOLO_FILES
    assert expected_files("yolo") == YOLO_FILES
    assert expected_files(ModelType.DLC) == DLC_FILES
    assert expected_files("dlc") == DLC_FILES
    # DLC は .onnx を含まず .pt + pytorch_config.yaml を含む
    assert "model.onnx" not in DLC_FILES
    assert "model.pt" in DLC_FILES and "pytorch_config.yaml" in DLC_FILES
    # YOLO は model.onnx を含む
    assert "model.onnx" in YOLO_FILES


_CTX = {
    "author": "A",
    "display_name": "Uma",
    "display_name_json": '"Uma"',
    "description_json": '"d"',
    "function_name": "uma-202607071200",
    "timestamp": "20260707120000",
    "spec_json": '[{"name":"animal"}]',
    "modelOnnx": "model.onnx",
    "modelPt": "model.pt",
    "dlcConfig": "pytorch_config.yaml",
    "modelName": "uma-202607071200",
}


def test_generator_dlc_templates(tmp_path: Path):
    g.render_all(tmp_path, _CTX, model_type="dlc")
    handler = (tmp_path / "model_handler.py").read_text(encoding="utf-8")
    func = (tmp_path / "function.yaml").read_text(encoding="utf-8")
    # DLC ハンドラは .pt/config を読み、onnx は使わない
    assert 'torch.load("model.pt"' in handler
    assert 'open("pytorch_config.yaml"' in handler
    assert "model.onnx" not in handler
    # function.yaml は DLC 名 + deeplabcut 依存
    assert "dlc-uma-202607071200" in func
    assert "deeplabcut" in func


def test_generator_yolo_templates_unchanged(tmp_path: Path):
    g.render_all(tmp_path, _CTX, model_type="yolo")
    handler = (tmp_path / "model_handler.py").read_text(encoding="utf-8")
    assert "model.onnx" in handler  # 従来の ONNX ハンドラ
