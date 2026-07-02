metadata:
  name: onnx-{{ author }}-{{ modelName }}-{{ timestamp }}-pose-gpu
  namespace: cvat
  annotations:
    name: {{ modelName }}
    type: detector
    spec: |
      [
        {"name": "person",
        "type": "skeleton",
        "svg": "{{ svgInfo }}",
        "sublabels": [
          {{ svgLabelNames }}
        ]
        }
      ]
spec:
  description: {{ modelName }} created by {{ author }} at {{ timestamp }}
  runtime: 'python:3.10'
  handler: main:handler
  eventTimeout: 60s
  build:
    image: cvat.{{ author }}.{{ modelName }}:gpu
    baseImage: nvidia/cuda:12.6.3-cudnn-runtime-ubuntu22.04

    directives:
      preCopy:
        - kind: RUN
          value: apt-get update && apt-get install --no-install-recommends -y python3-pip python-is-python3 libglib2.0-0 libsm6 libxext6 libxrender1 libxcb1 && rm -rf /var/lib/apt/lists/*
        - kind: WORKDIR
          value: /opt/nuclio
        - kind: RUN
          value: pip install onnxruntime-gpu=='1.20.*' opencv-python-headless pillow pyyaml --no-cache-dir
        - kind: WORKDIR
          value: /opt/nuclio
        - kind: COPY
          value: . .

  triggers:
    myHttpTrigger:
      numWorkers: 2
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
