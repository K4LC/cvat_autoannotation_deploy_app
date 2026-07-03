# web / worker 共通イメージ (T-12)
FROM python:3.10-slim

# opencv / onnxruntime / ultralytics の実行時に必要な OS ライブラリ
RUN apt-get update && apt-get install --no-install-recommends -y \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# CPU 前提 (§10 / CPU固定方針) なので torch は CPU ホイールを先に入れて
# CUDA 版の巨大ダウンロードを避ける。ultralytics は既存の torch を再利用する。
RUN pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# アプリ本体とテンプレート
COPY app ./app
COPY templates ./templates

# app パッケージを import 可能にする (uvicorn / rq worker 双方で必要)
ENV PYTHONPATH=/app
# ログを即時フラッシュ (cleanup 等の常駐ログが docker logs に出るように)
ENV PYTHONUNBUFFERED=1
# 共有ストレージのマウント先 (§11.4 / §13)
ENV STORAGE_DIR=/storage

EXPOSE 8000

# 既定は web。worker は compose 側で command を上書きする。
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
