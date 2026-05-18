"""Local dev entry when not using ``uvicorn`` directly (avoids shadowing the ``app`` package)."""

import os

import uvicorn

if __name__ == "__main__":
    port = int(os.environ.get("DATABRICKS_APP_PORT", os.environ.get("PORT", 8000)))
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=port,
        reload=os.environ.get("APP_ENV", "") == "development",
        app_dir="src",
    )
