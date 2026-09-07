import unittest

from backend.services.extraction_service import extract_declarations


class ExtractionServiceTests(unittest.TestCase):
    def test_common_label_variations(self) -> None:
        result = extract_declarations({"text": [
            "PRODUCT OF INDIA",
            "MANUFACTURED BY: Example Foods",
            "Marketed By: Example Traders",
            "NET WT: 500 g",
            "MAXIMUM RETAIL PRICE Rs 120",
            "MFD DATE: 08/2026",
            "BEST BEFORE 6 MONTHS",
            "CUSTOMER CARE: 1800 123 4567",
            "BATCH CODE: AB12/7",
        ]})
        declarations = result["declarations"]
        self.assertEqual(declarations["country_of_origin"]["value"], "INDIA")
        self.assertEqual(declarations["manufacturer"]["value"], "Example Foods")
        self.assertEqual(declarations["packer"]["value"], "Example Traders")
        self.assertEqual(declarations["net_quantity"]["value"], "500 g")
        self.assertEqual(declarations["mrp"]["value"], "120")
        self.assertEqual(declarations["month_year_of_manufacture_or_packing"]["value"], "08/2026")
        self.assertEqual(declarations["best_before_or_use_by"]["value"], "6 MONTHS")
        self.assertEqual(declarations["consumer_care"]["value"], "1800 123 4567")
        self.assertEqual(declarations["batch_or_lot_number"]["value"], "AB12/7")
        self.assertGreater(declarations["mrp"]["confidence"], 0.5)

    def test_split_labels_and_ambiguous_values_are_not_invented(self) -> None:
        result = extract_declarations({"text": [
            "NET QUANTITY:", "500 ml", "B. NO:", "and see below", "MFD:",
            "NESTLE CONSUMER CARE", "1800 1031947",
        ]})
        declarations = result["declarations"]
        self.assertEqual(declarations["net_quantity"]["value"], "500 ml")
        self.assertIsNone(declarations["batch_or_lot_number"]["value"])
        self.assertEqual(declarations["batch_or_lot_number"]["status"], "needs_review")
        self.assertEqual(declarations["consumer_care"]["value"], "1800 1031947")

    def test_product_candidates_exclude_ingredients_and_slogans(self) -> None:
        result = extract_declarations({"text": [
            "INGREDIENTS: Potato, edible vegetable oil",
            "It all starts with best quality potatoes",
            "POTATO CHIPS",
        ]})
        self.assertEqual(result["declarations"]["product_name"]["value"], "POTATO CHIPS")


if __name__ == "__main__":
    unittest.main()
