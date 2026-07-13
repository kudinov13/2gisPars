import logging
import threading
import time
import sys
import os

import webview
from app import app

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

PORT = 18923


def start_flask():
    app.run(host="127.0.0.1", port=PORT, debug=False, use_reloader=False)


def main():
    flask_thread = threading.Thread(target=start_flask, daemon=True)
    flask_thread.start()

    # Wait for Flask to start
    time.sleep(1.5)

    window = webview.create_window(
        title="PARSER // COMPANY INTEL",
        url=f"http://127.0.0.1:{PORT}",
        width=1280,
        height=800,
        min_size=(1024, 600),
        frameless=False,
        easy_drag=False,
    )

    webview.start()


if __name__ == "__main__":
    main()
