from pydantic import BaseModel
from typing import Optional


class StoreMetaConnection(BaseModel):
    connected: bool
    pageId: Optional[str] = None
    pageName: Optional[str] = None