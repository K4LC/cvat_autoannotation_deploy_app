import base64
import io
import json
import traceback

import yaml
from model_handler import ModelHandler
from PIL import Image


def init_context(context):
    context.logger.info("Init context...  0%")

    # Read labels
    with open("/opt/nuclio/function.yaml", "rb") as function_file:
        functionconfig = yaml.safe_load(function_file)

    labels_spec = functionconfig["metadata"]["annotations"]["spec"]
    labels = json.loads(labels_spec)

    # Read the DL model
    model = ModelHandler(labels)
    context.user_data.model = model

    context.logger.info("Init context...100%")


def handler(context, event):
    context.logger.info("Run {{ modelName }}-{{ author }}-{{ timestamp }}")
    try:
        data = event.body
        buf = io.BytesIO(base64.b64decode(data["image"]))
        threshold = float(data.get("threshold", 0.5))
        image = Image.open(buf).convert("RGB")

        results = context.user_data.model.infer(image, threshold)

        return context.Response(
            body=json.dumps(results), headers={}, content_type="application/json", status_code=200
        )
    except Exception as e:
        # 失敗原因をnuclioログに残し、レスポンスにも含めて切り分けしやすくする
        tb = traceback.format_exc()
        context.logger.error("inference failed: " + tb)
        return context.Response(
            body=json.dumps({"error": str(e), "traceback": tb}),
            headers={},
            content_type="application/json",
            status_code=500,
        )
