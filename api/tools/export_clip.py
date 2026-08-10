#!/usr/bin/env python3
"""Export CLIP ViT-B/32 (visual + text + tokenizer) to ONNX for semantic search.

Usage: python tools/export_clip.py [--out models]
Requires: pip install transformers torch onnx
"""

from __future__ import annotations

import argparse
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="models")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    import torch
    from transformers import CLIPModel, CLIPTokenizerFast

    model = CLIPModel.from_pretrained(
        "openai/clip-vit-base-patch32", attn_implementation="eager"
    )
    model.eval()

    class Visual(torch.nn.Module):
        def __init__(self, m):
            super().__init__()
            self.vision = m.vision_model
            self.proj = m.visual_projection

        def forward(self, pixel_values):
            return self.proj(self.vision(pixel_values=pixel_values).pooler_output)

    torch.onnx.export(
        Visual(model),
        (torch.zeros(1, 3, 224, 224),),
        out / "clip_visual.onnx",
        input_names=["pixel_values"],
        output_names=["embedding"],
        dynamic_axes={"pixel_values": {0: "batch"}, "embedding": {0: "batch"}},
        opset_version=14,
        dynamo=False,
    )

    class Textual(torch.nn.Module):
        def __init__(self, m):
            super().__init__()
            self.text = m.text_model
            self.proj = m.text_projection

        def forward(self, input_ids, attention_mask):
            return self.proj(
                self.text(input_ids=input_ids, attention_mask=attention_mask).pooler_output
            )

    ids = torch.ones(1, 16, dtype=torch.long)
    mask = torch.ones(1, 16, dtype=torch.long)
    torch.onnx.export(
        Textual(model),
        (ids, mask),
        out / "clip_text.onnx",
        input_names=["input_ids", "attention_mask"],
        output_names=["embedding"],
        dynamic_axes={
            "input_ids": {0: "batch", 1: "seq"},
            "attention_mask": {0: "batch", 1: "seq"},
            "embedding": {0: "batch"},
        },
        opset_version=14,
        dynamo=False,
    )

    CLIPTokenizerFast.from_pretrained("openai/clip-vit-base-patch32").save_pretrained(
        out / "clip_tokenizer"
    )
    print(f"CLIP exported to {out}")


if __name__ == "__main__":
    main()
