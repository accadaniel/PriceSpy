from serpapi import GoogleSearch
from typing import List, Optional
from ..config import get_settings
import re


def extract_price(price_str: str) -> Optional[float]:
    """Extract numeric price from a string like '$99.99' or '99,99 EUR'."""
    if not price_str:
        return None
    # Remove currency symbols and extract number
    numbers = re.findall(r'[\d,]+\.?\d*', price_str.replace(',', ''))
    if numbers:
        try:
            return float(numbers[0])
        except ValueError:
            return None
    return None


def search_google_shopping(
    query: str,
    size: Optional[str] = None,
    color: Optional[str] = None,
    max_results: int = 10
) -> List[dict]:
    """
    Search Google Shopping for product prices.

    Returns a list of dicts with: retailer, price, currency, url, title
    """
    settings = get_settings()

    if not settings.serpapi_key:
        raise ValueError("SERPAPI_KEY not configured")

    # Build search query with variants
    search_query = query
    if size:
        search_query += f" {size}"
    if color:
        search_query += f" {color}"

    params = {
        "engine": "google_shopping",
        "q": search_query,
        "api_key": settings.serpapi_key,
        "num": max_results,
        "hl": "en",
        "gl": "us",
    }

    search = GoogleSearch(params)
    results = search.get_dict()

    prices = []

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
            "currency": "USD",  # SerpAPI Google Shopping US defaults to USD
            "url": item.get("link", ""),
            "title": item.get("title", ""),
            "thumbnail": item.get("thumbnail", ""),
        })

    return prices


async def scrape_product_prices(
    product_id: int,
    search_query: str,
    size: Optional[str] = None,
    color: Optional[str] = None
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
        lambda: search_google_shopping(search_query, size, color)
    )

    return prices
