from fastapi import FastAPI

app = FastAPI(title="Mutable Realms")


@app.get("/health/live")
def liveness() -> dict[str, str]:
    return {"status": "alive"}
