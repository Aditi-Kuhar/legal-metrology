from __future__ import annotations

import logging
import resource
import traceback
from io import BytesIO
from threading import Lock
from typing import Any

from fastapi import HTTPException, UploadFile, status
import numpy as np
from PIL import Image

from backend.services.inspection_service import (
    ALLOWED_IMAGE_TYPES,
    MAX_IMAGE_SIZE,
    UPLOAD_DIR,
)

_ocr_instance: Any | None = None
_ocr_lock = Lock()
logger = logging.getLogger(__name__)


def _inspection_exists(inspection_id: str) -> bool:
    return any(UPLOAD_DIR.glob(f"{inspection_id}_*"))


def _get_ocr() -> Any:
    global _ocr_instance
    if _ocr_instance is None:
        with _ocr_lock:
            if _ocr_instance is None:
                try:
                    from paddleocr import PaddleOCR
                except ImportError as error:
                    raise HTTPException(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        detail="PaddleOCR is not installed or could not be imported",
                    ) from error

                try:
                    _ocr_instance = PaddleOCR(
                        use_doc_orientation_classify=False,
                        use_doc_unwarping=False,
                        use_textline_orientation=False,
                    )
                except TypeError:
                    _ocr_instance = PaddleOCR(use_angle_cls=True, lang="en")
    return _ocr_instance


def _result_value(result: Any, key: str, default: Any = None) -> Any:
    if isinstance(result, dict):
        return result.get(key, default)
    if hasattr(result, key):
        return getattr(result, key)
    if hasattr(result, "json"):
        value = result.json
        value = value() if callable(value) else value
        if isinstance(value, str):
            import json

            value = json.loads(value)
        if isinstance(value, dict):
            value = value.get("res", value)
            return value.get(key, default)
    return default


def _json_value(value: Any) -> Any:
    if hasattr(value, "tolist"):
        return value.tolist()
    return value


def _modern_entries(result: Any) -> list[dict[str, Any]]:
    texts = _result_value(result, "rec_texts")
    if texts is None:
        return []
    scores = _result_value(result, "rec_scores") or []
    boxes = _result_value(result, "dt_polys") or _result_value(result, "rec_polys") or []
    entries = []
    for index, text in enumerate(texts):
        entry: dict[str, Any] = {"text": str(text)}
        if index < len(scores):
            entry["confidence"] = float(scores[index])
        if index < len(boxes):
            entry["bbox"] = _json_value(boxes[index])
        entries.append(entry)
    return entries


def _legacy_entries(result: Any) -> list[dict[str, Any]]:
    if not isinstance(result, list):
        return []
    entries = []
    for line in result:
        if not isinstance(line, (list, tuple)) or len(line) < 2:
            continue
        box, recognition = line[0], line[1]
        if isinstance(recognition, (list, tuple)) and len(recognition) >= 2:
            entries.append({
                "text": str(recognition[0]),
                "confidence": float(recognition[1]),
                "bbox": _json_value(box),
            })
    return entries


def _normalise_results(results: Any) -> list[dict[str, Any]]:
    if results is None:
        return []
    result_items = results if isinstance(results, (list, tuple)) else [results]
    entries: list[dict[str, Any]] = []
    for result in result_items:
        entries.extend(_modern_entries(result) or _legacy_entries(result))
    return entries


async def run_ocr(inspection_id: str, image: UploadFile) -> dict[str, object]:
    if not _inspection_exists(inspection_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Inspection not found or has no uploaded package image",
        )
    if image.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Unsupported image type. Use JPEG, PNG, or WEBP.",
        )

    content = await image.read(MAX_IMAGE_SIZE + 1)
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded image is empty",
        )
    if len(content) > MAX_IMAGE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Uploaded image exceeds the 10 MB limit",
        )

    try:
        with Image.open(BytesIO(content)) as package_image:
            package_image.verify()
        with Image.open(BytesIO(content)) as package_image:
            image_data = package_image.convert("RGB")
    except OSError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is not a valid image",
        ) from error

    image_paths = list(UPLOAD_DIR.glob(f"{inspection_id}_*"))
    max_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    logger.warning(
        "Starting PaddleOCR inference for inspection_id=%s image_path=%s "
        "image_size=%sx%s image_bytes=%s max_rss=%s",
        inspection_id,
        image_paths[0] if image_paths else "unknown",
        image_data.width,
        image_data.height,
        len(content),
        max_rss,
    )

    try:
        ocr = _get_ocr()
        image_array = np.asarray(image_data)
        print(
            "OCR_INFERENCE_BEFORE "
            f"inspection_id={inspection_id} "
            f"image_path={image_paths[0] if image_paths else 'unknown'} "
            f"image_size={image_data.width}x{image_data.height} "
            f"image_bytes={len(content)} max_rss={max_rss}",
            flush=True,
        )
        try:
            if hasattr(ocr, "predict"):
                raw_results = ocr.predict(input=image_array)
            else:
                raw_results = ocr.ocr(image_array, cls=True)
            print(
                f"OCR_INFERENCE_AFTER inspection_id={inspection_id}",
                flush=True,
            )
        except Exception as error:
            print(
                f"OCR_INFERENCE_EXCEPTION inspection_id={inspection_id} "
                f"exception_type={type(error).__name__} "
                f"message={error}",
                flush=True,
            )
            traceback.print_exc()
            logger.exception(
                "PaddleOCR inference failed for inspection_id=%s "
                "exception_type=%s",
                inspection_id,
                type(error).__name__,
            )
            raise
        detections = _normalise_results(raw_results)
    except HTTPException:
        raise
    except Exception as error:
        logger.exception("OCR processing failed for inspection_id=%s", inspection_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="OCR processing failed",
        ) from error

    return {
        "inspection_id": inspection_id,
        "status": "OCR_COMPLETED",
        "text": [entry["text"] for entry in detections],
        "detections": detections,
    }