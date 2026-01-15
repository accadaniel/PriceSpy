from fastapi import APIRouter, HTTPException, Form, Request
from fastapi.responses import RedirectResponse
from typing import Optional
from pydantic import BaseModel
import httpx
import re
from .. import database
from ..models import ProductCreate, ProductUpdate


class UrlScrapeRequest(BaseModel):
    url: str
    category: str = "electronics"


class ScrapedProductData(BaseModel):
    name: Optional[str] = None
    brand: Optional[str] = None
    model: Optional[str] = None
    color: Optional[str] = None
    size: Optional[str] = None
    storage: Optional[str] = None
    material: Optional[str] = None
    price: Optional[float] = None
    search_query: Optional[str] = None

router = APIRouter(prefix="/api/products", tags=["products"])


@router.post("")
async def create_product(product: ProductCreate):
    """Create a new product to track."""
    product_id = await database.create_product(
        name=product.name,
        search_query=product.search_query,
        target_price=product.target_price,
        user_email=product.user_email,
        size=product.size,
        color=product.color,
    )
    return {"id": product_id, "message": "Product created successfully"}


@router.get("")
async def list_products(active_only: bool = False):
    """List all tracked products."""
    products = await database.get_all_products(active_only=active_only)

    # Enrich with lowest prices
    for product in products:
        lowest = await database.get_lowest_price(product["id"])
        if lowest:
            product["lowest_price"] = lowest["price"]
            product["lowest_price_retailer"] = lowest["retailer"]
            product["lowest_price_url"] = lowest["url"]

    return products


@router.get("/{product_id}")
async def get_product(product_id: int):
    """Get a specific product by ID."""
    product = await database.get_product(product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    # Add price info
    lowest = await database.get_lowest_price(product_id)
    if lowest:
        product["lowest_price"] = lowest["price"]
        product["lowest_price_retailer"] = lowest["retailer"]
        product["lowest_price_url"] = lowest["url"]

    latest_prices = await database.get_latest_prices(product_id)
    product["current_prices"] = latest_prices

    return product


@router.put("/{product_id}")
async def update_product(product_id: int, product: ProductUpdate):
    """Update a product."""
    update_data = product.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")

    success = await database.update_product(product_id, **update_data)
    if not success:
        raise HTTPException(status_code=404, detail="Product not found")

    return {"message": "Product updated successfully"}


@router.delete("/{product_id}")
async def delete_product(product_id: int):
    """Delete a product."""
    success = await database.delete_product(product_id)
    if not success:
        raise HTTPException(status_code=404, detail="Product not found")

    return {"message": "Product deleted successfully"}


@router.post("/{product_id}/toggle")
async def toggle_product(product_id: int):
    """Toggle a product's active status."""
    product = await database.get_product(product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    new_status = not product["is_active"]
    await database.update_product(product_id, is_active=new_status)

    return {"message": f"Product {'activated' if new_status else 'deactivated'}", "is_active": new_status}


@router.post("/scrape-url")
async def scrape_product_url(request: UrlScrapeRequest):
    """Scrape product details from a URL to prefill the form."""
    url = request.url
    category = request.category

    if not url:
        raise HTTPException(status_code=400, detail="URL is required")

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as client:
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
            }
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            html = response.text
    except httpx.TimeoutException:
        raise HTTPException(status_code=408, detail="Request timed out while fetching the URL")
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=f"Failed to fetch URL: {e.response.status_code}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch URL: {str(e)}")

    # Extract product data from HTML
    data = extract_product_data(html, category)

    return data


def extract_product_data(html: str, category: str) -> ScrapedProductData:
    """Extract product information from HTML content."""
    data = ScrapedProductData()

    # Try to extract product name from various meta tags and elements
    name_patterns = [
        r'<meta\s+property=["\']og:title["\']\s+content=["\']([^"\']+)["\']',
        r'<meta\s+name=["\']twitter:title["\']\s+content=["\']([^"\']+)["\']',
        r'<title>([^<]+)</title>',
        r'<h1[^>]*class=["\'][^"\']*product[^"\']*["\'][^>]*>([^<]+)</h1>',
        r'<h1[^>]*>([^<]+)</h1>',
        r'"name"\s*:\s*"([^"]+)"',
    ]

    for pattern in name_patterns:
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            name = match.group(1).strip()
            # Clean up common suffixes
            name = re.sub(r'\s*[-|]\s*(Amazon|eBay|Best Buy|Walmart|Target|Official).*$', '', name, flags=re.IGNORECASE)
            name = re.sub(r'\s*:\s*(Amazon|eBay).*$', '', name, flags=re.IGNORECASE)
            if len(name) > 5 and len(name) < 200:
                data.name = name
                break

    # Extract brand from meta tags or structured data
    brand_patterns = [
        r'"brand"\s*:\s*\{[^}]*"name"\s*:\s*"([^"]+)"',
        r'"brand"\s*:\s*"([^"]+)"',
        r'<meta\s+property=["\']product:brand["\']\s+content=["\']([^"\']+)["\']',
        r'<span[^>]*class=["\'][^"\']*brand[^"\']*["\'][^>]*>([^<]+)</span>',
    ]

    for pattern in brand_patterns:
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            brand = match.group(1).strip()
            if len(brand) > 1 and len(brand) < 50:
                data.brand = brand
                break

    # Extract price
    price_patterns = [
        r'"price"\s*:\s*"?(\d+\.?\d*)"?',
        r'<meta\s+property=["\']product:price:amount["\']\s+content=["\']([^"\']+)["\']',
        r'<span[^>]*class=["\'][^"\']*price[^"\']*["\'][^>]*>\s*[\$€£]?\s*(\d+[,.]?\d*)',
    ]

    for pattern in price_patterns:
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            try:
                price_str = match.group(1).replace(',', '.')
                data.price = float(price_str)
                break
            except ValueError:
                continue

    # Category-specific extractions
    if category == "electronics":
        # Extract storage (e.g., 128GB, 256GB, 1TB)
        storage_match = re.search(r'\b(\d+\s*(?:GB|TB|MB))\b', html, re.IGNORECASE)
        if storage_match:
            data.storage = storage_match.group(1).upper().replace(' ', '')

        # Extract model number
        model_patterns = [
            r'"model"\s*:\s*"([^"]+)"',
            r'"mpn"\s*:\s*"([^"]+)"',
            r'Model[:\s#]+([A-Z0-9][-A-Z0-9]+)',
        ]
        for pattern in model_patterns:
            match = re.search(pattern, html, re.IGNORECASE)
            if match:
                data.model = match.group(1).strip()
                break

    elif category == "clothes":
        # Extract size
        size_patterns = [
            r'"size"\s*:\s*"([^"]+)"',
            r'Size[:\s]+([XSML]{1,3}|\d{1,2})',
        ]
        for pattern in size_patterns:
            match = re.search(pattern, html, re.IGNORECASE)
            if match:
                data.size = match.group(1).strip()
                break

        # Extract material
        material_patterns = [
            r'"material"\s*:\s*"([^"]+)"',
            r'Material[:\s]+([A-Za-z\s,]+?)(?:\.|<|$)',
            r'\b(\d+%\s*(?:Cotton|Polyester|Wool|Silk|Linen|Nylon)[^<]*)\b',
        ]
        for pattern in material_patterns:
            match = re.search(pattern, html, re.IGNORECASE)
            if match:
                material = match.group(1).strip()
                if len(material) < 100:
                    data.material = material
                    break

    # Extract color (common for both categories)
    color_patterns = [
        r'"color"\s*:\s*"([^"]+)"',
        r'Color[:\s]+([A-Za-z\s]+?)(?:\.|<|,|$)',
        r'<meta\s+property=["\']product:color["\']\s+content=["\']([^"\']+)["\']',
    ]
    for pattern in color_patterns:
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            color = match.group(1).strip()
            if len(color) > 2 and len(color) < 30:
                data.color = color
                break

    # Generate search query from extracted data
    search_parts = []
    if data.brand:
        search_parts.append(data.brand)
    if data.name:
        # Use name but remove brand if already included
        name_for_search = data.name
        if data.brand and data.brand.lower() in name_for_search.lower():
            name_for_search = re.sub(re.escape(data.brand), '', name_for_search, flags=re.IGNORECASE).strip()
        search_parts.append(name_for_search)
    if data.model:
        search_parts.append(data.model)

    if search_parts:
        data.search_query = ' '.join(search_parts)

    return data
