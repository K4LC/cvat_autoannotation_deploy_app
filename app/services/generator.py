"""CVAT/Nuclio 用ファイル生成 (T-07)

`templates/*.tpl` (Jinja2) をレンダリングして、出力フォルダへ以下を生成する:
  - function.yaml       (templates/function.yaml.tpl … CPU 用)
  - function-gpu.yaml   (templates/function-gpu.yaml.tpl … GPU 用)
  - main.py             (templates/main.py.tpl)
  - model_handler.py    (templates/model_handler.py.tpl)

CPU/GPU の function.yaml を常に両方生成する (req_add §2)。main.py / model_handler.py は
CPU/GPU 共通（ラベルは実行時に function.yaml の spec から読むため）。

設計判断 (ユーザー確認済み):
  - モデル内部名 function_name = normalize_internal_name(display_name) + "-yyyymmddhhmm"。
    識別子系 (metadata.name / image tag / フォルダ名 / zip名) に使い、author は含めない。
  - skeleton の親ラベル名 (annotations.spec の "name") には SVGラベル名(svg_label) を使う。
  - annotations.name・description には表示名(display_name)を使う。

エスケープ安全性:
  annotations.spec に入る JSON (display_name / svg 文字列 / sublabels) は、テンプレ側で
  手組みするとクォートや改行で壊れやすい。そこで generator 側で json.dumps により
  組み立て、テンプレへは完成済み文字列として渡す。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from app.services.svg_parser import ParsedSvg

# タイムスタンプは日本標準時 (JST, UTC+9) で統一する。
JST = timezone(timedelta(hours=9))

# templates/ はプロジェクト直下 (app/services/generator.py から 2 つ上)。
TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "templates"

# 出力する固定モデルファイル名 (§23.5)。
MODEL_ONNX_NAME = "model.onnx"

# レンダリングするテンプレートと出力名の対応。
# CPU 用 (function.yaml) と GPU 用 (function-gpu.yaml) を常に両方生成する
# (req_add §2)。main.py / model_handler.py は CPU/GPU 共通。
TEMPLATE_MAP: dict[str, str] = {
    "function.yaml.tpl": "function.yaml",
    "function-gpu.yaml.tpl": "function-gpu.yaml",
    "main.py.tpl": "main.py",
    "model_handler.py.tpl": "model_handler.py",
}


def build_context(
    *,
    author: str,
    display_name: str,
    function_name: str,
    svg_label: str,
    parsed: ParsedSvg,
    timestamp: str | None = None,
) -> dict:
    """テンプレートへ渡すコンテキストを組み立てる。

    JSON エスケープが必要な値 (spec / display_name / description) は json.dumps で
    整形済みにして渡す。

    Args:
        svg_label: CVAT に表示する骨格オブジェクトのラベル名 (annotations.spec の "name")。
                   フォームの「SVGラベル名」入力に対応 (req_add §3)。
        display_name: CVAT 検出器の表示名 (annotations.name) と説明文に使う。
    """
    ts = timestamp or datetime.now(JST).strftime("%Y%m%d%H%M%S")

    # annotations.spec に入る JSON（skeleton 1 個）。json.dumps が全エスケープを担う。
    # "name" は CVAT 上のラベル名なので SVGラベル名 (svg_label) を使う (req_add §3)。
    spec_list = [
        {
            "name": svg_label,
            "type": "skeleton",
            "svg": parsed.svg_info,
            "sublabels": parsed.sublabels,
        }
    ]
    spec_json = json.dumps(spec_list, ensure_ascii=False, indent=2)

    description = f"{display_name} created by {author} at {ts}"

    return {
        "author": author,
        "display_name": display_name,
        # YAML スカラーに安全に入れるため JSON 文字列(引用符付き)にする。
        # JSON 文字列は YAML の flow スカラーとしても妥当。
        "display_name_json": json.dumps(display_name, ensure_ascii=False),
        "description_json": json.dumps(description, ensure_ascii=False),
        "function_name": function_name,
        "timestamp": ts,
        "spec_json": spec_json,
        "modelOnnx": MODEL_ONNX_NAME,
        # 後方互換: テンプレに modelName が残っていても壊れないよう識別子を割り当てる。
        "modelName": function_name,
    }


def _env(template_dir: Path) -> Environment:
    return Environment(
        loader=FileSystemLoader(str(template_dir)),
        undefined=StrictUndefined,      # 未定義変数はエラーにして早期検出
        keep_trailing_newline=True,
        autoescape=False,               # コード/YAML 生成なので HTML エスケープは不要
    )


def render_all(
    out_dir: str | Path,
    context: dict,
    *,
    template_dir: str | Path | None = None,
) -> dict[str, Path]:
    """TEMPLATE_MAP の全テンプレートをレンダリングして out_dir に書き出す。

    Returns:
        {出力ファイル名: 書き出した Path} の辞書。
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    env = _env(Path(template_dir) if template_dir else TEMPLATE_DIR)

    written: dict[str, Path] = {}
    for tpl_name, out_name in TEMPLATE_MAP.items():
        template = env.get_template(tpl_name)
        rendered = template.render(**context)
        dest = out_dir / out_name
        dest.write_text(rendered, encoding="utf-8")
        written[out_name] = dest
    return written
