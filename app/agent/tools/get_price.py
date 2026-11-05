import uuid
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.agent.tools.base import BaseTool, ToolResult
from app.services import product_service
from app.services.exceptions import NotFoundError


class GetPriceTool(BaseTool):
    @property
    def name(self) -> str:
        return "get_price"

    @property
    def description(self) -> str:
        return "Get the current price of a specific product."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "product_id": {"type": "string", "description": "UUID of the product"}
            },
            "required": ["product_id"],
        }

    async def execute(
        self,
        store_id: uuid.UUID,
        arguments: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> ToolResult:
        try:
            args = self.validate_arguments(arguments)
            product_id = uuid.UUID(args["product_id"])
            db: Session = context["db"]
            product = product_service.get_product(db, store_id, product_id)
            return ToolResult(
                success=True,
                data={
                    "product_id": str(product.id),
                    "name": product.name,
                    "price": str(product.price),
                    "currency": "DZD",
                },
            )
        except NotFoundError:
            return ToolResult(success=False, error="Product not found in this store")
        except (ValueError, KeyError):
            return ToolResult(success=False, error="Invalid product_id format")
        except SQLAlchemyError:
            raise
        except Exception:
            return ToolResult(success=False, error="Failed to get price")
