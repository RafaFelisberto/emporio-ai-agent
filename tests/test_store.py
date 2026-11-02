import tempfile
import unittest
from pathlib import Path
from app.settings import demo_dir
from app.storage import Store
from app.policies import find_policies


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "test.sqlite")
        self.store.import_csv_dir(demo_dir())

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_catalog_filters_stock_and_discontinued(self):
        products = self.store.list_products(category="Violões", max_price=1000)
        self.assertEqual({p["product_id"] for p in products}, {1, 2})

    def test_promotion_and_price_are_precise(self):
        p = self.store.list_products(query="Aurora GD20")[0]
        self.assertEqual(p["price_brl"], "R$ 1.979,10")
        self.assertEqual(p["original_price_brl"], "R$ 2.199,00")
        self.assertEqual(p["discount_percent"], 10)

    def test_expired_promotion_does_not_apply(self):
        p = self.store.list_products(query="Aurora C40")[0]
        self.assertEqual(p["price_brl"], "R$ 599,90")

    def test_unknown_or_unverified_order_not_exposed(self):
        self.assertEqual(self.store.get_order(8, False)["status"], "authorization_required")
        self.assertFalse(self.store.verify_order(8, "someone@example.com"))

    def test_policy_retrieval(self):
        found = find_policies("Me arrependi da compra online e quero devolver")
        self.assertTrue(any(p["topic"] == "returns" for p in found))


if __name__ == "__main__":
    unittest.main()
