{# GPU 用 function.yaml (DLC)
   CPU 版 (templates/dlc/function.yaml.tpl) と同一構造・同一変数。GPU 差分のみ:
     - baseImage を CUDA イメージに
     - torch を CPU 版でなく CUDA 版で導入
     - resources.limits.nvidia.com/gpu: 1
   ラベル/keypoint/skeleton/spec 形式・main.py/model_handler.py は CPU 版と共通。 #}
metadata:
  name: dlc-{{ function_name }}-pose-gpu
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
          value: apt-get update && apt-get install --no-install-recommends -y python3-pip python-is-python3 libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 libxcb1 ffmpeg && rm -rf /var/lib/apt/lists/*
        # CUDA 対応 torch（既定 index が CUDA ビルド）
        - kind: RUN
          value: pip install --no-cache-dir torch torchvision
        - kind: RUN
          value: pip install --no-cache-dir "deeplabcut[pytorch]" opencv-python-headless pillow pyyaml numpy
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
