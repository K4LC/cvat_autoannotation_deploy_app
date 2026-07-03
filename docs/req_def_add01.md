# 追加機能としての要件修正

## GPU対応設定の扱い

### 1. GPU対応の入力項目について

GPU対応の有無は、Webフォームでは入力させない。

ユーザーがCPU用かGPU用かを選択するのではなく、アプリケーションは常にCPU用とGPU用の両方の`function.yaml`を生成する。

---

### 2. 出力ファイル構成の変更

生成されるファイルは以下の5つとする。

```text
function.yaml
function-gpu.yaml
main.py
model.onnx
model_handler.py
```

zipを展開したときの構成は以下とする。

```text
<model_internal_name>/
├── function.yaml
├── function-gpu.yaml
├── main.py
├── model.onnx
└── model_handler.py
```

#### 2.1 function.yaml

CPU実行を前提としたNuclio/CVAT用設定ファイルとする。

#### 2.2 function-gpu.yaml

GPU実行を前提としたNuclio/CVAT用設定ファイルとする。

`function-gpu.yaml`は、骨格推定モデル用exampleをベースにしつつ、GPU対応に必要なデプロイ設定については、CVATの物体検出モデル用GPU対応exampleを参考にして調整する。

また、`function.yaml`はすでに最適化されている想定であり、example内に存在する`function-gpu.yaml.tpl`は未最適であるため、必要に応じて修正すること。

---

### 3. テンプレート調整方針

本アプリケーションでは、CPU用とGPU用の2種類の`function.yaml`を生成する。

```text
function.yaml      : CPU用
function-gpu.yaml  : GPU用
```

物体検出モデル用GPU exampleの設定をそのままコピーしないこと。

あくまで、骨格推定モデル用`function.yaml`に不足しているGPU実行関連の設定を補うための参考として使用する。

基本方針は以下とする。

```text
1. 骨格推定モデル用exampleの構造を優先する
2. CPU用設定としてfunction.yamlを生成する
3. GPU用設定としてfunction-gpu.yamlを生成する
4. GPU対応に必要な設定のみ、物体検出モデル用GPU対応exampleを参考に補う
5. 骨格推定モデル固有のラベル定義、keypoint定義、skeleton定義、後処理、CVAT返却形式は維持する
```

---

### 4. 入力フォームの更新

Webフォームに表示する項目は以下とする。

```text
作成者名
モデル表示名
SVGラベル名
SVGファイル
.ptファイル
```

以下の項目は表示しない。

```text
モデル内部名
ラベル一覧
GPU対応有無
CPU/GPU選択
confidence threshold
NMS threshold
image size
ONNX opset
```

---

### 5. 処理フローの更新

処理フローは以下とする。

```text
ユーザーがWebアプリにアクセス
↓
作成者名、モデル表示名、SVGラベル名、SVGファイル、.ptファイルを入力
↓
フォーム送信
↓
入力値を検証
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
zip化
↓
ジョブ状態をsuccessに更新
↓
ユーザーがzipをダウンロード
```

---

### 6. 更新後のMVP範囲

MVPで実装する範囲は以下とする。

```text
ローカルWeb画面
Docker Composeによる起動
作成者名入力
モデル表示名入力
SVGラベル名入力
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
zipダウンロード
Redisによるジョブ管理
進捗表示
複数人同時アクセス対応
```

あくまで機能の追加であるため、従来の機能はほぼすべて残した状態にすること。
