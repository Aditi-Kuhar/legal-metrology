from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile, status

UPLOAD_DIR = Path(__file__).resolve().parents[2] / "uploads"
MAX_IMAGE_SIZE = 10 * 1024 * 1024
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
_inspection_contexts: dict[str, dict[str, object]] = {}


def get_inspection_context(inspection_id: str) -> dict[str, object]:
    return _inspection_contexts.get(inspection_id, {})


def restore_inspection_context(inspection_id: str, context: dict[str, object]) -> None:
    _inspection_contexts[inspection_id] = context


def _safe_filename(filename: str | None) -> str:
    name = Path(filename or "image").name
    return name or "image"


def _validate_fields(fields: dict[str, str]) -> None:
    missing_fields = [name for name, value in fields.items() if not value.strip()]
    if missing_fields:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Missing required field(s): {', '.join(missing_fields)}",
        )


def _validate_image_types(images: list[UploadFile]) -> None:
    for image in images:
        if image.content_type not in ALLOWED_IMAGE_TYPES:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=f"Unsupported image type for '{image.filename}'. Use JPEG, PNG, or WEBP.",
            )


def _remove_files(paths: list[Path]) -> None:
    for path in paths:
        path.unlink(missing_ok=True)


async def _save_image(image: UploadFile, inspection_id: str) -> Path:
    destination = UPLOAD_DIR / f"{inspection_id}_{_safe_filename(image.filename)}"
    size = 0
    try:
        with destination.open("wb") as output:
            while chunk := await image.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_IMAGE_SIZE:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"Image '{image.filename}' exceeds the 10 MB limit",
                    )
                output.write(chunk)
    except HTTPException:
        destination.unlink(missing_ok=True)
        raise
    except OSError as error:
        destination.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to save uploaded image(s)",
        ) from error
    return destination


async def receive_inspection(
    *,
    product_category: str,
    product_name: str,
    manufacturer: str,
    inspection_place: str,
    inspection_date: str,
    images: list[UploadFile] | None,
) -> dict[str, object]:
    _validate_fields({
        "product_category": product_category,
        "product_name": product_name,
        "manufacturer": manufacturer,
        "inspection_place": inspection_place,
        "inspection_date": inspection_date,
    })

    if not images:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one package image is required",
        )

    _validate_image_types(images)

    inspection_id = f"LM-{uuid4().hex[:12].upper()}"
    saved_paths: list[Path] = []

    try:
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        for image in images:
            destination = await _save_image(image, inspection_id)
            saved_paths.append(destination)
    except HTTPException:
        _remove_files(saved_paths)
        raise

    _inspection_contexts[inspection_id] = {
        "product_category": product_category,
        "product_name": product_name,
        "manufacturer": manufacturer,
        "inspection_place": inspection_place,
        "inspection_date": inspection_date,
        "uploaded_image": saved_paths[0].name,
        "uploaded_images": [path.name for path in saved_paths],
    }

    return {
        "inspection_id": inspection_id,
        "status": "RECEIVED",
        "uploaded_images": [path.name for path in saved_paths],
    }
