from llm_client import generate_article

# Claudeに渡す「最小のテストデータ」
payload = {
    "brand": "TEST BRAND",
    "reference": "ABC-123",
    "tone": "落ち着いた上質",
    "options": {
        "brand_profile": False,
        "wearing_scene": False
    },
    "canonical_specs": {
        "ムーブメント": "自動巻",
        "ケース素材": "ステンレススチール",
        "ケース径": "40mm",
        "防水性能": "100m防水"
    }
}

intro, specs = generate_article(payload)

print("=== INTRO ===")
print(intro)
print()
print("=== SPECS ===")
print(specs)
