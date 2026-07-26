"""启动入口 — uvicorn, port 18088."""
import uvicorn

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=18088, reload=False)
