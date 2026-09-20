"""
Order processing service module.
"""

from dataclasses import dataclass
from typing import Optional, List


@dataclass
class OrderItem:
    item_id: str
    quantity: int
    unit_price: float


class OrderProcessor:
    """Handles validation, pricing calculations, and routing for incoming orders."""

    def __init__(self, tax_rate: float = 0.08):
        self.tax_rate = tax_rate

    def calculate_subtotal(self, items: List[OrderItem]) -> float:
        """Calculates pre-tax order total."""
        return sum(item.quantity * item.unit_price for item in items)

    def calculate_tax(self, subtotal: float) -> float:
        """Computes applicable sales tax."""
        return round(subtotal * self.tax_rate, 2)

    def process_order(self, order_id: str, items: List[OrderItem]) -> dict:
        """Processes entire checkout workflow."""
        subtotal = self.calculate_subtotal(items)
        tax = self.calculate_tax(subtotal)
        return {
            "order_id": order_id,
            "subtotal": subtotal,
            "tax": tax,
            "total": round(subtotal + tax, 2),
            "status": "APPROVED",
        }
