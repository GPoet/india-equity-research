"""Start the dashboard API on localhost:8000 (personal use: never bound to the network)."""

import uvicorn

from eqr.app.api import create_app
from eqr.app.services import LiveServices

if __name__ == "__main__":
    uvicorn.run(create_app(LiveServices()), host="127.0.0.1", port=8000, log_level="info")
