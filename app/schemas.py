"""
schemas.py
----------
Pydantic models that define the *shape* of data going in and out of the
API. These are deliberately kept separate from the SQLAlchemy models in
models.py:

- models.py describes the database table.
- schemas.py describes the JSON contract with API clients.

Keeping them separate means we can change internal DB columns without
automatically changing the public API, and vice versa.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class ProductOut(BaseModel):
    """
    The shape of a single product as returned by the API.

    model_config with from_attributes=True (the Pydantic v2 way of saying
    "orm_mode") lets us pass a SQLAlchemy Product instance directly to
    ProductOut.model_validate(product) and have Pydantic read its
    attributes (id, name, category, ...) instead of requiring a dict.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    category: str
    price: Decimal
    created_at: datetime
    updated_at: datetime


class PaginatedProductsResponse(BaseModel):
    """
    The envelope returned by GET /products.

    - items: the page of products for this request.
    - next_cursor: an opaque string the client should pass back as the
      `cursor` query parameter to fetch the next page. It is None when
      there are no more pages.
    - has_more: a convenience flag so clients don't have to infer
      "is this the last page?" just from next_cursor being null versus
      an empty items list.
    """

    items: List[ProductOut]
    next_cursor: Optional[str] = Field(
        default=None,
        description="Opaque cursor to pass as `cursor` to fetch the next page. Null if no more pages.",
    )
    has_more: bool


class HealthResponse(BaseModel):
    """Simple shape for the health check endpoint."""

    status: str
    database: str
