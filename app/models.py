from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime


class ProductCreate(BaseModel):
    name: str
    search_query: str
    size: Optional[str] = None
    color: Optional[str] = None
    target_price: float
    user_email: str


class ProductUpdate(BaseModel):
    name: Optional[str] = None
    search_query: Optional[str] = None
    size: Optional[str] = None
    color: Optional[str] = None
    target_price: Optional[float] = None
    user_email: Optional[str] = None
    is_active: Optional[bool] = None


class Product(BaseModel):
    id: int
    name: str
    search_query: str
    size: Optional[str]
    color: Optional[str]
    target_price: float
    user_email: str
    is_active: bool
    created_at: datetime
    lowest_price: Optional[float] = None
    lowest_price_retailer: Optional[str] = None
    lowest_price_url: Optional[str] = None


class PriceRecord(BaseModel):
    id: int
    product_id: int
    retailer: str
    price: float
    currency: str
    url: str
    scraped_at: datetime


class AlertRecord(BaseModel):
    id: int
    product_id: int
    price: float
    retailer: str
    sent_at: datetime
