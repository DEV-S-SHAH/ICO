import pytest
from ico_cache.core.metadata_guard import MetadataField, MetadataSchema, hard_gate

def test_generic_schema_extraction():
    # E-commerce schema
    schema = MetadataSchema(
        fields=[
            MetadataField(name="category", extractor=lambda t: "electronics" if "laptop" in t.lower() or "phone" in t.lower() else None),
            MetadataField(name="brand", extractor=lambda t: "Sony" if "sony" in t.lower() else ("Apple" if "apple" in t.lower() else None)),
            MetadataField(name="condition", extractor=lambda t: "refurbished" if "refurbished" in t.lower() else "new"),
        ]
    )

    extracted = schema.extract("Looking for a refurbished Sony laptop")
    assert extracted["category"] == "electronics"
    assert extracted["brand"] == "Sony"
    assert extracted["condition"] == "refurbished"

def test_generic_hard_gate():
    meta1 = {"category": "electronics", "brand": "Sony"}
    meta2 = {"category": "electronics", "brand": "Apple"}
    meta3 = {"category": "electronics", "brand": "Sony"}
    meta4 = {"category": "clothing", "brand": "Sony"}

    # Different brand -> block
    assert hard_gate(meta1, meta2, filter_keys=["category", "brand"]) is False
    # Same brand and category -> allow
    assert hard_gate(meta1, meta3, filter_keys=["category", "brand"]) is True
    # Different category -> block
    assert hard_gate(meta1, meta4, filter_keys=["category", "brand"]) is False
