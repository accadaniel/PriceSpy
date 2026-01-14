#!/usr/bin/env python3
"""
Standalone scraper script for cron job execution.
This script scrapes prices for all active products and sends alerts.
"""
import asyncio
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app import database
from app.services.scraper import scrape_product_prices
from app.services.alerts import check_and_send_alert
from app.config import get_settings


async def run_scraper():
    """Main scraper function that processes all active products."""
    print("=" * 50)
    print("PriceSpy Scraper - Starting")
    print("=" * 50)

    # Initialize database
    await database.init_db()

    # Get all active products
    products = await database.get_all_products(active_only=True)
    print(f"Found {len(products)} active products to scrape")

    if not products:
        print("No active products to scrape. Exiting.")
        return

    settings = get_settings()
    if not settings.serpapi_key:
        print("ERROR: SERPAPI_KEY not configured. Exiting.")
        return

    total_prices = 0
    total_alerts = 0
    errors = 0

    for product in products:
        print(f"\n--- Scraping: {product['name']} ---")
        print(f"    Query: {product['search_query']}")

        try:
            # Scrape prices
            prices = await scrape_product_prices(
                product_id=product["id"],
                search_query=product["search_query"],
                size=product.get("size"),
                color=product.get("color"),
            )

            if not prices:
                print(f"    No prices found")
                continue

            print(f"    Found {len(prices)} prices")

            # Store prices in database
            for price_data in prices:
                await database.add_price_record(
                    product_id=product["id"],
                    retailer=price_data["retailer"],
                    price=price_data["price"],
                    url=price_data["url"],
                    currency=price_data.get("currency", "USD"),
                )

            total_prices += len(prices)

            # Find lowest price and check for alerts
            lowest = min(prices, key=lambda x: x["price"])
            print(f"    Lowest: ${lowest['price']:.2f} at {lowest['retailer']}")
            print(f"    Target: ${product['target_price']:.2f}")

            if lowest["price"] < product["target_price"]:
                print(f"    Price is below target! Checking for alert...")

                alert_sent = await check_and_send_alert(
                    product=product,
                    lowest_price=lowest["price"],
                    retailer=lowest["retailer"],
                    url=lowest["url"],
                )

                if alert_sent:
                    print(f"    Alert sent to {product['user_email']}")
                    total_alerts += 1
                else:
                    print(f"    Alert skipped (already sent recently)")

        except Exception as e:
            print(f"    ERROR: {str(e)}")
            errors += 1

    print("\n" + "=" * 50)
    print("PriceSpy Scraper - Complete")
    print(f"  Products processed: {len(products)}")
    print(f"  Total prices found: {total_prices}")
    print(f"  Alerts sent: {total_alerts}")
    print(f"  Errors: {errors}")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(run_scraper())
