from fastapi import APIRouter, HTTPException, Form, Request
from fastapi.responses import RedirectResponse
from typing import Optional
from pydantic import BaseModel
import httpx
import re
import json
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


def extract_json_ld(html: str) -> list[dict]:
    """Extract all JSON-LD structured data from HTML."""
    json_ld_data = []
    pattern = r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>'
    matches = re.findall(pattern, html, re.DOTALL | re.IGNORECASE)

    for match in matches:
        try:
            data = json.loads(match.strip())
            if isinstance(data, list):
                json_ld_data.extend(data)
            else:
                json_ld_data.append(data)
        except json.JSONDecodeError:
            continue

    return json_ld_data


def extract_meta_tags(html: str) -> dict:
    """Extract Open Graph and other meta tags."""
    meta = {}

    # Open Graph tags (property attribute)
    og_patterns = [
        (r'<meta\s+property=["\']og:title["\']\s+content=["\']([^"\']+)["\']', 'og_title'),
        (r'<meta\s+content=["\']([^"\']+)["\']\s+property=["\']og:title["\']', 'og_title'),
        (r'<meta\s+property=["\']og:description["\']\s+content=["\']([^"\']+)["\']', 'og_description'),
        (r'<meta\s+content=["\']([^"\']+)["\']\s+property=["\']og:description["\']', 'og_description'),
        (r'<meta\s+property=["\']product:price:amount["\']\s+content=["\']([^"\']+)["\']', 'price'),
        (r'<meta\s+content=["\']([^"\']+)["\']\s+property=["\']product:price:amount["\']', 'price'),
        (r'<meta\s+property=["\']product:price:currency["\']\s+content=["\']([^"\']+)["\']', 'currency'),
        (r'<meta\s+property=["\']product:brand["\']\s+content=["\']([^"\']+)["\']', 'brand'),
        (r'<meta\s+content=["\']([^"\']+)["\']\s+property=["\']product:brand["\']', 'brand'),
        (r'<meta\s+property=["\']product:color["\']\s+content=["\']([^"\']+)["\']', 'color'),
        (r'<meta\s+content=["\']([^"\']+)["\']\s+property=["\']product:color["\']', 'color'),
    ]

    for pattern, key in og_patterns:
        if key not in meta:
            match = re.search(pattern, html, re.IGNORECASE)
            if match:
                meta[key] = match.group(1).strip()

    # Twitter cards
    twitter_patterns = [
        (r'<meta\s+name=["\']twitter:title["\']\s+content=["\']([^"\']+)["\']', 'twitter_title'),
        (r'<meta\s+content=["\']([^"\']+)["\']\s+name=["\']twitter:title["\']', 'twitter_title'),
    ]

    for pattern, key in twitter_patterns:
        if key not in meta:
            match = re.search(pattern, html, re.IGNORECASE)
            if match:
                meta[key] = match.group(1).strip()

    # Regular title
    title_match = re.search(r'<title>([^<]+)</title>', html, re.IGNORECASE)
    if title_match:
        meta['title'] = title_match.group(1).strip()

    return meta


def find_product_in_json_ld(json_ld_list: list[dict]) -> dict | None:
    """Find Product schema in JSON-LD data."""
    for item in json_ld_list:
        if isinstance(item, dict):
            item_type = item.get('@type', '')
            if isinstance(item_type, list):
                item_type = item_type[0] if item_type else ''

            if item_type in ['Product', 'IndividualProduct', 'ProductModel']:
                return item

            # Check @graph array
            if '@graph' in item:
                for graph_item in item['@graph']:
                    if isinstance(graph_item, dict):
                        graph_type = graph_item.get('@type', '')
                        if isinstance(graph_type, list):
                            graph_type = graph_type[0] if graph_type else ''
                        if graph_type in ['Product', 'IndividualProduct', 'ProductModel']:
                            return graph_item
    return None


def clean_product_name(name: str) -> str:
    """Clean up product name by removing store suffixes."""
    if not name:
        return name
    # Remove common store suffixes
    name = re.sub(r'\s*[-|–—:]\s*(Amazon|eBay|Best Buy|Walmart|Target|Official|Shop|Store|Buy).*$', '', name, flags=re.IGNORECASE)
    name = re.sub(r'\s*\|\s*.*$', '', name)  # Remove everything after |
    name = name.strip()
    return name


def extract_product_data(html: str, category: str) -> ScrapedProductData:
    """Extract product information from HTML content using multiple strategies."""
    data = ScrapedProductData()

    # Check if page seems to be a queue/waiting page
    queue_indicators = ['we should be up and moving shortly', 'please wait', 'queue', 'high traffic', 'checking your browser']
    html_lower = html.lower()
    if any(indicator in html_lower for indicator in queue_indicators):
        # Page is likely blocked/queued, return empty data
        return data

    # Strategy 1: JSON-LD structured data (most reliable)
    json_ld_list = extract_json_ld(html)
    product_ld = find_product_in_json_ld(json_ld_list)

    if product_ld:
        # Extract name
        if 'name' in product_ld:
            data.name = clean_product_name(product_ld['name'])

        # Extract brand
        brand = product_ld.get('brand')
        if isinstance(brand, dict):
            data.brand = brand.get('name', '')
        elif isinstance(brand, str):
            data.brand = brand

        # Extract price from offers
        offers = product_ld.get('offers', {})
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        if isinstance(offers, dict):
            price = offers.get('price') or offers.get('lowPrice')
            if price:
                try:
                    data.price = float(str(price).replace(',', '.'))
                except ValueError:
                    pass

        # Extract color
        if 'color' in product_ld:
            data.color = product_ld['color']

        # Extract model/SKU
        if 'model' in product_ld:
            data.model = product_ld['model']
        elif 'sku' in product_ld:
            data.model = product_ld['sku']
        elif 'mpn' in product_ld:
            data.model = product_ld['mpn']

        # Extract material
        if 'material' in product_ld:
            mat = product_ld['material']
            if isinstance(mat, list):
                data.material = ', '.join(mat)
            else:
                data.material = mat

        # Extract size
        if 'size' in product_ld:
            data.size = product_ld['size']

        # Extract description for additional info
        description = product_ld.get('description', '')

        # Try to get color from description if not found
        if not data.color and description:
            color_match = re.search(r'\b(Black|White|Red|Blue|Green|Navy|Grey|Gray|Brown|Beige|Pink|Orange|Yellow|Purple|Gold|Silver)\b', description, re.IGNORECASE)
            if color_match:
                data.color = color_match.group(1).title()

    # Strategy 2: Meta tags (fallback for missing fields)
    meta = extract_meta_tags(html)

    if not data.name:
        data.name = clean_product_name(meta.get('og_title') or meta.get('twitter_title') or meta.get('title', ''))

    if not data.brand:
        data.brand = meta.get('brand')

    if not data.color:
        data.color = meta.get('color')

    if not data.price:
        price_str = meta.get('price')
        if price_str:
            try:
                data.price = float(price_str.replace(',', '.'))
            except ValueError:
                pass

    # Strategy 3: Regex patterns for common structures (last resort)
    if not data.brand:
        brand_patterns = [
            r'"brand"\s*:\s*\{[^}]*"name"\s*:\s*"([^"]+)"',
            r'"brand"\s*:\s*"([^"]+)"',
            r'itemprop=["\']brand["\']\s+content=["\']([^"\']+)["\']',
            r'data-brand=["\']([^"\']+)["\']',
        ]
        for pattern in brand_patterns:
            match = re.search(pattern, html, re.IGNORECASE)
            if match:
                brand = match.group(1).strip()
                if len(brand) > 1 and len(brand) < 50:
                    data.brand = brand
                    break

    if not data.price:
        price_patterns = [
            r'"price"\s*:\s*"?(\d+\.?\d*)"?',
            r'data-price=["\'](\d+\.?\d*)["\']',
            r'class=["\'][^"\']*price[^"\']*["\'][^>]*>[\s\S]*?[\$€£]?\s*(\d+[,.]?\d*)',
        ]
        for pattern in price_patterns:
            match = re.search(pattern, html, re.IGNORECASE)
            if match:
                try:
                    price_str = match.group(1).replace(',', '.')
                    price = float(price_str)
                    if 0.01 < price < 100000:  # Sanity check
                        data.price = price
                        break
                except ValueError:
                    continue

    # Category-specific extractions
    if category == "electronics":
        if not data.storage:
            storage_match = re.search(r'\b(\d+)\s*(GB|TB)\b', html, re.IGNORECASE)
            if storage_match:
                data.storage = f"{storage_match.group(1)}{storage_match.group(2).upper()}"

        if not data.model:
            model_patterns = [
                r'"model"\s*:\s*"([^"]+)"',
                r'"mpn"\s*:\s*"([^"]+)"',
                r'"sku"\s*:\s*"([^"]+)"',
                r'Model[\s:#]+([A-Z0-9][-A-Z0-9/]+)',
            ]
            for pattern in model_patterns:
                match = re.search(pattern, html, re.IGNORECASE)
                if match:
                    model = match.group(1).strip()
                    if len(model) > 2 and len(model) < 50:
                        data.model = model
                        break

    elif category == "clothes":
        if not data.material:
            material_patterns = [
                r'"material"\s*:\s*"([^"]+)"',
                r'(\d+%\s*(?:Cotton|Polyester|Wool|Silk|Linen|Nylon|Spandex|Elastane|Viscose|Rayon)[^<\n]*)',
                r'Material[:\s]+([A-Za-z0-9%\s,]+?)(?:\.|<|$)',
            ]
            for pattern in material_patterns:
                match = re.search(pattern, html, re.IGNORECASE)
                if match:
                    material = match.group(1).strip()
                    if len(material) > 3 and len(material) < 150:
                        data.material = material
                        break

    # Extract color if still missing (common patterns)
    if not data.color:
        color_patterns = [
            r'"color"\s*:\s*"([^"]+)"',
            r'data-color=["\']([^"\']+)["\']',
            r'[Cc]olou?r[:\s]+([A-Za-z\s]+?)(?:\s*[,.<]|$)',
        ]
        for pattern in color_patterns:
            match = re.search(pattern, html)
            if match:
                color = match.group(1).strip()
                if len(color) > 2 and len(color) < 40 and not re.search(r'\d', color):
                    data.color = color
                    break

    # Generate search query from extracted data
    search_parts = []
    if data.brand:
        search_parts.append(data.brand)
    if data.name:
        name_for_search = data.name
        # Remove brand from name if already included
        if data.brand and data.brand.lower() in name_for_search.lower():
            name_for_search = re.sub(re.escape(data.brand), '', name_for_search, flags=re.IGNORECASE).strip()
        name_for_search = re.sub(r'\s+', ' ', name_for_search).strip()
        if name_for_search:
            search_parts.append(name_for_search)
    if data.model and data.model not in ' '.join(search_parts):
        search_parts.append(data.model)
    if data.color and data.color.lower() not in ' '.join(search_parts).lower():
        search_parts.append(data.color)

    if search_parts:
        data.search_query = ' '.join(search_parts)

    return data
