from fastapi import FastAPI

app = FastAPI(title="IS_IT_WORTH_IT")


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}
