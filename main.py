import os
import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any

app = FastAPI(title="Grocery Pricing Agent")

class RecipeRequest(BaseModel):
    recipe_input: str
    postal_code: str = "48170"

def parse_recipe_to_items(raw_text: str) -> List[str]:
    # Splits by newline or comma
    items = []
    for line in raw_text.replace(",", "\n").split("\n"):
        clean = line.strip()
        if clean:
            items.append(clean)
    return items

def query_flipp_deals(postal_code: str, query: str) -> List[Dict[str, Any]]:
    url = "https://backflipp.wishabi.com/flipp/items/search"
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15"
    }
    params = {"q": query, "postal_code": postal_code, "locale": "en-us"}
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=6)
        if resp.status_code == 200:
            data = resp.json()
            items = []
            for item in data.get("items", [])[:3]:
                items.append({
                    "merchant": item.get("merchant_name"),
                    "name": item.get("name"),
                    "price": item.get("current_price")
                })
            return items
    except Exception as e:
        print(f"Error querying Flipp: {e}")
    return []

@app.get("/")
def health_check():
    return {"status": "running"}

@app.post("/analyze-groceries")
async def analyze_groceries(req: RecipeRequest):
    ingredients = parse_recipe_to_items(req.recipe_input)
    if not ingredients:
        raise HTTPException(status_code=400, detail="No ingredients provided.")

    shopping_results = []
    for item in ingredients:
        deals = query_flipp_deals(req.postal_code, item)
        shopping_results.append({"ingredient": item, "local_deals": deals})
        
    output_lines = [f"# Grocery Plan for {req.postal_code}\n"]
    for res in shopping_results:
        output_lines.append(f"### {res['ingredient']}")
        if res["local_deals"]:
            for deal in res["local_deals"]:
                merchant = deal.get("merchant") or "Local Store"
                price = deal.get("price") or "See Ad"
                output_lines.append(f"- **{merchant}**: ${price} ({deal.get('name')})")
        else:
            output_lines.append("- *No circular flyer deal found — check standard shelf price.*")
        output_lines.append("")

    return {"markdown": "\n".join(output_lines), "raw_data": shopping_results}