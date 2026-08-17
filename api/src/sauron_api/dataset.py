from __future__ import annotations

import io
import json
import zipfile
from dataclasses import dataclass, field

CATEGORIES = ("car", "bicycle", "person", "road_sign")


@dataclass(frozen=True, slots=True)
class CocoImage:
    jpeg: bytes
    width: int
    height: int
    annotations: list[tuple[str, list[float]]] = field(default_factory=list)


def build_coco_dataset_zip(items: list[CocoImage]) -> bytes:
    """Build a TAO-compatible COCO detection archive from reviewed evidence."""
    images: list[dict] = []
    annotations: list[dict] = []
    category_ids = {name: index + 1 for index, name in enumerate(CATEGORIES)}
    annotation_id = 1

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        for image_id, item in enumerate(items, start=1):
            filename = f"img_{image_id:05d}.jpg"
            archive.writestr(f"images/{filename}", item.jpeg)
            images.append(
                {
                    "id": image_id,
                    "file_name": filename,
                    "width": item.width,
                    "height": item.height,
                }
            )
            for class_name, xyxy in item.annotations:
                category_id = category_ids.get(class_name)
                if category_id is None or len(xyxy) != 4:
                    continue
                x1, y1, x2, y2 = (float(value) for value in xyxy)
                width = max(0.0, x2 - x1)
                height = max(0.0, y2 - y1)
                annotations.append(
                    {
                        "id": annotation_id,
                        "image_id": image_id,
                        "category_id": category_id,
                        "bbox": [x1, y1, width, height],
                        "area": width * height,
                        "iscrowd": 0,
                    }
                )
                annotation_id += 1

        payload = {
            "images": images,
            "annotations": annotations,
            "categories": [
                {"id": category_id, "name": name}
                for name, category_id in category_ids.items()
            ],
        }
        archive.writestr("annotations/instances.json", json.dumps(payload, indent=2))
    return buf.getvalue()
