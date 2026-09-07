from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


DATABASE_PATH = Path(__file__).resolve().parents[1] / "inspections.db"


def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def initialise_database() -> None:
    with _connect() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS inspections (
                inspection_id TEXT PRIMARY KEY,
                product_category TEXT NOT NULL,
                product_name TEXT NOT NULL,
                manufacturer TEXT NOT NULL,
                inspection_place TEXT NOT NULL,
                inspection_date TEXT NOT NULL,
                uploaded_images TEXT NOT NULL,
                ocr_result TEXT NOT NULL,
                extraction_result TEXT NOT NULL,
                compliance_result TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )


def save_completed_inspection(
    inspection_id: str,
    context: dict[str, Any],
    ocr_result: dict[str, Any],
    extraction_result: dict[str, Any],
    compliance_result: dict[str, Any],
) -> None:
    uploaded_images = context.get("uploaded_images", [])
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO inspections (
                inspection_id, product_category, product_name, manufacturer,
                inspection_place, inspection_date, uploaded_images, ocr_result,
                extraction_result, compliance_result
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(inspection_id) DO UPDATE SET
                product_category = excluded.product_category,
                product_name = excluded.product_name,
                manufacturer = excluded.manufacturer,
                inspection_place = excluded.inspection_place,
                inspection_date = excluded.inspection_date,
                uploaded_images = excluded.uploaded_images,
                ocr_result = excluded.ocr_result,
                extraction_result = excluded.extraction_result,
                compliance_result = excluded.compliance_result
            """,
            (
                inspection_id,
                str(context.get("product_category", "")),
                str(context.get("product_name", "")),
                str(context.get("manufacturer", "")),
                str(context.get("inspection_place", "")),
                str(context.get("inspection_date", "")),
                json.dumps(uploaded_images),
                json.dumps(ocr_result),
                json.dumps(extraction_result),
                json.dumps(compliance_result),
            ),
        )


def list_inspections() -> list[dict[str, Any]]:
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT inspection_id, product_category, product_name, manufacturer,
                   inspection_place, inspection_date, compliance_result, created_at
            FROM inspections
            ORDER BY created_at DESC, inspection_id DESC
            """
        ).fetchall()
    inspections = []
    for row in rows:
        compliance = json.loads(row["compliance_result"])
        inspections.append({
            "inspection_id": row["inspection_id"],
            "product_category": row["product_category"],
            "product_name": row["product_name"],
            "manufacturer": row["manufacturer"],
            "inspection_place": row["inspection_place"],
            "inspection_date": row["inspection_date"],
            "overall_status": compliance.get("overall_status"),
            "compliance_score": compliance.get("compliance_score"),
            "created_at": row["created_at"],
        })
    return inspections


def get_saved_inspection(inspection_id: str) -> dict[str, Any] | None:
    with _connect() as connection:
        row = connection.execute(
            "SELECT * FROM inspections WHERE inspection_id = ?",
            (inspection_id,),
        ).fetchone()
    if row is None:
        return None
    return {
        "inspection_id": row["inspection_id"],
        "context": {
            "product_category": row["product_category"],
            "product_name": row["product_name"],
            "manufacturer": row["manufacturer"],
            "inspection_place": row["inspection_place"],
            "inspection_date": row["inspection_date"],
            "uploaded_images": json.loads(row["uploaded_images"]),
        },
        "ocr_result": json.loads(row["ocr_result"]),
        "extraction_result": json.loads(row["extraction_result"]),
        "compliance_result": json.loads(row["compliance_result"]),
    }


def load_saved_inspections() -> list[dict[str, Any]]:
    with _connect() as connection:
        ids = connection.execute("SELECT inspection_id FROM inspections").fetchall()
    return [saved for row in ids if (saved := get_saved_inspection(row["inspection_id"])) is not None]


def delete_inspection(inspection_id: str) -> dict[str, Any] | None:
    saved = get_saved_inspection(inspection_id)
    if saved is None:
        return None
    with _connect() as connection:
        connection.execute("DELETE FROM inspections WHERE inspection_id = ?", (inspection_id,))
    return saved
