"""deployer サービスのテスト — req_add02 §7〜§9 (ステップ3)。

- save_to_cvat: 5 ファイルのみコピー / SVG・.pt・zip 非含有 / 同名衝突で連番 /
  既存非上書き (AC-16)
- run_deploy: subprocess を fake runner に差し替え、成功 / 失敗 / タイムアウト /
  実行権限エラー / script 不在 の各分岐と、ログファイル・deploy_result.json の生成

依存は標準ライブラリのみ (subprocess は runner 引数で注入)。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.deployer import (
    DeployError,
    run_deploy,
    save_to_cvat,
)
from app.services.packager import EXPECTED_FILES

NAME = "human-pose-202607061530"


def _make_output_dir(tmp_path: Path) -> Path:
    """EXPECTED_FILES + 除外対象 (svg/pt/zip) を含む生成フォルダを作る。"""
    out = tmp_path / "output" / NAME
    out.mkdir(parents=True)
    for fname in EXPECTED_FILES:
        (out / fname).write_text(f"content-{fname}", encoding="utf-8")
    # 保存対象外 (§6)
    (out / "model.svg").write_text("svg", encoding="utf-8")
    (out / "model.pt").write_text("pt", encoding="utf-8")
    (out / f"cvat-yolo-{NAME}.zip").write_text("zip", encoding="utf-8")
    return out


# ---------------------------------------------------------------- save_to_cvat


def test_save_to_cvat_copies_only_five_files(tmp_path: Path) -> None:
    out = _make_output_dir(tmp_path)
    mymodel = tmp_path / "cvat" / "serverless" / "mymodel"

    dest = save_to_cvat(out, NAME, mymodel)

    assert dest == mymodel / NAME
    copied = sorted(p.name for p in dest.iterdir())
    assert copied == sorted(EXPECTED_FILES)
    # 除外対象は含まれない
    assert not (dest / "model.svg").exists()
    assert not (dest / "model.pt").exists()
    assert not (dest / f"cvat-yolo-{NAME}.zip").exists()


def test_save_to_cvat_creates_mymodel_dir(tmp_path: Path) -> None:
    out = _make_output_dir(tmp_path)
    mymodel = tmp_path / "cvat" / "serverless" / "mymodel"  # まだ存在しない
    assert not mymodel.exists()
    save_to_cvat(out, NAME, mymodel)
    assert mymodel.is_dir()


def test_save_to_cvat_missing_file_raises(tmp_path: Path) -> None:
    out = _make_output_dir(tmp_path)
    (out / EXPECTED_FILES[0]).unlink()
    mymodel = tmp_path / "mymodel"
    with pytest.raises(DeployError) as ei:
        save_to_cvat(out, NAME, mymodel)
    assert EXPECTED_FILES[0] in str(ei.value)


def test_save_to_cvat_collision_appends_suffix(tmp_path: Path) -> None:
    out = _make_output_dir(tmp_path)
    mymodel = tmp_path / "mymodel"
    mymodel.mkdir()
    # 既存フォルダ (中身入り) を用意 -> 上書きされないことを確認
    existing = mymodel / NAME
    existing.mkdir()
    (existing / "keep.txt").write_text("original", encoding="utf-8")

    dest1 = save_to_cvat(out, NAME, mymodel)
    assert dest1 == mymodel / f"{NAME}_001"
    # 既存は無傷 (AC-16)
    assert (existing / "keep.txt").read_text(encoding="utf-8") == "original"

    dest2 = save_to_cvat(out, NAME, mymodel)
    assert dest2 == mymodel / f"{NAME}_002"


# ------------------------------------------------------------------ run_deploy


def _serverless_with_export(tmp_path: Path) -> tuple[Path, Path, Path]:
    serverless = tmp_path / "cvat" / "serverless"
    exported = serverless / "mymodel" / NAME
    exported.mkdir(parents=True)
    log_dir = tmp_path / "logs"
    return serverless, exported, log_dir


def _fake_runner(returncode: int, stdout: str = "", stderr: str = "", capture: dict | None = None):
    def runner(argv, **kwargs):
        if capture is not None:
            capture["argv"] = argv
            capture["kwargs"] = kwargs
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)

    return runner


def test_run_deploy_success(tmp_path: Path) -> None:
    serverless, exported, log_dir = _serverless_with_export(tmp_path)
    capture: dict = {}
    result = run_deploy(
        target="cpu",
        exported_folder=exported,
        serverless_dir=serverless,
        log_dir=log_dir,
        timeout=60,
        runner=_fake_runner(0, stdout="deploy ok\n", capture=capture),
    )

    assert result.return_code == 0
    assert result.stdout_tail == "deploy ok"
    # 相対パスで serverless から実行される (§8.3)
    assert capture["argv"] == ["./deploy_cpu.sh", f"./mymodel/{NAME}"]
    assert capture["kwargs"]["cwd"] == str(serverless)
    # ログ + result.json が生成される (§9.5)
    assert Path(result.stdout_log_path).read_text(encoding="utf-8") == "deploy ok\n"
    meta = json.loads(Path(result.result_path).read_text(encoding="utf-8"))
    assert meta["return_code"] == 0
    assert meta["script"].endswith("deploy_cpu.sh")


def test_run_deploy_gpu_uses_gpu_script(tmp_path: Path) -> None:
    serverless, exported, log_dir = _serverless_with_export(tmp_path)
    capture: dict = {}
    run_deploy(
        target="gpu",
        exported_folder=exported,
        serverless_dir=serverless,
        log_dir=log_dir,
        timeout=60,
        runner=_fake_runner(0, capture=capture),
    )
    assert capture["argv"][0] == "./deploy_gpu.sh"


def test_run_deploy_failure_returns_nonzero_and_tail(tmp_path: Path) -> None:
    serverless, exported, log_dir = _serverless_with_export(tmp_path)
    big_stderr = "\n".join(f"line{i}" for i in range(150))
    result = run_deploy(
        target="cpu",
        exported_folder=exported,
        serverless_dir=serverless,
        log_dir=log_dir,
        timeout=60,
        runner=_fake_runner(1, stderr=big_stderr),
    )
    # 失敗は例外でなく DeployResult で返す (成否判定は tasks 側)
    assert result.return_code == 1
    # tail は末尾 100 行のみ
    assert result.stderr_tail == "\n".join(f"line{i}" for i in range(50, 150))
    # 全量はログファイルに保存
    assert Path(result.stderr_log_path).read_text(encoding="utf-8") == big_stderr


def test_run_deploy_script_not_found(tmp_path: Path) -> None:
    serverless, exported, log_dir = _serverless_with_export(tmp_path)

    def runner(argv, **kwargs):
        raise FileNotFoundError()

    with pytest.raises(DeployError) as ei:
        run_deploy(
            target="cpu",
            exported_folder=exported,
            serverless_dir=serverless,
            log_dir=log_dir,
            timeout=60,
            runner=runner,
        )
    assert "deploy_cpu.sh" in str(ei.value)
    # 失敗時も result を添える (return_code None)
    assert ei.value.result is not None
    assert ei.value.result.return_code is None


def test_run_deploy_permission_error(tmp_path: Path) -> None:
    serverless, exported, log_dir = _serverless_with_export(tmp_path)

    def runner(argv, **kwargs):
        raise PermissionError()

    with pytest.raises(DeployError) as ei:
        run_deploy(
            target="cpu",
            exported_folder=exported,
            serverless_dir=serverless,
            log_dir=log_dir,
            timeout=60,
            runner=runner,
        )
    assert "実行権限" in str(ei.value)


def test_run_deploy_timeout_saves_partial_logs(tmp_path: Path) -> None:
    serverless, exported, log_dir = _serverless_with_export(tmp_path)

    def runner(argv, **kwargs):
        raise subprocess.TimeoutExpired(
            cmd=argv, timeout=1, output="partial-out", stderr="partial-err"
        )

    with pytest.raises(DeployError) as ei:
        run_deploy(
            target="cpu",
            exported_folder=exported,
            serverless_dir=serverless,
            log_dir=log_dir,
            timeout=1,
            runner=runner,
        )
    assert "タイムアウト" in str(ei.value)
    res = ei.value.result
    assert res is not None
    # 部分ログが保存される (§9.6)
    assert Path(res.stdout_log_path).read_text(encoding="utf-8") == "partial-out"
    assert Path(res.stderr_log_path).read_text(encoding="utf-8") == "partial-err"
