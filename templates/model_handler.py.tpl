# Copyright (C) CVAT.ai Corporation
#
# SPDX-License-Identifier: MIT

import cv2
import numpy as np
import onnxruntime as ort


class ModelHandler:
    def __init__(self, labels):
        self.model = None
        self.load_network(model="{{ modelOnnx }}") # 用意したモデルに変更
        self.labels = labels

    def load_network(self, model):
        device = ort.get_device()
        cuda = True if device == "GPU" else False
        try:
            providers = (
                ["CUDAExecutionProvider", "CPUExecutionProvider"]
                if cuda
                else ["CPUExecutionProvider"]
            )
            so = ort.SessionOptions()
            so.log_severity_level = 3

            self.model = ort.InferenceSession(model, providers=providers, sess_options=so)
            self.output_details = [i.name for i in self.model.get_outputs()]
            self.input_details = [i.name for i in self.model.get_inputs()]
        except Exception as e:
            raise Exception(f"Cannot load model {model}: {e}")

    def letterbox(
        self, im, new_shape=(640, 640), color=(114, 114, 114), auto=True, scaleup=True, stride=32
    ):
        # Resize and pad image while meeting stride-multiple constraints
        shape = im.shape[:2]  # current shape [height, width]
        if isinstance(new_shape, int):
            new_shape = (new_shape, new_shape)

        # Scale ratio (new / old)
        r = min(new_shape[0] / shape[0], new_shape[1] / shape[1])
        if not scaleup:  # only scale down, do not scale up (for better val mAP)
            r = min(r, 1.0)

        # Compute padding
        new_unpad = int(round(shape[1] * r)), int(round(shape[0] * r))
        dw, dh = new_shape[1] - new_unpad[0], new_shape[0] - new_unpad[1]  # wh padding

        if auto:  # minimum rectangle
            dw, dh = np.mod(dw, stride), np.mod(dh, stride)  # wh padding

        dw /= 2  # divide padding into 2 sides
        dh /= 2

        if shape[::-1] != new_unpad:  # resize
            im = cv2.resize(im, new_unpad, interpolation=cv2.INTER_LINEAR)
        top, bottom = int(round(dh - 0.1)), int(round(dh + 0.1))
        left, right = int(round(dw - 0.1)), int(round(dw + 0.1))
        im = cv2.copyMakeBorder(
            im, top, bottom, left, right, cv2.BORDER_CONSTANT, value=color
        )  # add border
        return im, r, (dw, dh)

    def _infer(self, inputs: np.ndarray):
        img = cv2.cvtColor(inputs, cv2.COLOR_BGR2RGB)
        image = img.copy()
        image, ratio, dwdh = self.letterbox(image, auto=False)

        image = image.transpose((2, 0, 1))
        image = np.expand_dims(image, 0)
        image = np.ascontiguousarray(image)

        im = image.astype(np.float32) / 255.0

        inp = {self.input_details[0]: im}
        outputs = self.model.run(self.output_details, inp)
        pred = outputs[0]  # YOLOv8-pose の生出力 (1, 4+1+kpt*3, N) を想定

        # 初回のみ実際の出力形状をログに出して形式の食い違いを確認できるようにする
        if not getattr(self, "_shape_logged", False):
            print("ONNX outputs:", [o.shape for o in outputs])
            self._shape_logged = True

        # (1, C, N) -> (N, C) に整える（channels-first で来る想定）
        pred = np.squeeze(pred, 0)
        if pred.shape[0] < pred.shape[1]:
            pred = pred.T

        num_cols = pred.shape[1]
        num_kpts = (num_cols - 5) // 3
        if num_kpts <= 0 or (num_cols - 5) % 3 != 0:
            raise ValueError(
                f"unexpected ONNX output shape {outputs[0].shape}. "
                "nms=False の生出力 (1, 4+1+kpt*3, N) 形式を想定しています。"
            )

        boxes_xywh = pred[:, :4]           # cx, cy, w, h (letterbox 640 空間)
        obj_conf = pred[:, 4]              # 物体信頼度（sigmoid 済み）
        kpts_all = pred[:, 5:].reshape(-1, num_kpts, 3)  # (M, K, [x, y, score])

        # 信頼度で足切り
        mask = obj_conf >= 0.25
        boxes_xywh, obj_conf, kpts_all = boxes_xywh[mask], obj_conf[mask], kpts_all[mask]
        if len(boxes_xywh) == 0:
            return []

        # cx,cy,w,h -> x1,y1,x2,y2
        cx, cy, w, h = boxes_xywh[:, 0], boxes_xywh[:, 1], boxes_xywh[:, 2], boxes_xywh[:, 3]
        xyxy = np.stack([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], axis=1)

        # NMS（クラスは1種の想定）
        nms_boxes = [
            [float(x1), float(y1), float(x2 - x1), float(y2 - y1)]
            for x1, y1, x2, y2 in xyxy
        ]
        keep = cv2.dnn.NMSBoxes(nms_boxes, obj_conf.tolist(), 0.25, 0.45)
        if len(keep) == 0:
            return []
        keep = np.array(keep).flatten()

        dw, dh = dwdh
        results = []
        for i in keep:
            # bbox を letterbox から元画像座標へ戻す
            box = xyxy[i].copy()
            box[[0, 2]] -= dw
            box[[1, 3]] -= dh
            box /= ratio

            # keypoints も同様に戻す
            kp = kpts_all[i].copy()
            kp[:, 0] -= dw
            kp[:, 1] -= dh
            kp[:, :2] /= ratio

            results.append(
                {
                    "bbox": box,
                    "bbox_score": float(obj_conf[i]),
                    "class_id": 0,
                    "keypoints": kp[:, :2],
                    "keypoint_scores": kp[:, 2],
                }
            )

        return results

    def infer(self, image, threshold):
        image = np.array(image)
        image = image[:, :, ::-1].copy()

        detections = self._infer(image)
        results = []

        for pred_instance in detections:
            keypoints = pred_instance["keypoints"]
            keypoint_scores = pred_instance["keypoint_scores"]

            for label in self.labels:  # context.user_data.labels相当
                skeleton = {
                    "confidence": str(pred_instance["bbox_score"]),
                    "label": label["name"],
                    "type": "skeleton",
                    "elements": [
                        {
                            "label": element["name"],
                            "type": "points",
                            "outside": 0
                            if keypoint_scores[element["id"]] >= threshold
                            else 1,
                            "points": [
                                float(keypoints[element["id"]][0]),
                                float(keypoints[element["id"]][1]),
                            ],
                            "confidence": str(
                                keypoint_scores[element["id"]]
                            ),
                        }
                        for element in label["sublabels"]
                    ],
                }

                # 全部 outside なら追加しない
                if not all(e["outside"] for e in skeleton["elements"]):
                    results.append(skeleton)

        return results
