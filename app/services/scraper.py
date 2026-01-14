from serpapi import GoogleSearch
from typing import List, Optional
from ..config import get_settings
import re


# Region configuration for SerpAPI
REGION_CONFIG = {
    "eu": {
        "gl": "de",  # Germany as main EU market
        "hl": "en",  # English language
        "currency": "EUR",
        "location": "Germany",
    },
    "worldwide": {
        "gl": "us",  # US for worldwide (largest market)
        "hl": "en",
        "currency": "USD",
        "location": "United States",
    },
    "hu": {
        "gl": "hu",  # Hungary specifically
        "hl": "hu",
        "currency": "HUF",
        "location": "Hungary",
    }
}


def extract_price(price_str: str) -> Optional[float]:
    """Extract numeric price from a string like '$99.99', '99,99 EUR', or '29 999 Ft'."""
    if not price_str:
        return None
    # Remove currency symbols and normalize
    cleaned = price_str.replace(',', '.').replace(' ', '')
    # Remove common currency symbols
    cleaned = re.sub(r'[€$£¥₹Ft]', '', cleaned)
    cleaned = re.sub(r'EUR|USD|GBP|HUF', '', cleaned)
    # Extract number
    numbers = re.findall(r'[\d]+\.?\d*', cleaned)
    if numbers:
        try:
            return float(numbers[0])
        except ValueError:
            return None
    return None


def search_google_shopping(
    query: str,
    region: str = "eu",
    size: Optional[str] = None,
    color: Optional[str] = None,
    brand: Optional[str] = None,
    model: Optional[str] = None,
    storage: Optional[str] = None,
    material: Optional[str] = None,
    max_results: int = 10
) -> List[dict]:
    """
    Search Google Shopping for product prices.

    Returns a list of dicts with: retailer, price, currency, url, title
    """
    settings = get_settings()

    if not settings.serpapi_key:
        raise ValueError("SERPAPI_KEY not configured")

    # Get region config
    region_cfg = REGION_CONFIG.get(region, REGION_CONFIG["eu"])

    # Build search query with all variants
    search_parts = [query]
    if brand:
        search_parts.append(brand)
    if model:
        search_parts.append(model)
    if size:
        search_parts.append(size)
    if color:
        search_parts.append(color)
    if storage:
        search_parts.append(storage)
    if material:
        search_parts.append(material)

    search_query = " ".join(search_parts)

    params = {
        "engine": "google_shopping",
        "q": search_query,
        "api_key": settings.serpapi_key,
        "num": max_results,
        "hl": region_cfg["hl"],
        "gl": region_cfg["gl"],
    }

    # Add location for more accurate results
    if "location" in region_cfg:
        params["location"] = region_cfg["location"]

    search = GoogleSearch(params)
    results = search.get_dict()

    prices = []
    currency = region_cfg["currency"]

    # Parse shopping results
    shopping_results = results.get("shopping_results", [])

    for item in shopping_results[:max_results]:
        price_str = item.get("price") or item.get("extracted_price")
        price = None

        # Try extracted_price first (numeric), then parse price string
        if "extracted_price" in item and item["extracted_price"]:
            price = float(item["extracted_price"])
        elif price_str:
            price = extract_price(price_str)

        if price is None:
            continue

        prices.append({
            "retailer": item.get("source", "Unknown"),
            "price": price,
            "currency": currency,
            "url": item.get("link", ""),
            "title": item.get("title", ""),
            "thumbnail": item.get("thumbnail", ""),
        })

    return prices


async def scrape_product_prices(
    product_id: int,
    search_query: str,
    region: str = "eu",
    size: Optional[str] = None,
    color: Optional[str] = None,
    brand: Optional[str] = None,
    model: Optional[str] = None,
    storage: Optional[str] = None,
    material: Optional[str] = None,
) -> List[dict]:
    """
    Scrape prices for a product and return results.
    This is an async wrapper around the sync SerpAPI call.
    """
    import asyncio

    # Run sync SerpAPI call in thread pool
    loop = asyncio.get_event_loop()
    prices = await loop.run_in_executor(
        None,
        lambda: search_google_shopping(
            search_query,
            region=region,
            size=size,
            color=color,
            brand=brand,
            model=model,
            storage=storage,
            material=material,
        )
    )

    return prices
