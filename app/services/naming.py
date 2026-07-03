"""モデル内部名の正規化 (T-03)

SVG から取得した名前を、ファイル名・フォルダ名・Nuclio 関数名・function.yaml の
関数識別名として安全に使える形式へ変換する (§7.1 / §14.5)。

使用可能文字は以下とする:
  - 英小文字 (a-z)
  - 数字 (0-9)
  - ハイフン (-)

要件 §7.1 ではアンダースコアも許可としていたが、Nuclio/k8s の名前規約
(DNS-1123) がアンダースコアを許さないため、本アプリではアンダースコアを
使わずハイフンへ変換する方針とする。

変換例:
  "My Pose Model" -> "my-pose-model"

依存ライブラリ不要（標準ライブラリ re のみ）。
"""

import re

# 許可外文字（空白・アンダースコアを含む）の連続。ハイフン1つへ畳み込む。
_DISALLOWED = re.compile(r"[^a-z0-9-]+")
# 連続ハイフン。1つへ畳み込む。
_MULTI_HYPHEN = re.compile(r"-{2,}")

# 生成物の名前が過度に長くなるのを防ぐ上限（Nuclio/コンテナ名の実用的な範囲）。
MAX_LENGTH = 63


class InvalidNameError(ValueError):
    """内部名として使える文字列に正規化できなかった場合に送出する。"""


def normalize_internal_name(raw: str) -> str:
    """名前を安全なモデル内部名へ正規化する。

    Args:
        raw: SVG などから取得した元の名前。

    Returns:
        `[a-z0-9_-]` のみからなる文字列。

    Raises:
        InvalidNameError: 入力が空、または正規化後に空になった場合。
    """
    if raw is None or not raw.strip():
        raise InvalidNameError("モデル内部名が空です")

    # 小文字化してから、許可外文字（空白含む）の連続をハイフンへ。
    name = _DISALLOWED.sub("-", raw.strip().lower())
    # 連続ハイフンを1つに畳み込む。
    name = _MULTI_HYPHEN.sub("-", name)
    # 前後のハイフンを除去。
    name = name.strip("-")

    if not name:
        raise InvalidNameError(
            f"正規化後のモデル内部名が空になりました: {raw!r}"
        )

    if len(name) > MAX_LENGTH:
        name = name[:MAX_LENGTH].strip("-")

    return name
