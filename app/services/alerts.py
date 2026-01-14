import resend
from typing import Optional
from ..config import get_settings


def send_price_alert(
    to_email: str,
    product_name: str,
    current_price: float,
    target_price: float,
    retailer: str,
    product_url: str,
    currency: str = "USD"
) -> Optional[str]:
    """
    Send a price drop alert email.

    Returns the email ID if successful, None otherwise.
    """
    settings = get_settings()

    if not settings.resend_api_key:
        raise ValueError("RESEND_API_KEY not configured")

    resend.api_key = settings.resend_api_key

    # Format prices
    currency_symbol = "$" if currency == "USD" else currency
    current_formatted = f"{currency_symbol}{current_price:.2f}"
    target_formatted = f"{currency_symbol}{target_price:.2f}"
    savings = target_price - current_price
    savings_formatted = f"{currency_symbol}{savings:.2f}"

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
            .header {{ background: #4CAF50; color: white; padding: 20px; text-align: center; }}
            .content {{ padding: 20px; background: #f9f9f9; }}
            .price-box {{ background: white; padding: 15px; margin: 15px 0; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
            .current-price {{ font-size: 32px; color: #4CAF50; font-weight: bold; }}
            .target-price {{ color: #666; text-decoration: line-through; }}
            .savings {{ color: #4CAF50; font-weight: bold; }}
            .button {{ display: inline-block; background: #4CAF50; color: white; padding: 12px 24px; text-decoration: none; border-radius: 4px; margin-top: 15px; }}
            .footer {{ text-align: center; padding: 20px; color: #666; font-size: 12px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>Price Drop Alert!</h1>
            </div>
            <div class="content">
                <h2>{product_name}</h2>
                <div class="price-box">
                    <p>Current Price at <strong>{retailer}</strong>:</p>
                    <p class="current-price">{current_formatted}</p>
                    <p>Your target price: <span class="target-price">{target_formatted}</span></p>
                    <p class="savings">You save: {savings_formatted}</p>
                </div>
                <a href="{product_url}" class="button">View Deal</a>
            </div>
            <div class="footer">
                <p>You're receiving this because you set up a price alert on PriceSpy.</p>
                <p>Prices may vary and are subject to change.</p>
            </div>
        </div>
    </body>
    </html>
    """

    text_content = f"""
    Price Drop Alert!

    {product_name}

    Current Price at {retailer}: {current_formatted}
    Your target price: {target_formatted}
    You save: {savings_formatted}

    View the deal: {product_url}

    ---
    You're receiving this because you set up a price alert on PriceSpy.
    """

    try:
        response = resend.Emails.send({
            "from": settings.from_email,
            "to": [to_email],
            "subject": f"Price Drop Alert: {product_name} now {current_formatted}!",
            "html": html_content,
            "text": text_content,
        })
        return response.get("id")
    except Exception as e:
        print(f"Failed to send email: {e}")
        return None


async def check_and_send_alert(
    product: dict,
    lowest_price: float,
    retailer: str,
    url: str
) -> bool:
    """
    Check if price is below target and send alert if not sent recently.

    Returns True if alert was sent.
    """
    from .. import database

    # Check if price is below target
    if lowest_price >= product["target_price"]:
        return False

    # Check if we already sent an alert recently (within 24 hours)
    recent_alert = await database.get_recent_alert(product["id"], hours=24)
    if recent_alert:
        return False

    # Send the alert
    email_id = send_price_alert(
        to_email=product["user_email"],
        product_name=product["name"],
        current_price=lowest_price,
        target_price=product["target_price"],
        retailer=retailer,
        product_url=url,
    )

    if email_id:
        # Record the alert
        await database.add_alert_record(product["id"], lowest_price, retailer)
        return True

    return False
