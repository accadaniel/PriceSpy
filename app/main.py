from fastapi import FastAPI, Request, Form
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from . import database
from .routers import products, prices


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize database
    await database.init_db()
    yield
    # Shutdown: nothing to clean up


app = FastAPI(
    title="PriceSpy",
    description="Price monitoring and alert system",
    version="1.0.0",
    lifespan=lifespan,
)

# Mount static files
static_path = Path(__file__).parent / "static"
static_path.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=static_path), name="static")

# Templates
templates_path = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=templates_path)

# Include API routers
app.include_router(products.router)
app.include_router(prices.router)


# Web UI Routes
@app.get("/")
async def home(request: Request):
    """Home page - list all products."""
    products_list = await database.get_all_products()

    # Enrich with latest prices
    for product in products_list:
        latest_prices = await database.get_latest_prices(product["id"])
        if latest_prices:
            product["lowest_price"] = latest_prices[0]["price"]
            product["lowest_price_retailer"] = latest_prices[0]["retailer"]
            product["lowest_price_url"] = latest_prices[0]["url"]

    return templates.TemplateResponse(
        "index.html",
        {"request": request, "products": products_list}
    )


@app.get("/add")
async def add_product_form(request: Request):
    """Show add product form."""
    return templates.TemplateResponse(
        "add_product.html",
        {"request": request}
    )


@app.post("/add")
async def add_product_submit(
    request: Request,
    name: str = Form(...),
    search_query: str = Form(...),
    target_price: float = Form(...),
    user_email: str = Form(...),
    size: Optional[str] = Form(None),
    color: Optional[str] = Form(None),
):
    """Handle add product form submission."""
    await database.create_product(
        name=name,
        search_query=search_query,
        target_price=target_price,
        user_email=user_email,
        size=size if size else None,
        color=color if color else None,
    )
    return RedirectResponse(url="/", status_code=303)


@app.get("/product/{product_id}")
async def product_detail(request: Request, product_id: int):
    """Product detail page with price history."""
    product = await database.get_product(product_id)
    if not product:
        return RedirectResponse(url="/", status_code=303)

    price_history = await database.get_price_history(product_id, limit=100)
    latest_prices = await database.get_latest_prices(product_id)

    return templates.TemplateResponse(
        "product.html",
        {
            "request": request,
            "product": product,
            "price_history": price_history,
            "latest_prices": latest_prices,
        }
    )


@app.post("/product/{product_id}/delete")
async def delete_product_web(product_id: int):
    """Delete a product from web UI."""
    await database.delete_product(product_id)
    return RedirectResponse(url="/", status_code=303)


@app.post("/product/{product_id}/toggle")
async def toggle_product_web(product_id: int):
    """Toggle product active status from web UI."""
    product = await database.get_product(product_id)
    if product:
        await database.update_product(product_id, is_active=not product["is_active"])
    return RedirectResponse(url="/", status_code=303)


@app.get("/health")
async def health_check():
    """Health check endpoint for Render."""
    return {"status": "healthy"}
