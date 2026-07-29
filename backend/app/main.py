from fastapi import FastAPI

from app.scans.api import router as scans_router

app = FastAPI(title="IS_IT_WORTH_IT")
app.include_router(scans_router)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}
