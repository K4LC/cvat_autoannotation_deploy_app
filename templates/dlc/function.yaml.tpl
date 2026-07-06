metadata:
  name: dlc-{{ function_name }}-pose-cpu
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
    image: cvat.{{ function_name }}:cpu
    baseImage: ubuntu:22.04

    directives:
      preCopy:
        - kind: RUN
          value: apt-get update && apt-get install --no-install-recommends -y python3-pip python-is-python3 libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 libxcb1 ffmpeg && rm -rf /var/lib/apt/lists/*
        # CPU 版 torch を先に固定で入れる（DLC の依存で GPU 版が入らないように）
        - kind: RUN
          value: pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu
        # DeepLabCut(PyTorch) と推論に必要な最小依存
        - kind: RUN
          value: pip install --no-cache-dir "deeplabcut[pytorch]" opencv-python-headless pillow pyyaml numpy --no-cache-dir
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

  platform:
    attributes:
      restartPolicy:
        name: always
        maximumRetryCount: 3
      mountMode: volume
