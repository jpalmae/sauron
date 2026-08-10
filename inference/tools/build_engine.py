#!/usr/bin/env python3
"""Export YOLOv8 -> ONNX -> TensorRT .engine optimized for NVIDIA L4 (Ada Lovelace).

Usage (on the target GPU host):
    python tools/build_engine.py --weights yolov8n.pt --out models/yolov8n_fp16.engine --fp16
    python tools/build_engine.py --weights yolov8n.pt --out models/yolov8n_int8.engine --int8 --calib-data /data/calib
"""

from __future__ import annotations

import argparse
from pathlib import Path


def export_onnx(weights: str, onnx_path: Path, imgsz: int) -> Path:
    from ultralytics import YOLO

    model = YOLO(weights)
    model.export(format="onnx", imgsz=imgsz, simplify=True, opset=12, dynamic=False)
    default = Path(weights).with_suffix(".onnx")
    default.rename(onnx_path)
    return onnx_path


def build_engine(
    onnx_path: Path, out_path: Path, fp16: bool, int8: bool, workspace_gb: int,
    calib_data: str | None = None, imgsz: int = 640,
) -> None:
    import tensorrt as trt

    logger = trt.Logger(trt.Logger.INFO)
    builder = trt.Builder(logger)
    try:
        flag = 1 << int(trt.NetworkDefinitionCreationFlag.EXPLICIT_BATCH)
    except AttributeError:
        flag = 0  # TRT 10: explicit batch is default
    network = builder.create_network(flag)
    parser = trt.OnnxParser(network, logger)
    if not parser.parse_from_file(str(onnx_path)):
        for i in range(parser.num_errors):
            logger.log(trt.Logger.ERROR, parser.get_error(i))
        raise SystemExit("ONNX parse failed")

    config = builder.create_builder_config()
    config.set_memory_pool_limit(trt.MemoryPoolType.WORKSPACE, workspace_gb << 30)
    if fp16:
        try:
            has_fp16 = builder.platform_has_fast_fp16
        except AttributeError:
            has_fp16 = True
        if has_fp16:
            config.set_flag(trt.BuilderFlag.FP16)
    if int8:
        try:
            has_int8 = builder.platform_has_fast_int8
        except AttributeError:
            has_int8 = True
        if not has_int8:
            raise SystemExit("platform has no fast INT8")
        if not calib_data:
            raise SystemExit("INT8 requires --calib-data (dir with calibration frames)")
        config.set_flag(trt.BuilderFlag.INT8)
        config.int8_calibrator = ImageCalibrator(calib_data, imgsz)

    serialized = builder.build_serialized_network(network, config)
    if serialized is None:
        raise SystemExit("engine build failed")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(bytes(serialized))
    print(f"engine written to {out_path} ({out_path.stat().st_size / 1e6:.1f} MB)")


class ImageCalibrator:
    """IInt8EntropyCalibrator2 over a directory of production frames (JPEG/PNG)."""

    def __init__(self, data_dir: str, imgsz: int, batch_size: int = 8, max_batches: int = 64):
        import glob

        import tensorrt as trt

        # dynamically subclass to keep tensorrt import optional at module level
        base = trt.IInt8EntropyCalibrator2
        cls = type("TrtImageCalibrator", (base, ImageCalibrator), {})
        self.__class__ = cls
        base.__init__(self)

        self.files = sorted(glob.glob(f"{data_dir}/*.jpg") + glob.glob(f"{data_dir}/*.png"))
        if not self.files:
            raise SystemExit(f"no calibration images in {data_dir}")
        self.imgsz = imgsz
        self.batch_size = batch_size
        self.max_batches = min(max_batches, len(self.files) // batch_size or 1)
        self._batch = 0
        from cuda.bindings import driver as cu

        self._cu = cu
        self._d_input = cu.cuMemAlloc(batch_size * 3 * imgsz * imgsz * 4)[1]

    def get_batch_size(self) -> int:
        return self.batch_size

    def get_batch(self, names):
        import cv2
        import numpy as np

        if self._batch >= self.max_batches:
            return None
        blobs = []
        for f in self.files[self._batch * self.batch_size : (self._batch + 1) * self.batch_size]:
            img = cv2.imread(f)
            if img is None:
                continue
            img = cv2.resize(img, (self.imgsz, self.imgsz))
            blob = img[:, :, ::-1].transpose(2, 0, 1).astype(np.float32) / 255.0
            blobs.append(np.ascontiguousarray(blob))
        while len(blobs) < self.batch_size:
            blobs.append(blobs[-1].copy())
        batch = np.concatenate(blobs)[None].reshape(self.batch_size, 3, self.imgsz, self.imgsz)
        self._cu.cuMemcpyHtoD(self._d_input, batch.ctypes.data, batch.nbytes)
        self._batch += 1
        return [int(self._d_input)]

    def read_calibration_cache(self):
        return None

    def write_calibration_cache(self, cache):
        pass


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", required=True, help="YOLOv8 .pt weights")
    ap.add_argument("--out", required=True, help="output .engine path")
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--fp16", action="store_true", default=True)
    ap.add_argument("--int8", action="store_true")
    ap.add_argument("--workspace-gb", type=int, default=4)
    ap.add_argument("--calib-data", default=None, help="dir with calibration frames (INT8)")
    args = ap.parse_args()

    onnx_path = Path(args.out).with_suffix(".onnx")
    export_onnx(args.weights, onnx_path, args.imgsz)
    build_engine(
        onnx_path, Path(args.out), args.fp16, args.int8, args.workspace_gb,
        calib_data=args.calib_data, imgsz=args.imgsz,
    )


if __name__ == "__main__":
    main()
