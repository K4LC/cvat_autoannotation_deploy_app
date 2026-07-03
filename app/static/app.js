// フロントエンド制御 (T-11)
// フォーム送信 -> POST /jobs -> GET /jobs/{id} をポーリング -> 進捗表示 ->
// 完了でダウンロードボタン / 失敗でエラー表示 (§F-07 / §18)。

"use strict";

const POLL_INTERVAL_MS = 1500;

const form = document.getElementById("job-form");
const formSection = document.getElementById("form-section");
const progressSection = document.getElementById("progress-section");
const formError = document.getElementById("form-error");
const submitBtn = document.getElementById("submit-btn");

let pollTimer = null;

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  formError.hidden = true;
  submitBtn.disabled = true;

  const formData = new FormData(form);
  const displayName = formData.get("display_name");

  try {
    const res = await fetch("/jobs", { method: "POST", body: formData });
    const data = await res.json();

    if (!res.ok) {
      // 入力検証エラーなどはフォーム上に表示し、再入力できるようにする
      showFormError(data.detail || "送信に失敗しました");
      return;
    }
    startProgress(data.job_id, displayName, data.status_url);
  } catch (err) {
    showFormError("通信エラーが発生しました: " + err);
  }
});

function showFormError(message) {
  formError.textContent = message;
  formError.hidden = false;
  submitBtn.disabled = false;
}

function startProgress(jobId, displayName, statusUrl) {
  formSection.hidden = true;
  progressSection.hidden = false;
  document.getElementById("job-id").textContent = jobId;
  document.getElementById("model-name").textContent = displayName;

  poll(statusUrl);
  pollTimer = setInterval(() => poll(statusUrl), POLL_INTERVAL_MS);
}

async function poll(statusUrl) {
  try {
    const res = await fetch(statusUrl);
    if (!res.ok) return; // 一時的なエラーは次のポーリングで回復
    const state = await res.json();
    updateProgress(state);

    if (state.status === "success") {
      finishSuccess(state);
    } else if (state.status === "failed") {
      finishError(state);
    } else if (state.status === "expired") {
      finishExpired();
    }
  } catch (err) {
    // ネットワークの一時障害は無視して次回に任せる
  }
}

function updateProgress(state) {
  document.getElementById("status-label").textContent =
    state.label_ja || state.status;
  document.getElementById("progress-fill").style.width =
    (state.progress || 0) + "%";
  document.getElementById("progress-message").textContent =
    state.message || "";
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

function finishSuccess(state) {
  stopPolling();
  const link = document.getElementById("download-link");
  link.href = state.download_url;
  document.getElementById("result-success").hidden = false;
  showRestart();
}

function finishError(state) {
  stopPolling();
  const box = document.getElementById("result-error");
  box.textContent = "エラー: " + (state.error || state.message || "生成に失敗しました");
  box.hidden = false;
  showRestart();
}

function finishExpired() {
  stopPolling();
  const box = document.getElementById("result-error");
  box.textContent = "このジョブは期限切れです。最初からやり直してください。";
  box.hidden = false;
  showRestart();
}

function showRestart() {
  const btn = document.getElementById("restart-btn");
  btn.hidden = false;
  btn.onclick = () => location.reload();
}
