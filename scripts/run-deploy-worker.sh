#!/usr/bin/env bash
# WSL(Ubuntu) ホスト上で deploy ワーカーを起動する冪等ランチャ (req_add02 / deploy 分離)。
#
# なぜ必要か:
#   Docker の worker は「生成→mymodel 保存」まで行い、deploy を "deploy" キューへ
#   enqueue して status=DEPLOYING(デプロイ待機中) にする。実際の deploy_{cpu,gpu}.sh は
#   docker/nuctl を要するため、それらがある WSL ホスト上のこのワーカーが処理する。
#   これを起動しないとジョブは「デプロイ待機中」のまま進まない。
#
# 前提:
#   - docker compose を WSL シェルから起動済み (redis が host:6379 に公開されている)。
#   - ホストに docker / nuctl が入っている (CVAT を手動デプロイできる環境)。
#   - .env に CVAT_BASE_PATH が設定済み (例: /home/isiku/Nas)。設定は自動で読まれる。
#
# 使い方 (リポジトリ直下で):
#   bash scripts/run-deploy-worker.sh
#
# 環境変数で上書き可能:
#   REDIS_URL   (既定: redis://localhost:6379/0)
#   REDIS_HOST  (既定: localhost) ... run_deploy_job 内の Redis 接続に使用
#   STORAGE_DIR (既定: <repo>/hoststorage) ... deploy ログの出力先

set -euo pipefail

# リポジトリ直下 (このスクリプトの 1 つ上) へ移動
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

REDIS_URL="${REDIS_URL:-redis://localhost:6379/0}"
export REDIS_HOST="${REDIS_HOST:-localhost}"
export STORAGE_DIR="${STORAGE_DIR:-$REPO_ROOT/hoststorage}"
export PYTHONPATH="$REPO_ROOT"

VENV="$REPO_ROOT/.deployvenv"
if [ ! -d "$VENV" ]; then
  echo "[deploy-worker] .deployvenv を作成します..."
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install -q --upgrade pip
  "$VENV/bin/pip" install -q -r "$REPO_ROOT/requirements-deploy.txt"
fi

mkdir -p "$STORAGE_DIR"

echo "[deploy-worker] REDIS_URL=$REDIS_URL REDIS_HOST=$REDIS_HOST"
echo "[deploy-worker] STORAGE_DIR=$STORAGE_DIR"
echo "[deploy-worker] deploy キューを待機します (Ctrl-C で停止)"
exec "$VENV/bin/rq" worker deploy --url "$REDIS_URL"
