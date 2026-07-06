# 追加要件 02
# 全画面ドラッグ＆ドロップ対応・CVAT serverless配下への保存・自動デプロイ対応

## 1. 追加機能の概要

既存のCVAT向け骨格推定モデル自動デプロイファイル生成Webアプリに対して、以下の機能を追加する。

```text
画面全体へのSVG/.ptファイルドラッグ＆ドロップ対応
生成フォルダをCVATのserverless/mymodel配下へ保存
CPUまたはGPUのデプロイ対象をユーザーが選択
選択に応じてdeploy_cpu.shまたはdeploy_gpu.shを自動実行
自動デプロイに失敗した場合はログを表示・保存
```

本要件は既存機能への追加であり、以下の従来機能は維持する。

```text
ローカルWeb画面
Docker Composeによる起動
作成者名入力
モデル表示名入力
SVGラベル名入力
SVGファイルアップロード
.ptファイルアップロード
SVG解析
モデル内部名へのyyyymmddhhmm形式タイムスタンプ付与
.ptからmodel.onnxへの変換
CPU用function.yaml生成
GPU用function-gpu.yaml生成
main.py生成
model_handler.py生成
Redisによるジョブ管理
進捗表示
複数人同時アクセス対応
```

---

## 2. 全画面ドラッグ＆ドロップ対応

### 2.1 目的

ユーザーがSVGファイルおよび`.pt`ファイルをWeb画面へドラッグ＆ドロップする際、特定の小さなドロップエリアだけでなく、画面全体をドロップ対象として扱えるようにする。

これにより、ユーザーが直感的にファイルを投入できるようにする。

### 2.2 全画面ドロップ対象

Web画面全体をSVGファイルおよび`.pt`ファイルのドロップ対象とする。

ユーザーがブラウザ画面上にファイルをドラッグした場合、画面全体にドロップ可能であることを示すオーバーレイを表示する。

### 2.3 オーバーレイ表示

ファイルが画面上にドラッグされたら、以下のようなオーバーレイを画面全体に表示する。

表示例：

```text
ここにSVGファイルまたは.ptファイルをドロップ
```

または、

```text
SVG / PTファイルをドロップしてください
```

オーバーレイは以下の条件で表示・非表示を切り替える。

```text
dragenter: オーバーレイ表示
dragover: オーバーレイ表示を維持
dragleave: 画面外へ離れた場合に非表示
drop: ファイル受け取り後に非表示
```

### 2.4 ファイル種別判定

ドロップされたファイルは、拡張子またはMIME typeをもとに判定する。

対応するファイル：

```text
.svg
.pt
```

ドロップされたファイルが`.svg`の場合は、SVGファイル入力欄に反映する。

ドロップされたファイルが`.pt`の場合は、`.pt`ファイル入力欄に反映する。

### 2.5 複数ファイル同時ドロップ

ユーザーがSVGファイルと`.pt`ファイルを同時にドロップできるようにする。

例：

```text
model.svg
best.pt
```

この場合、アプリケーションはそれぞれを自動判定し、該当する入力欄へセットする。

### 2.6 不正ファイルの扱い

対応していない拡張子のファイルがドロップされた場合は、フォームに反映せず、画面上にエラーを表示する。

エラー例：

```text
対応していないファイル形式です。SVGファイルまたは.ptファイルを指定してください。
```

### 2.7 同種ファイルが複数ある場合

同じ種類のファイルが複数ドロップされた場合は、MVPでは最後に読み込まれたファイルを採用する。

例：

```text
a.svg
b.svg
```

この場合、`b.svg`をSVGファイルとして採用する。

必要に応じて、画面上に以下のような警告を表示してもよい。

```text
複数のSVGファイルが指定されたため、最後のファイルを使用します。
```

---

## 3. 入力フォームの更新

### 3.1 フォーム項目

Webフォームには以下を表示する。

```text
作成者名
モデル表示名
SVGラベル名
デプロイ対象
SVGファイル
.ptファイル
```

### 3.2 デプロイ対象

ユーザーは生成後に実行するデプロイスクリプトを選択できる。

MVPでは、CPUまたはGPUのどちらか一方のみを選択するラジオボタン方式を推奨する。

```text
デプロイ対象:
( ) CPU
( ) GPU
```

初期値はCPUとする。

### 3.3 保存先パス入力欄は表示しない

保存先は`.env`で指定するため、ユーザー入力フォームには保存先パス入力欄を表示しない。

以下の項目はフォームに表示しない。

```text
保存先パス
モデル内部名
ラベル一覧
GPU対応有無
confidence threshold
NMS threshold
image size
ONNX opset
```

### 3.4 ファイル選択とドラッグ＆ドロップの併用

ユーザーは以下のどちらの方法でもSVGファイルと`.pt`ファイルを指定できる。

```text
通常のファイル選択ボタン
画面全体へのドラッグ＆ドロップ
```

どちらの方法で指定しても、フォーム送信時の扱いは同じとする。

### 3.5 選択済みファイル名の表示

SVGファイルおよび`.pt`ファイルが選択またはドロップされたら、画面上にファイル名を表示する。

表示例：

```text
SVGファイル: model.svg
PTファイル: best.pt
```

---

## 4. CVAT保存先の方針

### 4.1 保存先の基本方針

生成されたフォルダは、zipとして保存・ダウンロードするのではなく、CVATのserverless配下へ通常フォルダとして保存する。

保存先は以下とする。

```text
<CVAT_BASE_PATH>/cvat/serverless/mymodel/<model_internal_name>/
```

例：

```text
/home/user/projects/cvat/serverless/mymodel/human-pose_202607041530/
```

### 4.2 CVAT_BASE_PATH

`CVAT_BASE_PATH`は、サーバ内かつDockerコンテナ外のローカルパスを指す。

ただし、Dockerコンテナ内から参照・書き込みできるように、Docker Composeでbind mountする。

---

## 5. .env設定

### 5.1 CVATルートパス

サーバ内かつDockerコンテナ外のローカルパスを`.env`で指定する。

例：

```env
CVAT_BASE_PATH=/home/user/projects
DEPLOY_TIMEOUT_SECONDS=600
```

この場合、実際に使用するCVAT関連パスは以下となる。

```text
CVATリポジトリ:
  /home/user/projects/cvat

生成フォルダ保存先:
  /home/user/projects/cvat/serverless/mymodel/

CPUデプロイスクリプト:
  /home/user/projects/cvat/serverless/deploy_cpu.sh

GPUデプロイスクリプト:
  /home/user/projects/cvat/serverless/deploy_gpu.sh
```

### 5.2 Dockerコンテナからの参照

WebアプリケーションはDockerコンテナ内で動作するため、Dockerコンテナ外のホスト側パスを直接参照することはできない。

そのため、`docker-compose.yml`で`.env`に指定したホスト側パスをコンテナへbind mountする必要がある。

MVPでは、ホスト側パスとコンテナ側パスを同一に見せる構成を推奨する。

例：

```yaml
services:
  web:
    volumes:
      - ${CVAT_BASE_PATH}:${CVAT_BASE_PATH}

  worker:
    volumes:
      - ${CVAT_BASE_PATH}:${CVAT_BASE_PATH}
```

この構成により、コンテナ内からも以下のパスでCVATリポジトリを参照できる。

```text
${CVAT_BASE_PATH}/cvat
```

### 5.3 Dockerソケットの扱い

`deploy_cpu.sh`や`deploy_gpu.sh`がDocker操作を行う場合、workerコンテナからホストのDockerへアクセスできる必要がある。

必要に応じて、workerサービスに以下のvolume mountを追加する。

```yaml
services:
  worker:
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
```

ただし、Dockerソケットのマウントは強い権限を持つため、ローカルネットワーク内の信頼できる環境でのみ使用する。

---

## 6. 出力ファイル構成

生成されるファイルは以下の5つとする。

```text
function.yaml
function-gpu.yaml
main.py
model.onnx
model_handler.py
```

保存先の構成は以下とする。

```text
${CVAT_BASE_PATH}/cvat/serverless/mymodel/
└── <model_internal_name>/
    ├── function.yaml
    ├── function-gpu.yaml
    ├── main.py
    ├── model.onnx
    └── model_handler.py
```

SVGファイル、`.pt`ファイル、README、deploy scriptは生成フォルダに含めない。

---

## 7. 保存処理

### 7.1 保存先ディレクトリ

Workerはファイル生成後、以下のパスへ生成フォルダを保存する。

```text
${CVAT_BASE_PATH}/cvat/serverless/mymodel/<model_internal_name>/
```

### 7.2 mymodelディレクトリ

以下のディレクトリが存在しない場合、アプリケーションが作成する。

```text
${CVAT_BASE_PATH}/cvat/serverless/mymodel/
```

### 7.3 同名フォルダが存在する場合

モデル内部名には`yyyymmddhhmm`形式のタイムスタンプが付与されるため、基本的には重複しにくい。

ただし、同じ分に同じモデルが複数回変換される可能性があるため、同名フォルダが存在する場合は安全な名前に変更する。

例：

```text
human-pose_202607041530
human-pose_202607041530_001
human-pose_202607041530_002
```

既存フォルダは上書きしない。

---

## 8. deploy script実行機能

### 8.1 目的

生成されたモデルフォルダをCVATのserverless配下へ保存した後、ユーザーが選択した対象に応じてCVATのdeploy scriptを実行する。

実行対象は以下とする。

```text
CPU選択時:
  ${CVAT_BASE_PATH}/cvat/serverless/deploy_cpu.sh ${CVAT_BASE_PATH}/cvat/serverless/mymodel/<model_internal_name>

GPU選択時:
  ${CVAT_BASE_PATH}/cvat/serverless/deploy_gpu.sh ${CVAT_BASE_PATH}/cvat/serverless/mymodel/<model_internal_name>
```

### 8.2 実行タイミング

deploy scriptは、以下の処理がすべて完了した後に実行する。

```text
.ptからmodel.onnxへの変換
function.yaml生成
function-gpu.yaml生成
main.py生成
model_handler.py生成
生成フォルダのmymodel配下への保存
```

### 8.3 実行ディレクトリ

deploy scriptは、以下のディレクトリをカレントディレクトリとして実行する。

```text
${CVAT_BASE_PATH}/cvat/serverless
```

例：

```bash
cd ${CVAT_BASE_PATH}/cvat/serverless
./deploy_cpu.sh ./mymodel/<model_internal_name>
```

または、

```bash
cd ${CVAT_BASE_PATH}/cvat/serverless
./deploy_gpu.sh ./mymodel/<model_internal_name>
```

### 8.4 実行方法

WorkerはPythonの`subprocess`等を用いてdeploy scriptを実行する。

deploy scriptの実行はWebプロセスではなくworkerが担当する。

理由：

```text
Webリクエストを長時間ブロックしない
ONNX変換・ファイル生成・保存・デプロイまでを1つのジョブとして扱いやすい
Redisのジョブ状態とログ管理を一元化できる
```

---

## 9. 自動デプロイ失敗時のログ取得

### 9.1 ログ取得方針

自動デプロイに失敗した場合、原因を確認できるように、deploy scriptのログを取得・保存・表示する。

Workerはdeploy script実行時に以下を取得する。

```text
標準出力 stdout
標準エラー stderr
終了コード return code
実行したスクリプトのパス
実行ディレクトリ
実行開始時刻
実行終了時刻
```

### 9.2 成功判定

deploy scriptの終了コードが`0`の場合、デプロイ成功とみなす。

ジョブ状態を`success`に変更する。

画面には以下を表示する。

```text
生成とデプロイが完了しました。
保存先: ${CVAT_BASE_PATH}/cvat/serverless/mymodel/<model_internal_name>
実行したスクリプト: deploy_cpu.sh
```

または、

```text
生成とデプロイが完了しました。
保存先: ${CVAT_BASE_PATH}/cvat/serverless/mymodel/<model_internal_name>
実行したスクリプト: deploy_gpu.sh
```

### 9.3 失敗判定

deploy scriptの終了コードが`0`以外の場合、デプロイ失敗とみなす。

ジョブ状態を`failed`に変更する。

画面には以下を表示する。

```text
デプロイに失敗しました。
deploy scriptのログを確認してください。
```

### 9.4 失敗時に表示する情報

デプロイ失敗時、画面上に以下を表示できるようにする。

```text
実行したdeploy script
終了コード
標準出力
標準エラー
ログの末尾
保存先フォルダパス
```

ログが長すぎる場合は、画面表示では末尾のみを表示してもよい。

例：

```text
最後の100行を表示
```

ただし、Redisまたはログファイルには可能な範囲で全体ログを保存する。

### 9.5 ログファイル保存

可能であれば、ジョブごとの一時ディレクトリにdeployログを保存する。

保存例：

```text
/storage/jobs/<job_id>/logs/deploy_stdout.log
/storage/jobs/<job_id>/logs/deploy_stderr.log
/storage/jobs/<job_id>/logs/deploy_result.json
```

`deploy_result.json`の例：

```json
{
  "script": "/home/user/projects/cvat/serverless/deploy_cpu.sh",
  "cwd": "/home/user/projects/cvat/serverless",
  "return_code": 1,
  "started_at": "2026-07-04T15:30:00+09:00",
  "finished_at": "2026-07-04T15:31:20+09:00",
  "stdout_log_path": "/storage/jobs/<job_id>/logs/deploy_stdout.log",
  "stderr_log_path": "/storage/jobs/<job_id>/logs/deploy_stderr.log"
}
```

### 9.6 タイムアウト

deploy scriptの実行には時間がかかる可能性がある。

MVPでは、deploy script実行にタイムアウトを設定する。

例：

```text
DEPLOY_TIMEOUT_SECONDS=600
```

タイムアウトした場合は、ジョブ状態を`failed`に変更し、画面にエラーを表示する。

エラー例：

```text
デプロイ処理がタイムアウトしました。
DEPLOY_TIMEOUT_SECONDSの設定を確認してください。
```

### 9.7 実行権限エラー

deploy scriptに実行権限がない場合は、ジョブ状態を`failed`に変更し、画面にエラーを表示する。

エラー例：

```text
deploy_cpu.shに実行権限がありません。
chmod +x を実行してください。
```

---

## 10. function.yaml / function-gpu.yamlの扱い

### 10.1 両方生成する

ユーザーがCPUまたはGPUのどちらを選択した場合でも、生成フォルダ内には常に以下の2つを含める。

```text
function.yaml
function-gpu.yaml
```

### 10.2 deploy scriptとの関係

CPUを選択した場合は、`deploy_cpu.sh`を実行する。

GPUを選択した場合は、`deploy_gpu.sh`を実行する。

生成フォルダには両方の設定ファイルを含めるが、実際にどちらの設定が使われるかは、CVAT側のdeploy scriptの仕様に従う。

### 10.3 GPU設定の調整

`function-gpu.yaml`は、骨格推定モデル用exampleをベースにしつつ、物体検出モデル用GPU exampleを参考にしてGPU実行に必要な設定を補う。

物体検出モデル用GPU exampleの設定をそのままコピーしないこと。

骨格推定モデル固有の以下は維持する。

```text
ラベル定義
keypoint定義
skeleton定義
model_handler.pyの後処理
CVATへの返却形式
```

---

## 11. Redisジョブ情報の更新

Redisに保存するジョブ情報に、CVATパス、保存先フォルダ、デプロイ対象、デプロイログ情報を追加する。

例：

```json
{
  "job_id": "uuid",
  "status": "queued",
  "author": "作成者名",
  "display_name": "モデル表示名",
  "base_model_name": "svgから取得したモデル名",
  "function_name": "タイムスタンプ付きモデル内部名",
  "svg_label_name": "ユーザーが入力したSVGラベル名",
  "pt_path": "/storage/jobs/<job_id>/input/model.pt",
  "svg_path": "/storage/jobs/<job_id>/input/model.svg",
  "created_timestamp": "202607041530",
  "cvat_base_path": "/home/user/projects",
  "exported_folder_path": "/home/user/projects/cvat/serverless/mymodel/human-pose_202607041530",
  "deploy_target": "cpu",
  "deploy_script_path": "/home/user/projects/cvat/serverless/deploy_cpu.sh",
  "deploy_return_code": null,
  "deploy_stdout_tail": "",
  "deploy_stderr_tail": "",
  "deploy_stdout_log_path": "/storage/jobs/<job_id>/logs/deploy_stdout.log",
  "deploy_stderr_log_path": "/storage/jobs/<job_id>/logs/deploy_stderr.log",
  "deploy_result_path": "/storage/jobs/<job_id>/logs/deploy_result.json"
}
```

---

## 12. ジョブ状態の更新

ジョブ状態に以下を追加する。

```text
saving_to_cvat
deploying
deploy_success
deploy_failed
```

状態遷移例：

```text
queued
↓
running
↓
parsing_svg
↓
exporting_onnx
↓
generating_files
↓
saving_to_cvat
↓
deploying
↓
success
```

失敗時：

```text
saving_to_cvat
↓
failed
```

または、

```text
deploying
↓
failed
```

---

## 13. 処理フローの更新

処理フローは以下とする。

```text
ユーザーがWebアプリにアクセス
↓
作成者名、モデル表示名、SVGラベル名、デプロイ対象を入力
↓
SVGファイルと.ptファイルを選択、または画面全体へドラッグ＆ドロップ
↓
フォーム送信
↓
入力値を検証
↓
.envからCVAT_BASE_PATHを取得
↓
${CVAT_BASE_PATH}/cvat/serverless の存在を確認
↓
${CVAT_BASE_PATH}/cvat/serverless/deploy_cpu.sh または deploy_gpu.sh の存在を確認
↓
SVGを解析し、モデル内部名の元になる名前と骨格情報を取得
↓
現在時刻からyyyymmddhhmm形式のタイムスタンプを生成
↓
モデル内部名にタイムスタンプを付与
↓
ジョブIDを発行
↓
アップロードファイルをジョブごとの一時ディレクトリに保存
↓
Redisにジョブを登録
↓
Workerがジョブを取得
↓
.ptをmodel.onnxへ変換
↓
CPU用のfunction.yamlを生成
↓
GPU用のfunction-gpu.yamlを生成
↓
SVGラベル名と骨格情報を反映してmain.py/model_handler.pyを生成
↓
5ファイルを1つのフォルダにまとめる
↓
${CVAT_BASE_PATH}/cvat/serverless/mymodel/配下へ保存
↓
ユーザーが選択したdeploy scriptを実行
↓
deploy scriptのstdout/stderr/return codeを保存
↓
成功した場合はジョブ状態をsuccessに更新
↓
失敗した場合はジョブ状態をfailedに更新
↓
画面に結果とログを表示
```

---

## 14. Docker Compose要件の更新

### 14.1 .envの読み込み

`docker-compose.yml`は`.env`から`CVAT_BASE_PATH`を読み込む。

例：

```env
CVAT_BASE_PATH=/home/user/projects
DEPLOY_TIMEOUT_SECONDS=600
```

### 14.2 volume mount

workerおよびwebからCVATリポジトリを参照できるように、`CVAT_BASE_PATH`をbind mountする。

例：

```yaml
services:
  web:
    volumes:
      - ${CVAT_BASE_PATH}:${CVAT_BASE_PATH}

  worker:
    volumes:
      - ${CVAT_BASE_PATH}:${CVAT_BASE_PATH}
      - /var/run/docker.sock:/var/run/docker.sock
```

### 14.3 deploy実行サービス

deploy scriptの実行はworkerが担当する。

### 14.4 同時デプロイの制御

複数ユーザーが同時にdeploy scriptを実行すると競合する可能性がある。

MVPでは、worker数を1にすることでデプロイ処理を直列化する。

または、deploy実行部分にRedis lockを使用して、同時デプロイを防止する。

---

## 15. 画面要件の更新

### 15.1 入力フォーム

Webフォームには以下を表示する。

```text
作成者名
モデル表示名
SVGラベル名
デプロイ対象
SVGファイル
.ptファイル
```

### 15.2 パス表示

`.env`から読み込まれたCVAT保存先の概要を画面上に表示してもよい。

例：

```text
保存先: ${CVAT_BASE_PATH}/cvat/serverless/mymodel/
```

ただし、ユーザーが画面上から保存先を変更する機能は不要とする。

### 15.3 完了画面

完了画面には以下を表示する。

```text
生成結果
保存先フォルダパス
実行したdeploy script
deploy結果
deployログ
```

### 15.4 失敗画面

デプロイに失敗した場合、失敗画面または進捗画面に以下を表示する。

```text
エラーメッセージ
実行したdeploy script
終了コード
標準出力の末尾
標準エラーの末尾
保存先フォルダパス
```

---

## 16. 更新後のMVP範囲

MVPで実装する範囲は以下とする。

```text
ローカルWeb画面
Docker Composeによる起動
.envによるCVAT_BASE_PATH指定
画面全体ドラッグ＆ドロップ対応
作成者名入力
モデル表示名入力
SVGラベル名入力
デプロイ対象CPU/GPU選択
SVGファイルアップロード
.ptファイルアップロード
SVGからモデル内部名の元になる名前を自動取得
SVGから骨格情報・keypoint情報・skeleton情報を自動取得
モデル内部名へのyyyymmddhhmm形式タイムスタンプ付与
.ptからmodel.onnxへの変換
CPU用function.yaml生成
GPU用function-gpu.yaml生成
main.py生成
model_handler.py生成
5ファイル入りフォルダ作成
${CVAT_BASE_PATH}/cvat/serverless/mymodel/配下への保存
deploy_cpu.shまたはdeploy_gpu.shの実行
自動デプロイ失敗時のログ取得・表示
Redisによるジョブ管理
進捗表示
複数人同時アクセス対応
```

MVPでは以下は実装しない。

```text
保存先パスの画面入力
モデル内部名の手動入力
ラベル一覧の手動入力
confidence thresholdの手動入力
NMS thresholdの手動入力
image sizeの手動入力
ONNX opsetの手動入力
icon.svg生成
README.md生成
ユーザーアカウント機能
生成履歴の永続保存
外部公開対応
物体検出モデル対応
segmentation対応
```

---

## 17. 更新後の受け入れ条件

### AC-01 全画面ドラッグ＆ドロップ

SVGファイルまたは`.pt`ファイルを画面全体にドラッグ＆ドロップできること。

### AC-02 ドラッグ中のオーバーレイ

ファイルを画面上にドラッグした際、画面全体にドロップ可能であることを示すオーバーレイが表示されること。

### AC-03 ファイル種別自動判定

ドロップされたファイルが`.svg`の場合はSVG入力として扱われ、`.pt`の場合は`.pt`入力として扱われること。

### AC-04 複数ファイル同時ドロップ

SVGファイルと`.pt`ファイルを同時にドロップした場合、それぞれが正しい入力欄に反映されること。

### AC-05 .envによるCVAT_BASE_PATH指定

`.env`に指定された`CVAT_BASE_PATH`をアプリケーションが読み込めること。

### AC-06 mymodel配下への保存

生成されたモデルフォルダが以下に保存されること。

```text
${CVAT_BASE_PATH}/cvat/serverless/mymodel/<model_internal_name>/
```

### AC-07 出力フォルダ構成

保存先に以下の構成でファイルが保存されること。

```text
${CVAT_BASE_PATH}/cvat/serverless/mymodel/<model_internal_name>/
├── function.yaml
├── function-gpu.yaml
├── main.py
├── model.onnx
└── model_handler.py
```

### AC-08 デプロイ対象選択

Webフォーム上でCPUまたはGPUのどちらをデプロイするか選択できること。

### AC-09 CPU選択時

CPUを選択した場合、以下のスクリプトが実行されること。

```text
${CVAT_BASE_PATH}/cvat/serverless/deploy_cpu.sh
```

### AC-10 GPU選択時

GPUを選択した場合、以下のスクリプトが実行されること。

```text
${CVAT_BASE_PATH}/cvat/serverless/deploy_gpu.sh
```

### AC-11 deployログ表示

deploy scriptの標準出力および標準エラーがジョブログとして保存され、画面から確認できること。

### AC-12 deploy失敗時

deploy scriptが失敗した場合、ジョブ状態が`failed`になり、画面上にエラーとログが表示されること。

### AC-13 deploy失敗ログの内容

deploy失敗時、以下の情報が確認できること。

```text
実行したdeploy script
終了コード
標準出力
標準エラー
ログの末尾
保存先フォルダパス
```

### AC-14 Docker外ホストパスへの保存

保存先はDockerコンテナ内の一時領域ではなく、bind mountされたホスト側CVATリポジトリ配下であること。

### AC-15 Webリクエストをブロックしない

deploy scriptの実行はWebプロセスではなくworkerで行われること。

### AC-16 既存フォルダを上書きしない

保存先に同名フォルダが存在する場合、既存フォルダを上書きせず、連番などを付与して安全なフォルダ名で保存すること。

---

## 18. 実装時の注意

### 18.1 Dockerコンテナ外のホストパス

`CVAT_BASE_PATH`はサーバ内かつDockerコンテナ外のローカルパスである。

ただし、Dockerコンテナ内からそのパスを参照するためには、`docker-compose.yml`でbind mountが必要である。

### 18.2 deploy scriptの副作用

`deploy_cpu.sh`や`deploy_gpu.sh`は、CVAT/Nuclio環境に対して実際にデプロイ操作を行う。

そのため、実行前に以下を確認すること。

```text
CVATが起動していること
Nuclioが利用可能であること
deploy scriptが存在すること
deploy scriptに実行権限があること
workerからDockerまたはNuclioにアクセスできること
```

### 18.3 Dockerソケットの権限

workerコンテナに`/var/run/docker.sock`をマウントする場合、workerはホストDockerを操作できる強い権限を持つ。

外部公開環境では使用しない。

### 18.4 同時デプロイの制御

MVPでは、worker数を1にすることでデプロイ処理を直列化する。

将来的にworker数を増やす場合は、deploy script実行部分にRedis lock等を導入する。

### 18.5 function.yamlとfunction-gpu.yaml

生成フォルダには常に`function.yaml`と`function-gpu.yaml`の両方を含める。

ただし、実行されるdeploy scriptはユーザーが選択したCPU/GPUに応じて1つとする。

### 18.6 旧zip機能との関係

本要件では、zipダウンロードよりもCVAT serverless配下への保存とdeploy script実行を優先する。

MVPではzip生成・zipダウンロードは必須ではない。

### 18.7 自動デプロイ失敗時の扱い

自動デプロイに失敗しても、生成フォルダ自体はCVAT serverless配下に残る可能性がある。

そのため、失敗時には以下を画面に表示する。

```text
生成フォルダの保存先
実行したdeploy script
deploy失敗ログ
再実行時の注意
```
