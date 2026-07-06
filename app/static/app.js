// フロントエンド制御 (T-11 / req_add02 §2・§15)
// フォーム送信 -> POST /jobs -> GET /jobs/{id} をポーリング -> 進捗表示 ->
// 完了でデプロイ結果/ダウンロード / 失敗でエラー・ログ表示 (§F-07 / §18)。
// 加えて、画面全体へのドラッグ&ドロップでファイルを投入できる (req_add02 §2)。

"use strict";

const POLL_INTERVAL_MS = 1500;

const form = document.getElementById("job-form");
const formSection = document.getElementById("form-section");
const progressSection = document.getElementById("progress-section");
const formError = document.getElementById("form-error");
const submitBtn = document.getElementById("submit-btn");

const svgInput = document.getElementById("svg");
const ptInput = document.getElementById("pt");
const svgFilename = document.getElementById("svg-filename");
const ptFilename = document.getElementById("pt-filename");
const dropOverlay = document.getElementById("drop-overlay");
const dropNotice = document.getElementById("drop-notice");

// DLC 関連 (モデル種別で表示切替)
const dlcConfigInput = document.getElementById("dlc_config");
const dlcConfigField = document.getElementById("dlc-config-field");
const dlcConfigFilename = document.getElementById("dlc-config-filename");
const dlcHint = document.getElementById("dlc-hint");

let pollTimer = null;

// 選択中のモデル種別が DLC か。
function isDlcSelected() {
  const el = document.querySelector('input[name="model_type"]:checked');
  return el && el.value === "dlc";
}

// モデル種別の切替で DLC 設定欄の表示/必須を更新する。
function updateModelTypeUI() {
  const dlc = isDlcSelected();
  dlcConfigField.hidden = !dlc;
  dlcHint.hidden = !dlc;
  dlcConfigInput.required = dlc;
  if (!dlc) {
    // YOLO に戻したら DLC 設定はクリア
    dlcConfigInput.value = "";
    dlcConfigFilename.hidden = true;
  }
}

document.querySelectorAll('input[name="model_type"]').forEach((el) => {
  el.addEventListener("change", updateModelTypeUI);
});
updateModelTypeUI();

// ------------------------------------------------------------------ フォーム送信
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

// ------------------------------------------------------- ファイル選択 / D&D 共通
// 拡張子から入力欄を判定する (req_add02 §2.4)。対応外は null。
// .yaml/.yml は DLC 選択時のみ DLC 設定欄に割り当てる。
function inputForFile(file) {
  const name = (file.name || "").toLowerCase();
  if (name.endsWith(".svg")) return svgInput;
  if (name.endsWith(".pt")) return ptInput;
  if ((name.endsWith(".yaml") || name.endsWith(".yml")) && isDlcSelected()) return dlcConfigInput;
  return null;
}

// DataTransfer を使って file input に File をセットする (§2.4 / §3.4)。
function assignFile(input, file) {
  const dt = new DataTransfer();
  dt.items.add(file);
  input.files = dt.files;
  updateFilenameDisplay();
}

// 選択中ファイル名を表示する (§3.5)。
function updateFilenameDisplay() {
  renderFilename(svgInput, svgFilename, "SVGファイル");
  renderFilename(ptInput, ptFilename, "PTファイル");
  renderFilename(dlcConfigInput, dlcConfigFilename, "DLC設定");
}

function renderFilename(input, el, label) {
  if (input.files && input.files.length > 0) {
    el.textContent = label + ": " + input.files[0].name;
    el.hidden = false;
  } else {
    el.hidden = true;
  }
}

// 複数ファイルを種別ごとに振り分ける (§2.5 / §2.6 / §2.7)。
function handleDroppedFiles(fileList) {
  const files = Array.from(fileList || []);
  if (files.length === 0) return;

  const byType = { svg: [], pt: [], yaml: [], invalid: [] };
  for (const file of files) {
    const input = inputForFile(file);
    if (input === svgInput) byType.svg.push(file);
    else if (input === ptInput) byType.pt.push(file);
    else if (input === dlcConfigInput) byType.yaml.push(file);
    else byType.invalid.push(file);
  }

  const notices = [];
  // 同種が複数なら最後を採用し警告 (§2.7)
  if (byType.svg.length > 0) {
    assignFile(svgInput, byType.svg[byType.svg.length - 1]);
    if (byType.svg.length > 1) notices.push("複数のSVGファイルが指定されたため、最後のファイルを使用します。");
  }
  if (byType.pt.length > 0) {
    assignFile(ptInput, byType.pt[byType.pt.length - 1]);
    if (byType.pt.length > 1) notices.push("複数の.ptファイルが指定されたため、最後のファイルを使用します。");
  }
  if (byType.yaml.length > 0) {
    assignFile(dlcConfigInput, byType.yaml[byType.yaml.length - 1]);
    if (byType.yaml.length > 1) notices.push("複数の設定ファイルが指定されたため、最後のファイルを使用します。");
  }

  if (byType.invalid.length > 0) {
    // 対応外は反映せずエラー表示 (§2.6)
    const msg = isDlcSelected()
      ? "対応していないファイル形式です。SVG / .pt / DLC設定(.yaml) を指定してください。"
      : "対応していないファイル形式です。SVGファイルまたは.ptファイルを指定してください。";
    showFormError(msg);
  } else {
    formError.hidden = true;
  }

  if (notices.length > 0) {
    dropNotice.textContent = notices.join(" ");
    dropNotice.hidden = false;
  } else {
    dropNotice.hidden = true;
  }
}

// ファイル選択ボタンからの選択でもファイル名を表示 (§3.5)
svgInput.addEventListener("change", updateFilenameDisplay);
ptInput.addEventListener("change", updateFilenameDisplay);
dlcConfigInput.addEventListener("change", updateFilenameDisplay);

// -------------------------------------------------------- 全画面ドラッグ&ドロップ
// dragenter/dragleave はネスト要素間でも発火するため、カウンタで画面外離脱を判定する。
let dragDepth = 0;

function showOverlay() {
  dropOverlay.hidden = false;
}
function hideOverlay() {
  dropOverlay.hidden = true;
}

window.addEventListener("dragenter", (e) => {
  if (!hasFiles(e)) return;
  e.preventDefault();
  dragDepth++;
  showOverlay();
});

window.addEventListener("dragover", (e) => {
  if (!hasFiles(e)) return;
  e.preventDefault(); // これがないと drop が発火しない
  showOverlay();
});

window.addEventListener("dragleave", (e) => {
  if (!hasFiles(e)) return;
  e.preventDefault();
  dragDepth = Math.max(0, dragDepth - 1);
  if (dragDepth === 0) hideOverlay();
});

window.addEventListener("drop", (e) => {
  e.preventDefault(); // ブラウザがファイルを開くのを防ぐ
  dragDepth = 0;
  hideOverlay();
  if (e.dataTransfer && e.dataTransfer.files) {
    handleDroppedFiles(e.dataTransfer.files);
  }
});

// ドラッグ中の内容がファイルかどうか (テキスト選択のドラッグ等を無視)。
function hasFiles(e) {
  const dt = e.dataTransfer;
  if (!dt) return false;
  return Array.from(dt.types || []).includes("Files");
}

// ----------------------------------------------------------------- 進捗ポーリング
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

// ----------------------------------------------------------------- 完了 / 失敗
function finishSuccess(state) {
  stopPolling();

  // CVAT 保存 + 自動デプロイ運用時はデプロイ結果を表示 (§15.3)
  if (state.exported_folder_path) {
    setText("exported-path", state.exported_folder_path);
    setText("deploy-script", scriptLabel(state));
    setText("deploy-stdout", state.deploy_stdout_tail || "（出力なし）");
    setText("deploy-stderr", state.deploy_stderr_tail || "（出力なし）");
    document.getElementById("deploy-info").hidden = false;
  }

  // zip 併用: download_url があるときだけダウンロードボタンを出す
  const link = document.getElementById("download-link");
  if (state.download_url) {
    link.href = state.download_url;
    link.hidden = false;
  } else {
    link.hidden = true;
  }

  document.getElementById("result-success").hidden = false;
  showRestart();
}

function finishError(state) {
  stopPolling();
  setText(
    "result-error-message",
    "エラー: " + (state.error || state.message || "生成に失敗しました")
  );

  // デプロイ失敗時は詳細も表示 (§15.4 / §9.4)
  const hasDeployInfo =
    state.exported_folder_path ||
    state.deploy_script_path ||
    state.deploy_return_code !== null;
  if (hasDeployInfo) {
    setText("err-deploy-script", scriptLabel(state));
    setText(
      "err-return-code",
      state.deploy_return_code === null || state.deploy_return_code === undefined
        ? "（なし）"
        : String(state.deploy_return_code)
    );
    setText("err-exported-path", state.exported_folder_path || "（保存前に失敗）");
    document.getElementById("deploy-error-meta").hidden = false;

    setText("err-deploy-stdout", state.deploy_stdout_tail || "（出力なし）");
    setText("err-deploy-stderr", state.deploy_stderr_tail || "（出力なし）");
    document.getElementById("err-log-block").hidden = false;
  }

  document.getElementById("result-error").hidden = false;
  showRestart();
}

function finishExpired() {
  stopPolling();
  setText("result-error-message", "このジョブは期限切れです。最初からやり直してください。");
  document.getElementById("result-error").hidden = false;
  showRestart();
}

// deploy script のファイル名（パスの末尾）+ 対象を表示用に整形。
function scriptLabel(state) {
  const path = state.deploy_script_path || "";
  const base = path.split(/[\\/]/).pop();
  const target = state.deploy_target ? " (" + state.deploy_target.toUpperCase() + ")" : "";
  return base ? base + target : "-";
}

function setText(id, text) {
  document.getElementById(id).textContent = text;
}

function showRestart() {
  const btn = document.getElementById("restart-btn");
  btn.hidden = false;
  btn.onclick = () => location.reload();
}
