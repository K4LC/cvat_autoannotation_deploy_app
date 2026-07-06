# DeepLabCut 3.x (PyTorch) 単一動物モデルの nuclio 推論ハンドラ。
# ONNX 変換はせず、pytorch_config.yaml から DLC の PoseModel を構築して直接推論する。
# backbone(ResNet/HRNet 等)・output_stride・keypoint 数はすべて config 由来で、
# ハードコードしない（別 backbone でも同じハンドラで動く）。
#
# 注意: DLC 3.x の推論 API (PoseModel.build / get_predictions / poses キー) は
# 導入する deeplabcut のバージョンで確認・調整すること。

import numpy as np
import yaml
import torch

try:
    from deeplabcut.pose_estimation_pytorch.models import PoseModel
except Exception as _e:  # import 失敗は init で明示的に知らせる
    PoseModel = None
    _IMPORT_ERROR = _e
else:
    _IMPORT_ERROR = None

# ImageNet 正規化 (data.inference.normalize_images=true のとき使用)
IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


class ModelHandler:
    def __init__(self, labels):
        if PoseModel is None:
            raise RuntimeError(f"deeplabcut(pytorch) を import できません: {_IMPORT_ERROR}")
        self.labels = labels

        with open("{{ dlcConfig }}", "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        self.cfg = cfg

        # 実 bodyparts（末尾の空文字を除外）。keypoint 数は config 由来。
        meta = cfg.get("metadata", {}) or {}
        bodyparts = [b for b in (meta.get("bodyparts") or []) if b]
        self.num_bodyparts = len(bodyparts)

        inference_cfg = (cfg.get("data", {}) or {}).get("inference", {}) or {}
        self.normalize = bool(inference_cfg.get("normalize_images", True))

        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model = PoseModel.build(cfg["model"])
        snapshot = torch.load("{{ modelPt }}", map_location=self.device)
        state = snapshot.get("model", snapshot) if isinstance(snapshot, dict) else snapshot
        self.model.load_state_dict(state)
        self.model.to(self.device)
        self.model.eval()

    def _preprocess(self, image_rgb):
        img = image_rgb.astype(np.float32) / 255.0
        if self.normalize:
            img = (img - IMAGENET_MEAN) / IMAGENET_STD
        chw = np.ascontiguousarray(img.transpose(2, 0, 1))
        return torch.from_numpy(chw).unsqueeze(0).to(self.device)

    def _predict(self, x):
        # DLC 3.x: モデル出力を predictor でデコードし (batch, num_animals, num_kpts, 3)。
        with torch.no_grad():
            outputs = self.model(x)
            preds = self.model.get_predictions(outputs)
        poses = preds["bodypart"]["poses"]
        return poses.detach().cpu().numpy()

    def infer(self, image, threshold):
        image = np.array(image)  # PIL(RGB) -> HxWx3
        x = self._preprocess(image)
        poses = self._predict(x)

        arr = poses[0]
        if arr.ndim == 3:            # (num_animals, num_kpts, 3) -> 単一動物
            arr = arr[0]
        arr = arr[: self.num_bodyparts]  # 実 bodyparts のみ採用

        keypoints = arr[:, :2]
        scores = arr[:, 2]
        mean_score = float(np.mean(scores)) if len(scores) else 0.0

        results = []
        for label in self.labels:  # SVG 由来のラベル/サブラベル (bodyparts 順)
            skeleton = {
                "confidence": str(mean_score),
                "label": label["name"],
                "type": "skeleton",
                "elements": [
                    {
                        "label": element["name"],
                        "type": "points",
                        "outside": 0 if scores[element["id"]] >= threshold else 1,
                        "points": [
                            float(keypoints[element["id"]][0]),
                            float(keypoints[element["id"]][1]),
                        ],
                        "confidence": str(float(scores[element["id"]])),
                    }
                    for element in label["sublabels"]
                ],
            }
            # 全部 outside なら追加しない
            if not all(e["outside"] for e in skeleton["elements"]):
                results.append(skeleton)

        return results
