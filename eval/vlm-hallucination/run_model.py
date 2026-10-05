"""Run one page-to-text model over the rendered test pages on CPU.

Usage: python run_model.py <model-key> [page ...]
Writes work/out/<model-key>/p<page>.txt and a .json with timing and whether
generation hit the token cap (a truncation or a repetition loop).
"""
import json
import pathlib
import sys
import time

import torch
from PIL import Image
from transformers import (AutoModelForImageTextToText, AutoProcessor, LightOnOcrForConditionalGeneration,
                          LightOnOcrProcessor)

HERE = pathlib.Path(__file__).parent
WORK = HERE / "work"
MAX_NEW_TOKENS = 4096

# key: (hub id, text prompt or None for image-only, longest image side in px)
MODELS = {
    "granite-docling-258m": ("ibm-granite/granite-docling-258M", "Convert this page to docling.", None),
    "glm-ocr-0.9b": ("zai-org/GLM-OCR", "Text Recognition:", None),
    "paddleocr-vl-1.6": ("PaddlePaddle/PaddleOCR-VL-1.6", "OCR:", None),
    "lightonocr-2-1b": ("lightonai/LightOnOCR-2-1B", None, 1540),
}


def load_page(page: int, longest: int | None) -> Image.Image:
    img = Image.open(WORK / "pages" / f"p{page}.png").convert("RGB")
    if longest and max(img.size) > longest:
        img.thumbnail((longest, longest))
    return img


def main():
    key, pages = sys.argv[1], [int(p) for p in sys.argv[2:]] or [45, 47, 49, 52]
    hub_id, prompt, longest = MODELS[key]
    torch.set_num_threads(4)
    # LightOnOCR's checkpoint config says mistral3; the Auto classes then load a model that
    # ignores the image and prints the same table for every page. Use its own classes.
    model_cls, proc_cls = ((LightOnOcrForConditionalGeneration, LightOnOcrProcessor) if key.startswith("lightonocr")
                           else (AutoModelForImageTextToText, AutoProcessor))
    processor = proc_cls.from_pretrained(hub_id)
    model = model_cls.from_pretrained(hub_id, dtype=torch.float32).eval()
    out_dir = WORK / "out" / key
    out_dir.mkdir(parents=True, exist_ok=True)
    for page in pages:
        content = [{"type": "image", "image": load_page(page, longest)}]
        if prompt:
            content.append({"type": "text", "text": prompt})
        inputs = processor.apply_chat_template(
            [{"role": "user", "content": content}],
            add_generation_prompt=True, tokenize=True, return_dict=True, return_tensors="pt",
        )
        inputs.pop("token_type_ids", None)
        start = time.time()
        with torch.inference_mode():
            # use_cache: granite-docling ships use_cache=false, which makes CPU decoding ~20x slower
            gen = model.generate(**inputs, max_new_tokens=MAX_NEW_TOKENS, do_sample=False, use_cache=True)
        new = gen[0, inputs["input_ids"].shape[1]:]
        # Keep special tokens: DocTags live in them for granite-docling.
        text = processor.decode(new, skip_special_tokens=False)
        meta = {"model": key, "hub_id": hub_id, "page": page, "seconds": round(time.time() - start, 1),
                "input_tokens": int(inputs["input_ids"].shape[1]), "new_tokens": int(len(new)),
                "hit_token_cap": int(len(new)) >= MAX_NEW_TOKENS}
        (out_dir / f"p{page}.txt").write_text(text)
        (out_dir / f"p{page}.json").write_text(json.dumps(meta, indent=1))
        print(json.dumps(meta), flush=True)


if __name__ == "__main__":
    main()
