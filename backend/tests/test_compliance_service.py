import unittest

from backend.services.compliance_service import check_compliance


class ComplianceServiceTests(unittest.TestCase):
    def test_present_declarations_are_compliant(self) -> None:
        declarations = {
            "product_name": {"value": "POTATO CHIPS", "status": "detected"},
            "manufacturer": {"value": "Example Foods", "status": "detected"},
            "packer": {"value": None, "status": "not_detected"},
            "importer": {"value": None, "status": "not_detected"},
            "country_of_origin": {"value": None, "status": "not_detected"},
            "net_quantity": {"value": "500 g", "status": "detected"},
            "mrp": {"value": "120", "status": "detected"},
            "month_year_of_manufacture_or_packing": {"value": "08/2026", "status": "detected"},
            "best_before_or_use_by": {"value": "6 MONTHS", "status": "detected"},
            "consumer_care": {"value": "1800 123 4567", "status": "detected"},
            "unit_sale_price": {"value": "0.24/g", "status": "detected"},
        }
        result = check_compliance(
            declarations,
            "Packaged commodities",
            {"is_imported": False, "best_before_applicable": True, "unit_sale_price_applicable": True},
        )
        self.assertEqual(result["overall_status"], "COMPLIANT")
        self.assertTrue(all(check["status"] in {"COMPLIANT", "NOT_APPLICABLE"} for check in result["checks"]))
        self.assertEqual(result["compliance_score"], 100)

    def test_uncertain_ocr_requires_review(self) -> None:
        declarations = {
            "product_name": {"value": None, "status": "not_detected"},
            "manufacturer": {"value": None, "status": "needs_review"},
            "net_quantity": {"value": None, "status": "needs_review"},
            "mrp": {"value": None, "status": "not_detected"},
            "month_year_of_manufacture_or_packing": {"value": None, "status": "needs_review"},
            "best_before_or_use_by": {"value": None, "status": "not_detected"},
            "consumer_care": {"value": None, "status": "not_detected"},
            "unit_sale_price": {"value": None, "status": "not_detected"},
        }
        result = check_compliance(declarations, "Packaged commodities", {})
        self.assertEqual(result["overall_status"], "REVIEW_REQUIRED")
        self.assertFalse(any(check["status"] == "VIOLATION" for check in result["checks"]))
        self.assertLess(result["compliance_score"], 100)

    def test_confirmed_missing_applicable_declaration_is_violation(self) -> None:
        declarations = {
            "product_name": {"value": "POTATO CHIPS", "status": "detected"},
            "manufacturer": {"value": "Example Foods", "status": "detected"},
            "net_quantity": {"value": "500 g", "status": "detected"},
            "mrp": {"value": None, "status": "not_detected"},
            "month_year_of_manufacture_or_packing": {"value": "08/2026", "status": "detected"},
            "best_before_or_use_by": {"value": "6 MONTHS", "status": "detected"},
            "consumer_care": {"value": "1800 123 4567", "status": "detected"},
            "unit_sale_price": {"value": None, "status": "not_detected"},
        }
        result = check_compliance(
            declarations,
            "Packaged commodities",
            {
                "is_imported": False,
                "best_before_applicable": True,
                "unit_sale_price_applicable": False,
                "confirmed_missing_fields": ["mrp"],
            },
        )
        mrp_check = next(check for check in result["checks"] if check["field"] == "mrp")
        self.assertEqual(mrp_check["status"], "VIOLATION")
        self.assertEqual(result["overall_status"], "NON_COMPLIANT")


if __name__ == "__main__":
    unittest.main()
