"""
Prompts for clothing item metadata extraction (OpenAI Vision).
"""

COMPREHENSIVE_FEATURES_PROMPT = """You are analyzing a single clothing item image.
Return ONLY a valid JSON array with exactly one object. No markdown, no explanation.

The object must have these fields (string unless noted):
- article_name: short descriptive name (e.g. "Navy Slip-On Sneakers")
- category: one of Top, Bottom, Outerwear, Footwear
- subcategory: specific type (e.g. Sneakers, Loafers, T-Shirt, Jeans)
- basic_color: primary visible color (e.g. Navy Blue, Black)
- color_hex_codes: array of { "hex": "#RRGGBB", "percentage": number } for dominant colors, or empty []
- pattern: solid, striped, checked, floral, graphic, textured, other
- texture: e.g. smooth leather, soft suede
- material: e.g. leather, cotton
- occasion: single best match (e.g. Casual Day Out, Business Casual, Formal)
- season: spring, summer, fall, winter, all-season
- fit: slim, regular, oversized, other
- length: e.g. ankle-length, knee-length, full-length, Unknown

If uncertain for any field, use "Unknown" or "other" but always fill every field.
Output format: [ { "article_name": "...", ... } ]
"""
