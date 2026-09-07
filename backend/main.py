"""Minimal Legal Metrology backend.

Run from the project root with:
    uvicorn backend.main:app --reload
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.inspections import router as inspections_router
from backend.services.persistence_service import initialise_database
from backend.services.persistence_service import load_saved_inspections
from backend.services.inspection_service import restore_inspection_context
from backend.services.extraction_service import store_ocr_result

app = FastAPI(title="Legal Metrology Compliance API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(inspections_router)
initialise_database()
for saved_inspection in load_saved_inspections():
    restore_inspection_context(saved_inspection["inspection_id"], saved_inspection["context"])
    store_ocr_result(saved_inspection["inspection_id"], saved_inspection["ocr_result"])


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
