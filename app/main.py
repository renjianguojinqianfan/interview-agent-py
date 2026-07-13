from fastapi import FastAPI

app = FastAPI(title="interview-agent-py", version="0.1.0")


@app.get("/")
async def root() -> dict[str, str]:
    return {"message": "Hello, interview-agent-py!"}
