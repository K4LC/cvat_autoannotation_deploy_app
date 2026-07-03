"""SVG 解析 (T-05)

CVAT がエクスポートする skeleton ラベルの SVG (例: example/svg/person.svg) から、
CVAT/Nuclio の function.yaml へ登録するために必要な情報を抽出する。

抽出対象 (§7.2):
  - keypoints  : キーポイント(サブラベル)名の一覧
  - skeleton   : 骨格の辺 [node_from, node_to] の一覧
  - sublabels  : function.yaml の "sublabels" にそのまま入る [{id,name,type}]
  - svg_info   : function.yaml の "svg" に埋め込むクリーンな SVG 要素文字列
                 (入力の stroke/fill 等を除去し、circle に data-label-name を付与)

入力 SVG の構造 (example/svg/person.svg):
  <svg ...>
    <line ... data-type="edge" data-node-from="N" data-node-to="M"></line>   # 骨格の辺
    <circle ... data-type="element node" data-node-id="I"></circle>          # キーポイント
    <desc data-description-type="labels-specification">{ ...JSON... }</desc>  # サブラベル定義
  </svg>

出力フォーマットの参照: example/mmpose_keypoint_cpu/function.yaml の annotations.spec。

セキュリティ (§20.4 / §23.2):
  defusedxml を用いて外部実体参照(XXE)や危険な XML 処理を防ぐ。

注意: 本 SVG にはモデル内部名(§7.1)に相当する情報が含まれない。モデル内部名の
      決定は本モジュールの責務外とし、呼び出し側で扱う (別途確認事項)。
"""

from __future__ import annotations

import json
from pathlib import Path

from defusedxml.ElementTree import ParseError, parse
from pydantic import BaseModel, Field


class SvgParseError(Exception):
    """SVG から必要な情報を取得できなかった場合に送出する (§7.3 / F-15)。"""


class ParsedSvg(BaseModel):
    """SVG から抽出した骨格推定用の情報。"""

    labels: list[str] = Field(default_factory=list)      # サブラベル名の一覧 (§7.2)
    keypoints: list[str] = Field(default_factory=list)   # = labels (キーポイント名)
    skeleton: list[list[int]] = Field(default_factory=list)  # 辺 [from, to]
    sublabels: list[dict] = Field(default_factory=list)  # function.yaml 用 [{id,name,type}]
    svg_info: str = ""                                   # function.yaml 用 svg 文字列


def _localname(tag: str) -> str:
    """名前空間付きタグ ({ns}line) からローカル名 (line) を取り出す。"""
    return tag.rsplit("}", 1)[-1]


def _validate_labels(names: list[str]) -> list[str]:
    """ラベル名を検証・正規化する (§7.2)。

    - 前後空白を除去
    - 1 件以上存在
    - 空文字を許可しない
    - 重複を許可しない
    """
    cleaned = [n.strip() for n in names]

    if not cleaned:
        raise SvgParseError("SVGファイルからラベル情報を取得できませんでした")
    if any(n == "" for n in cleaned):
        raise SvgParseError("SVGファイル内に空のラベル名が存在します")
    if len(set(cleaned)) != len(cleaned):
        raise SvgParseError("SVGファイル内のラベルが重複しています")

    return cleaned


def parse_svg(path: str | Path) -> ParsedSvg:
    """SVG を解析して ParsedSvg を返す。

    Raises:
        SvgParseError: XML が不正、またはキーポイント/ラベルを取得できない場合。
    """
    try:
        tree = parse(str(path))
    except (ParseError, OSError) as exc:
        raise SvgParseError("SVGファイルの形式が不正です") from exc

    root = tree.getroot()

    lines: list = []
    circles: list = []
    desc_json: dict | None = None

    for el in root.iter():
        name = _localname(el.tag)
        if name == "line" and el.attrib.get("data-type") == "edge":
            lines.append(el)
        elif name == "circle" and el.attrib.get("data-type") == "element node":
            circles.append(el)
        elif name == "desc" and el.attrib.get("data-description-type") == "labels-specification":
            try:
                desc_json = json.loads((el.text or "").strip())
            except json.JSONDecodeError:
                desc_json = None

    if not circles:
        raise SvgParseError("SVGファイルからラベル情報を取得できませんでした（キーポイントがありません）")

    # --- サブラベル名の決定 ---
    # desc の labels-specification があればそれを優先（順序保持）。
    # 無ければ circle の data-node-id を名前として使う。
    if desc_json:
        node_to_name = {key: (val.get("name") or key) for key, val in desc_json.items()}
        ordered_names = [(val.get("name") or key, val.get("type", "points"))
                         for key, val in desc_json.items()]
    else:
        node_to_name = {c.attrib.get("data-node-id", ""): c.attrib.get("data-node-id", "")
                        for c in circles}
        ordered_names = [(c.attrib.get("data-node-id", ""), "points") for c in circles]

    label_names = _validate_labels([n for n, _ in ordered_names])

    sublabels = [
        {"id": idx, "name": name, "type": typ}
        for idx, (name, typ) in enumerate(
            (n, t) for n, (_, t) in zip(label_names, ordered_names)
        )
    ]

    # --- 骨格の辺 ---
    skeleton: list[list[int]] = []
    for ln in lines:
        try:
            frm = int(ln.attrib["data-node-from"])
            to = int(ln.attrib["data-node-to"])
        except (KeyError, ValueError):
            continue
        skeleton.append([frm, to])

    # --- function.yaml に埋め込む svg 文字列を再構築 ---
    svg_info = _build_svg_info(lines, circles, node_to_name)

    return ParsedSvg(
        labels=label_names,
        keypoints=label_names,
        skeleton=skeleton,
        sublabels=sublabels,
        svg_info=svg_info,
    )


def _build_svg_info(lines: list, circles: list, node_to_name: dict[str, str]) -> str:
    """入力要素から、function.yaml の "svg" に入れるクリーンな文字列を作る。

    - line   : x1,y1,x2,y2,data-type,data-node-from,data-node-to のみ残す
    - circle : r,cx,cy,data-type,data-element-id,data-node-id,data-label-name のみ残す
               (stroke/fill/stroke-width 等の描画属性は除去し、data-label-name を付与)
    要素は line 群 -> circle 群 の順で改行区切り (example の function.yaml に合わせる)。
    """
    parts: list[str] = []

    for ln in lines:
        a = ln.attrib
        parts.append(
            f'<line x1="{a.get("x1", "")}" y1="{a.get("y1", "")}"'
            f' x2="{a.get("x2", "")}" y2="{a.get("y2", "")}"'
            f' data-type="edge" data-node-from="{a.get("data-node-from", "")}"'
            f' data-node-to="{a.get("data-node-to", "")}"></line>'
        )

    for c in circles:
        a = c.attrib
        node_id = a.get("data-node-id", "")
        element_id = a.get("data-element-id", node_id)
        label_name = node_to_name.get(node_id, node_id)
        parts.append(
            f'<circle r="{a.get("r", "")}" cx="{a.get("cx", "")}" cy="{a.get("cy", "")}"'
            f' data-type="element node" data-element-id="{element_id}"'
            f' data-node-id="{node_id}" data-label-name="{label_name}"></circle>'
        )

    return "\n".join(parts)
