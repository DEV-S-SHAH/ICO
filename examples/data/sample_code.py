"""Sample code repository file for AST chunking demo."""


def calculate_discount(price: float, rate: float) -> float:
    """Calculates discounted price based on promotional rate."""
    return price * (1.0 - rate)


class InventoryManager:
    """Manages store inventory levels and stock reorders."""

    def __init__(self, store_id: str):
        self.store_id = store_id
        self.stock = {}

    def add_stock(self, sku: str, quantity: int) -> None:
        """Adds quantity to SKU in stock."""
        self.stock[sku] = self.stock.get(sku, 0) + quantity
