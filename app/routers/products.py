from fastapi import APIRouter, HTTPException, Form, Request
from fastapi.responses import RedirectResponse
from typing import Optional
from .. import database
from ..models import ProductCreate, ProductUpdate

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
