"""CVAT serverless 配下への保存と deploy script 実行 (req_add02 §7〜§9)

生成済みの 5 ファイルを CVAT の `serverless/mymodel/<model_internal_name>/` へ
コピーし (save_to_cvat)、ユーザーが選んだ CPU/GPU に応じた deploy script を
worker から実行する (run_deploy)。

保存先 (§4.1 / §7):
    <CVAT_BASE_PATH>/cvat/serverless/mymodel/<model_internal_name>/

deploy script (§8.1 / §8.3): cwd を serverless に置いて相対実行する。
    cd <CVAT_BASE_PATH>/cvat/serverless
    ./deploy_cpu.sh ./mymodel/<model_internal_name>

zipfile と同様、依存は標準ライブラリ (shutil / subprocess / json) のみ。
subprocess はテスト時に `runner` 引数で差し替えできる (onnx_export の
model_factory と同じ注入方式)。
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

# CVAT へ保存する 5 ファイル。packager と同一集合を再利用する (§6)。
from app.services.packager import EXPECTED_FILES

# ログのタイムスタンプは日本標準時 (JST, UTC+9) で統一する (§9.5 の例も +09:00)。
JST = timezone(timedelta(hours=9))

# 画面表示・保存する stdout/stderr の末尾行数 (§9.4)。
TAIL_LINES = 100

# ログファイル名 (§9.5)。
STDOUT_LOG_NAME = "deploy_stdout.log"
STDERR_LOG_NAME = "deploy_stderr.log"
RESULT_JSON_NAME = "deploy_result.json"


class DeployError(Exception):
    """CVAT 保存 / deploy script 実行に失敗した場合に送出する (§9.3/§9.6/§9.7)。

    可能なら失敗時点までに得られた情報 (ログ tail 等) を `result` に添えて、
    画面に表示できるようにする。
    """

    def __init__(self, message: str, *, result: "DeployResult | None" = None) -> None:
        super().__init__(message)
        self.result = result


@dataclass
class DeployResult:
    """deploy script 実行の結果 (§9.1)。Redis / 画面表示・deploy_result.json の元。"""

    script_path: str
    cwd: str
    return_code: int | None
    stdout_tail: str
    stderr_tail: str
    started_at: str
    finished_at: str
    stdout_log_path: str | None = None
    stderr_log_path: str | None = None
    result_path: str | None = None


def _now_iso() -> str:
    """JST の ISO8601 文字列 (§9.5 の started_at/finished_at 形式)。"""
    return datetime.now(JST).isoformat()


def _tail(text: str | None, lines: int = TAIL_LINES) -> str:
    """文字列の末尾 `lines` 行を返す (長大ログの画面表示・保存用 §9.4)。"""
    if not text:
        return ""
    parts = text.splitlines()
    return "\n".join(parts[-lines:])


def _reserve_unique_dir(mymodel_dir: Path, name: str) -> Path:
    """`mymodel_dir/name` を作成する。既存なら `_001`,`_002`… と連番付与 (§7.3)。

    既存フォルダは上書きしない (AC-16)。作成に成功したディレクトリを返す。
    mkdir(exist_ok=False) で「存在チェック→作成」を原子的に行い競合を避ける。
    """
    candidates = [name] + [f"{name}_{i:03d}" for i in range(1, 1000)]
    for candidate in candidates:
        dest = mymodel_dir / candidate
        try:
            dest.mkdir(parents=False, exist_ok=False)
            return dest
        except FileExistsError:
            continue
    raise DeployError(f"保存先フォルダ名の重複が多すぎます: {name}")


def save_to_cvat(output_dir: str | Path, function_name: str, mymodel_dir: str | Path) -> Path:
    """生成済み 5 ファイルを CVAT の mymodel 配下へコピーする (§7)。

    Args:
        output_dir: 5 ファイルが入った生成フォルダ (…/output/<function_name>)。
        function_name: 保存先フォルダ名 (= モデル内部名)。
        mymodel_dir: <CVAT_BASE_PATH>/cvat/serverless/mymodel。

    Returns:
        実際に保存したフォルダの Path (衝突時は連番付き)。

    Raises:
        DeployError: 必須ファイルが不足している場合。
    """
    output_dir = Path(output_dir)
    mymodel_dir = Path(mymodel_dir)

    missing = [name for name in EXPECTED_FILES if not (output_dir / name).is_file()]
    if missing:
        raise DeployError(
            f"CVAT保存に必要なファイルが不足しています: {', '.join(missing)}"
        )

    # mymodel ディレクトリが無ければ作成する (§7.2)。
    mymodel_dir.mkdir(parents=True, exist_ok=True)

    dest = _reserve_unique_dir(mymodel_dir, function_name)
    # SVG / .pt / zip は含めない (§6)。EXPECTED_FILES の 5 ファイルのみ。
    for name in EXPECTED_FILES:
        shutil.copy2(output_dir / name, dest / name)
    return dest


def _write_logs(
    log_dir: Path,
    *,
    stdout: str | None,
    stderr: str | None,
    result_meta: dict,
) -> tuple[Path, Path, Path]:
    """stdout/stderr 全量とメタ情報 (deploy_result.json) を保存する (§9.5)。"""
    log_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = log_dir / STDOUT_LOG_NAME
    stderr_path = log_dir / STDERR_LOG_NAME
    result_path = log_dir / RESULT_JSON_NAME

    stdout_path.write_text(stdout or "", encoding="utf-8")
    stderr_path.write_text(stderr or "", encoding="utf-8")
    meta = dict(result_meta)
    meta["stdout_log_path"] = str(stdout_path)
    meta["stderr_log_path"] = str(stderr_path)
    result_path.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return stdout_path, stderr_path, result_path


def run_deploy(
    *,
    target: str,
    exported_folder: str | Path,
    serverless_dir: str | Path,
    log_dir: str | Path,
    timeout: int,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> DeployResult:
    """deploy script を実行し結果を返す (§8/§9)。

    cwd を serverless に置き `./deploy_{target}.sh ./mymodel/<name>` を実行する。
    stdout/stderr/return code とログファイルパスを含む DeployResult を返す。
    終了コードが 0 以外でも DeployResult を返す (成功/失敗判定は呼び出し側=§9.2/§9.3)。

    Raises:
        DeployError: script が存在しない / 実行権限が無い / タイムアウトした場合
            (§9.6/§9.7)。可能な範囲でログを保存し、result を添えて送出する。
    """
    serverless_dir = Path(serverless_dir)
    exported_folder = Path(exported_folder)
    log_dir = Path(log_dir)

    script_name = f"deploy_{target}.sh"
    script_path = serverless_dir / script_name
    # serverless からの相対パスで渡す (§8.3: ./mymodel/<name>)。
    rel_arg = "./" + exported_folder.relative_to(serverless_dir).as_posix()
    argv = [f"./{script_name}", rel_arg]

    started_at = _now_iso()

    def _meta(return_code: int | None) -> dict:
        return {
            "script": str(script_path),
            "cwd": str(serverless_dir),
            "return_code": return_code,
            "started_at": started_at,
            "finished_at": _now_iso(),
        }

    try:
        proc = runner(
            argv,
            cwd=str(serverless_dir),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        result = _finalize(log_dir, None, "", "", _meta(None), script_path, serverless_dir, started_at)
        raise DeployError(
            f"{script_name} が見つかりません: {script_path}", result=result
        ) from exc
    except PermissionError as exc:
        result = _finalize(log_dir, None, "", "", _meta(None), script_path, serverless_dir, started_at)
        raise DeployError(
            f"{script_name}に実行権限がありません。chmod +x を実行してください。",
            result=result,
        ) from exc
    except subprocess.TimeoutExpired as exc:
        # タイムアウト時も得られた部分ログを保存する (§9.6)。
        stdout = exc.stdout if isinstance(exc.stdout, str) else (
            exc.stdout.decode("utf-8", "replace") if exc.stdout else ""
        )
        stderr = exc.stderr if isinstance(exc.stderr, str) else (
            exc.stderr.decode("utf-8", "replace") if exc.stderr else ""
        )
        result = _finalize(
            log_dir, None, stdout, stderr, _meta(None), script_path, serverless_dir, started_at
        )
        raise DeployError(
            "デプロイ処理がタイムアウトしました。"
            "DEPLOY_TIMEOUT_SECONDSの設定を確認してください。",
            result=result,
        ) from exc

    return _finalize(
        log_dir,
        proc.returncode,
        proc.stdout,
        proc.stderr,
        _meta(proc.returncode),
        script_path,
        serverless_dir,
        started_at,
    )


def _finalize(
    log_dir: Path,
    return_code: int | None,
    stdout: str | None,
    stderr: str | None,
    meta: dict,
    script_path: Path,
    serverless_dir: Path,
    started_at: str,
) -> DeployResult:
    """ログを保存し DeployResult を組み立てる共通処理。"""
    stdout_path, stderr_path, result_path = _write_logs(
        log_dir, stdout=stdout, stderr=stderr, result_meta=meta
    )
    return DeployResult(
        script_path=str(script_path),
        cwd=str(serverless_dir),
        return_code=return_code,
        stdout_tail=_tail(stdout),
        stderr_tail=_tail(stderr),
        started_at=started_at,
        finished_at=meta["finished_at"],
        stdout_log_path=str(stdout_path),
        stderr_log_path=str(stderr_path),
        result_path=str(result_path),
    )


def result_to_fields(result: DeployResult) -> dict:
    """DeployResult を JobRecord/JobStore の set_status(**fields) 用 dict に変換する。"""
    return {
        "deploy_return_code": result.return_code,
        "deploy_stdout_tail": result.stdout_tail,
        "deploy_stderr_tail": result.stderr_tail,
        "deploy_script_path": result.script_path,
        "deploy_stdout_log_path": result.stdout_log_path,
        "deploy_stderr_log_path": result.stderr_log_path,
        "deploy_result_path": result.result_path,
    }


__all__ = [
    "DeployError",
    "DeployResult",
    "save_to_cvat",
    "run_deploy",
    "result_to_fields",
]
