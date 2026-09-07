from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse, StreamingResponse

from backend.services.ocr_service import run_ocr
from backend.services.inspection_service import get_inspection_context, receive_inspection
from backend.services.extraction_service import extract_declarations, get_ocr_result, store_ocr_result
from backend.services.compliance_service import check_compliance
from backend.services.report_service import generate_report
from backend.services.persistence_service import delete_inspection, list_inspections, save_completed_inspection

router = APIRouter(prefix="/api/inspections", tags=["inspections"])
INSPECTION_NOT_FOUND = "Inspection not found"


@router.post("", status_code=201)
async def create_inspection(
    product_category: Annotated[str, Form()] = "",
    product_name: Annotated[str, Form()] = "",
    manufacturer: Annotated[str, Form()] = "",
    inspection_place: Annotated[str, Form()] = "",
    inspection_date: Annotated[str, Form()] = "",
    images: Annotated[list[UploadFile] | None, File()] = None,
) -> dict[str, object]:
    return await receive_inspection(
        product_category=product_category,
        product_name=product_name,
        manufacturer=manufacturer,
        inspection_place=inspection_place,
        inspection_date=inspection_date,
        images=images,
    )


@router.post("/{inspection_id}/ocr")
async def inspect_package_image(
    inspection_id: str,
    image: Annotated[UploadFile, File(...)],
) -> dict[str, object]:
    if not inspection_id.startswith("LM-"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=INSPECTION_NOT_FOUND,
        )

    result = await run_ocr(inspection_id, image)
    store_ocr_result(inspection_id, result)
    return result


@router.post("/{inspection_id}/extract")
async def extract_inspection_declarations(inspection_id: str) -> dict[str, object]:
    if not inspection_id.startswith("LM-"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=INSPECTION_NOT_FOUND,
        )
    return extract_declarations(get_ocr_result(inspection_id))


@router.post("/{inspection_id}/compliance")
async def inspect_compliance(inspection_id: str) -> dict[str, object]:
    if not inspection_id.startswith("LM-"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=INSPECTION_NOT_FOUND,
        )
    extracted = extract_declarations(get_ocr_result(inspection_id))
    context = get_inspection_context(inspection_id)
    compliance = check_compliance(
        extracted["declarations"],
        context.get("product_category", ""),
        context,
        get_ocr_result(inspection_id).get("detections", []),
    )
    save_completed_inspection(inspection_id, context, get_ocr_result(inspection_id), extracted, compliance)
    return compliance


@router.get("")
async def get_inspections() -> dict[str, object]:
    return {"inspections": list_inspections()}


@router.delete("/{inspection_id}")
async def remove_inspection(inspection_id: str) -> dict[str, object]:
    if not inspection_id.startswith("LM-"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=INSPECTION_NOT_FOUND)
    saved = delete_inspection(inspection_id)
    if saved is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=INSPECTION_NOT_FOUND)
    context = get_inspection_context(inspection_id)
    image_names = context.get("uploaded_images") or saved["context"].get("uploaded_images", [])
    for image_name in image_names:
        if isinstance(image_name, str):
            (Path(__file__).resolve().parents[2] / "uploads" / Path(image_name).name).unlink(missing_ok=True)
    return {"inspection_id": inspection_id, "status": "DELETED"}


@router.get("/{inspection_id}/image")
async def get_inspection_image(inspection_id: str) -> FileResponse:
    if not inspection_id.startswith("LM-"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=INSPECTION_NOT_FOUND)
    context = get_inspection_context(inspection_id)
    image_name = context.get("uploaded_image")
    if not isinstance(image_name, str):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inspection image not found")
    image_path = Path(__file__).resolve().parents[2] / "uploads" / image_name
    if not image_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inspection image not found")
    return FileResponse(image_path)


@router.get("/{inspection_id}/report")
async def get_inspection_report(inspection_id: str) -> StreamingResponse:
    if not inspection_id.startswith("LM-"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=INSPECTION_NOT_FOUND)
    report = generate_report(inspection_id)
    return StreamingResponse(
        report,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{inspection_id}-compliance-report.pdf"'},
    )
