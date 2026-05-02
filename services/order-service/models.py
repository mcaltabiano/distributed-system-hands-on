from pydantic import BaseModel, Field
import uuid


class OrderRequest(BaseModel):
    product_id: str
    quantity: int = Field(gt=0)


class OrderResponse(BaseModel):
    order_id: uuid.UUID
    product_id: str
    quantity: int
    status: str
