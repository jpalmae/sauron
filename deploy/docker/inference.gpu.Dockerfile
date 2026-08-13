# syntax=docker/dockerfile:1
#
# GPU inference image: ultralytics (PyTorch + CUDA) for YOLOv8-pose on GPU.
# For the DGX Spark (GB10 Grace-Blackwell, ARM64). 10-20x faster than CPU ONNX.
FROM --platform=linux/arm64 ultralytics/ultralytics:latest

ENV PYTHONUNBUFFERED=1
WORKDIR /app

# ultralytics image has: torch+CUDA, numpy, opencv, pydantic, scipy, PyYAML.
# We add the Sauron inference package (no-deps) + missing extras.
COPY inference/pyproject.toml ./
COPY inference/src ./src
RUN pip install --no-deps -e "." && pip install httpx redis "yt-dlp>=2026.1"

COPY inference/tools ./tools
# Baked models (ONNX fallback + PyTorch .pt if present)
COPY inference/models/ /app/models/

VOLUME ["/app/configs"]
EXPOSE 9100
HEALTHCHECK --interval=15s --timeout=5s --retries=5 \
    CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:9100/healthz')"

ENTRYPOINT ["sauron-inference"]
CMD ["run", "-c", "configs/pipeline.local.yaml"]
