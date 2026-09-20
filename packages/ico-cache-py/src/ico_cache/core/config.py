from pydantic import BaseModel

class ICOConfig(BaseModel):
    base_url: str = "http://localhost:8000"
    semantic_threshold: float = 0.92
