from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from ..types import Detection
from .base import Detector

log = logging.getLogger(__name__)


class TensorRTPose(Detector):
    """YOLOv8-pose TensorRT (.engine) — GPU. Misma API que OnnxPoseDetector."""

    def __init__(
        self,
        engine_path: str | Path,
        device_id: int = 0,
        input_size: tuple[int, int] = (640, 640),
        conf_threshold: float = 0.5,
        nms_threshold: float = 0.45,
        classes: dict[int, str] | None = None,
    ) -> None:
        try:
            import tensorrt as trt
            from cuda.bindings import driver as cu
        except ImportError as e:
            raise RuntimeError("TensorRTPose requiere extra gpu (tensorrt + cuda-python)") from e

        self._trt = trt
        self.device_id = device_id
        self.input_size = input_size
        self.conf_threshold = conf_threshold
        self.nms_threshold = nms_threshold
        self.classes = classes or {0: "person"}

        engine_path = Path(engine_path)
        if not engine_path.exists():
            raise FileNotFoundError(f"engine no encontrado: {engine_path}")

        # runtime
        logger = trt.Logger(trt.Logger.WARNING)
        runtime = trt.Runtime(logger)
        self.engine = runtime.deserialize_cuda_engine(engine_path.read_bytes())
        self.context = self.engine.create_execution_context()

        from cuda.bindings import driver as cu

        self._cu = cu
        cu.cuInit(0)
        dev = cu.cuDeviceGet(device_id)[1]
        self._ctx = cu.cuDevicePrimaryCtxRetain(dev)[1]
        cu.cuCtxSetCurrent(self._ctx)
        self._stream = cu.cuStreamCreate(0)[1]

        self._in_name = self.engine.get_tensor_name(0)
        self._out_name = self.engine.get_tensor_name(self.engine.num_io_tensors - 1)
        in_shape = (1, 3, input_size[1], input_size[0])
        self.context.set_input_shape(self._in_name, in_shape)

        self._d_in = self._alloc(int(np.prod(in_shape)) * 4)
        out_shape = self.context.get_tensor_shape(self._out_name)
        self._out_elems = int(np.prod(out_shape))
        self._d_out = self._alloc(self._out_elems * 4)
        self._h_out = np.empty(self._out_elems, dtype=np.float32)
        self._out_shape = tuple(out_shape)

    def _alloc(self, nbytes: int) -> int:
        return self._cu.cuMemAlloc(nbytes)[1]

    def detect(self, image: np.ndarray) -> list[Detection]:
        from .yolo_postprocess import letterbox, postprocess_yolo_pose

        cu = self._cu
        padded, scale, pad = letterbox(image, self.input_size)
        blob = padded[:, :, ::-1].transpose(2, 0, 1)[None].astype(np.float32) / 255.0
        blob = np.ascontiguousarray(blob)

        cu.cuMemcpyHtoDAsync(self._d_in, blob.ctypes.data, blob.nbytes, self._stream)
        self.context.set_tensor_address(self._in_name, int(self._d_in))
        self.context.set_tensor_address(self._out_name, int(self._d_out))
        self.context.execute_async_v3(self._stream)
        cu.cuMemcpyDtoHAsync(self._h_out.ctypes.data, self._d_out, self._h_out.nbytes, self._stream)
        cu.cuStreamSynchronize(self._stream)

        output = self._h_out.reshape(self._out_shape)
        results = postprocess_yolo_pose(
            output,
            orig_shape=image.shape[:2],
            scale=scale,
            pad=pad,
            conf_threshold=self.conf_threshold,
            nms_threshold=self.nms_threshold,
        )
        detections: list[Detection] = []
        for box, score, kp in results:
            detections.append(
                Detection(
                    bbox=box.astype(np.float32),
                    score=float(score),
                    class_id=0,
                    class_name=self.classes.get(0, "person"),
                    keypoints=kp,
                )
            )
        return detections

    def close(self) -> None:
        cu = self._cu
        for ptr in (self._d_in, self._d_out):
            try:
                cu.cuMemFree(ptr)
            except Exception:
                log.debug("cuMemFree failed", exc_info=True)
