"""Typed, read-only business queries over SQLite; CSV import is an explicit action."""
from __future__ import annotations

import csv
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
import hmac
import sqlite3
import unicodedata
import re


def normalized(value: str) -> str:
    v = unicodedata.normalize("NFKD", str(value).casefold())
    v = "".join(c for c in v if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", v).strip()


def money(value: str | float | Decimal) -> str:
    amount = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"R$ {amount:,.2f}".replace(",", "§").replace(".", ",").replace("§", ".")


SCHEMA = """
CREATE TABLE IF NOT EXISTS categories (
  category_id INTEGER PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS products (
  product_id INTEGER PRIMARY KEY, name TEXT NOT NULL, category_id INTEGER,
  description TEXT NOT NULL DEFAULT '', price_brl TEXT NOT NULL,
  stock_quantity INTEGER NOT NULL, status TEXT NOT NULL,
  FOREIGN KEY(category_id) REFERENCES categories(category_id)
);
CREATE TABLE IF NOT EXISTS promotions (
  promotion_id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL,
  discount_percent TEXT NOT NULL, description TEXT NOT NULL, is_active INTEGER NOT NULL,
  FOREIGN KEY(product_id) REFERENCES products(product_id)
);
CREATE TABLE IF NOT EXISTS customers (
  customer_id INTEGER PRIMARY KEY, name TEXT NOT NULL DEFAULT '',
  email TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS orders (
  order_id INTEGER PRIMARY KEY, customer_id INTEGER NOT NULL,
  order_date TEXT, status TEXT, total_brl TEXT,
  tracking_code TEXT, estimated_delivery TEXT,
  FOREIGN KEY(customer_id) REFERENCES customers(customer_id)
);
"""


class Store:
    def __init__(self, db_file: str | Path):
        self.db_file = Path(db_file)
        self.db_file.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(self.db_file)
        self.con.row_factory = sqlite3.Row
        self.con.executescript(SCHEMA)

    def close(self) -> None:
        self.con.close()

    @staticmethod
    def _find_file(folder: Path, stem: str) -> Path | None:
        files = list(folder.glob("*.csv"))
        matches = [p for p in files if p.stem == stem or p.stem.endswith(" - " + stem)]
        # Explicitly named synthetic test records; no real customer data in Git.
        if not matches and folder.name == "demo":
            fixture = {"customers": "people_fixture.csv", "orders": "purchase_fixture.csv"}.get(stem)
            if fixture and (folder / fixture).exists():
                return folder / fixture
        return sorted(matches)[0] if matches else None

    def import_csv_dir(self, folder: str | Path) -> dict[str, int]:
        folder = Path(folder)
        if not folder.is_dir():
            raise FileNotFoundError(f"Diretório de dados não encontrado: {folder}")
        config = {
            "categories": ("category_id", "name", "description"),
            "products": ("product_id", "name", "category_id", "description", "price_brl", "stock_quantity", "status"),
            "promotions": ("promotion_id", "product_id", "discount_percent", "description", "is_active"),
            "customers": ("customer_id", "name", "email"),
            "orders": ("order_id", "customer_id", "order_date", "status", "total_brl", "tracking_code", "estimated_delivery"),
        }
        counts: dict[str, int] = {}
        with self.con:
            # A fresh CSV import represents one coherent snapshot, not an append.
            for table in ("orders", "customers", "promotions", "products", "categories"):
                self.con.execute(f"DELETE FROM {table}")
            for table, cols in config.items():
                path = self._find_file(folder, table)
                if path is None:
                    continue
                with path.open(encoding="utf-8-sig", newline="") as fh:
                    rows = list(csv.DictReader(fh))
                missing = set(cols) - (set(rows[0]) if rows else set(cols))
                if missing:
                    raise ValueError(f"{path.name}: faltam colunas {sorted(missing)}")
                placeholders = ",".join("?" for _ in cols)
                sql = f"INSERT OR REPLACE INTO {table} ({','.join(cols)}) VALUES ({placeholders})"
                self.con.executemany(sql, [[r.get(c) or "" for c in cols] for r in rows])
                counts[table] = len(rows)
        return counts

    def list_products(self, query: str = "", category: str = "", max_price: float | None = None, limit: int = 5) -> list[dict]:
        limit = max(1, min(10, int(limit)))
        sql = """SELECT p.*, COALESCE(c.name,'') AS category,
                 (SELECT MAX(CAST(pr.discount_percent AS REAL)) FROM promotions pr
                  WHERE pr.product_id=p.product_id AND pr.is_active=1) AS discount
                 FROM products p LEFT JOIN categories c ON p.category_id=c.category_id
                 WHERE p.status='active' AND p.stock_quantity>0"""
        rows = [dict(r) for r in self.con.execute(sql)]
        qtokens = normalized(query).split()
        ctokens = normalized(category).split()
        found = []
        for p in rows:
            category_norm = normalized(p["category"])
            if ctokens and not all(t in category_norm for t in ctokens):
                continue
            name_norm = normalized(p["name"])
            # Product names are favored over free-form descriptions.
            score = sum(3 if t in name_norm.split() else 1 if t in name_norm else 0 for t in qtokens)
            if qtokens and not all(t in name_norm for t in qtokens):
                continue
            discount = Decimal(str(p["discount"])) if p["discount"] is not None else Decimal("0")
            original = Decimal(p["price_brl"])
            final = (original * (Decimal(100)-discount) / Decimal(100)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if max_price is not None and final > Decimal(str(max_price)):
                continue
            found.append({
                "product_id": p["product_id"], "name": p["name"], "category": p["category"],
                "price_brl": money(final), "original_price_brl": money(original),
                "discount_percent": int(discount) if discount == int(discount) else float(discount),
                "stock_quantity": p["stock_quantity"], "description": p["description"][:280],
                "_score": score, "_sort_price": final,
            })
        found.sort(key=lambda x: (-x["_score"], x["_sort_price"], x["name"]))
        for p in found:
            p.pop("_score");p.pop("_sort_price")
        return found[:limit]

    def verify_order(self, order_id: int, email: str) -> bool:
        row = self.con.execute("""SELECT c.email FROM orders o JOIN customers c ON c.customer_id=o.customer_id
                                  WHERE o.order_id=?""", (order_id,)).fetchone()
        if not row or not row["email"]:
            return False
        return hmac.compare_digest(row["email"].casefold().strip(), email.casefold().strip())

    def get_order(self, order_id: int, verified: bool) -> dict:
        if not verified:
            return {"status": "authorization_required", "message": "Confirme o número do pedido e o e-mail usado na compra."}
        row = self.con.execute("""SELECT order_id, order_date, status, total_brl, tracking_code, estimated_delivery
                                  FROM orders WHERE order_id=?""", (order_id,)).fetchone()
        if not row:
            return {"status": "not_found"}
        return {"order_id": row["order_id"], "status": row["status"],
                "order_date": row["order_date"], "total_brl": money(row["total_brl"]),
                "tracking_code": row["tracking_code"] or None,
                "estimated_delivery": row["estimated_delivery"] or None,
                "note": "Dados são fotografia do último CSV importado; não equivalem a tracking ao vivo."}
