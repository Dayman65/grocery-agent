import os
import re
import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any
from bs4 import BeautifulSoup
from recipe_scrapers import scrape_me

app = FastAPI(title="Grocery Pricing Agent")

class RecipeRequest(BaseModel):
    recipe_input: str
    postal_code: str = "48170"

def clean_ingredient_for_search(raw_item: str) -> str:
    """
    Cleans recipe text like '2 lbs boneless skinless chicken breasts, diced'
    down to a clean search query like 'chicken breasts' for circular matching.
    """
    # Remove parentheticals, e.g. "(about 2 cups)"
    cleaned = re.sub(r'\(.*?\)', '', raw_item)
    # Remove common measurement fractions, numbers, and units
    cleaned = re.sub(r'^\s*[\d\/\.\s\-\¼\½\¾\⅓\⅔]+', '', cleaned)
    units = [
        r'\bcups?\b', r'\btablespoons?\b', r'\btbsp\b', r'\bteaspoons?\b', 
        r'\btsp\b', r'\bpounds?\b', r'\blbs?\b', r'\bounces?\b', r'\boz\b', 
        r'\bcloves?\b', r'\bpinch\b', r'\bcan\b', r'\bcans\b', r'\bpackage\b',
        r'\bpackages\b', r'\bhead\b', r'\bheads\b', r'\bstalks?\b'
    ]
    for unit in units:
        cleaned = re.sub(unit, '', cleaned, flags=re.IGNORECASE)
    
    # Split off descriptors after a comma (e.g., 'diced', 'room temperature')
    cleaned = cleaned.split(',')[0]
    return cleaned.strip()

def extract_ingredients(recipe_input: str) -> tuple[str, List[str]]:
    """
    Extracts recipe title and ingredients from either a URL or raw text.
    """
    raw_input = recipe_input.strip()
    
    # Check if input is a URL
    if raw_input.startswith("http://") or raw_input.startswith("https://"):
        url = raw_input.split()[0]  # Grab just the link if accompanied by extra text
        headers = {
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15"
        }
        
        try:
            # First, try standard recipe schema extraction
            scraper = scrape_me(url)
            title = scraper.title()
            ingredients = scraper.ingredients()
            if ingredients:
                return title, ingredients
        except Exception:
            pass  # Fall back to general HTML parsing if schema fails
        
        try:
            response = requests.get(url, headers=headers, timeout=10)
            soup = BeautifulSoup(response.text, "html.parser")
            title = soup.title.string.strip() if soup.title else "Recipe from Web"
            
            # Simple heuristic fallback: look for common ingredient classes/tags
            found = []
            for el in soup.select('[class*="ingredient"], [itemprop="recipeIngredient"]'):
                text = el.get_text(strip=True)
                if text and len(text) < 120 and text not in found:
                    found.append(text)
            
            if found:
                return title, found
        except Exception as e:
            print(f"Error fetching URL: {e}")
            
        return "Shared Recipe", [raw_input]

    # Otherwise, treat as raw text
    lines = [line.strip() for line in raw_input.replace(",", "\n").split("\n") if line.strip()]
    return "Custom Recipe List", lines

def query_flipp_deals(postal_code: str, query: str) -> List[Dict[str, Any]]:
    url = "https://backflipp.wishabi.com/flipp/items/search"
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15"
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
    title, ingredients = extract_ingredients(req.recipe_input)
    if not ingredients:
        raise HTTPException(status_code=400, detail="No ingredients could be found or parsed.")

    shopping_results = []
    for raw_item in ingredients:
        search_query = clean_ingredient_for_search(raw_item)
        if not search_query:
            search_query = raw_item

        deals = query_flipp_deals(req.postal_code, search_query)
        shopping_results.append({
            "original_ingredient": raw_item,
            "search_term": search_query,
            "local_deals": deals
        })

    # Format Markdown response
    output_lines = [f"# {title}", f"*Zip Code: {req.postal_code}*\n"]
    for res in shopping_results:
        output_lines.append(f"### {res['original_ingredient']}")
        if res["local_deals"]:
            for deal in res["local_deals"]:
                merchant = deal.get("merchant") or "Local Store"
                price = deal.get("price") or "See Ad"
                output_lines.append(f"- **{merchant}**: ${price} ({deal.get('name')})")
        else:
            output_lines.append("- *No circular flyer deal found — check standard shelf price.*")
        output_lines.append("")

    return {"markdown": "\n".join(output_lines), "raw_data": shopping_results}