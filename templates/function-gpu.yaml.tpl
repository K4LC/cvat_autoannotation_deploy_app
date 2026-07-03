{# GPU 用 function.yaml (T-14 / req_add §2.2)
   最適化済みの CPU 版 (function.yaml.tpl) と同一の構造・変数を用い、
   GPU 実行に必要な差分のみを物体検出GPU example (example/yolo_box_gpu/function-gpu.yaml)
   を参考に補う。GPU 差分は 3 点のみ:
     - baseImage を CUDA イメージに
     - onnxruntime -> onnxruntime-gpu
     - resources.limits.nvidia.com/gpu: 1
   ラベル/keypoint/skeleton/spec 形式は CPU 版と完全同一 (main.py/model_handler.py も共通)。 #}
metadata:
  name: onnx-{{ function_name }}-pose-gpu
  namespace: cvat
  annotations:
    name: {{ display_name_json }}
    type: detector
    spec: |
      {{ spec_json | indent(6) }}
spec:
  description: {{ description_json }}
  runtime: 'python:3.10'
  handler: main:handler
  eventTimeout: 60s
  build:
    image: cvat.{{ function_name }}:gpu
    baseImage: nvidia/cuda:12.6.3-cudnn-runtime-ubuntu22.04

    directives:
      preCopy:
        - kind: RUN
          value: apt-get update && apt-get install --no-install-recommends -y python3-pip python-is-python3 libglib2.0-0 libsm6 libxext6 libxrender1 libxcb1 && rm -rf /var/lib/apt/lists/*
        - kind: RUN
          value: pip install onnxruntime-gpu=='1.20.*' opencv-python-headless pillow pyyaml --no-cache-dir
        - kind: WORKDIR
          value: /opt/nuclio
        - kind: COPY
          value: . .

  triggers:
    myHttpTrigger:
      numWorkers: 1
      kind: 'http'
      workerAvailabilityTimeoutMilliseconds: 10000
      attributes:
        maxRequestBodySize: 33554432 # 32MB

  resources:
    limits:
      nvidia.com/gpu: 1

  platform:
    attributes:
      restartPolicy:
        name: always
        maximumRetryCount: 3
      mountMode: volume
