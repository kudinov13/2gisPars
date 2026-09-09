import logging
import threading
import time
import sys
import os
import webbrowser

from app import app

if getattr(sys, "frozen", False):
    _app_dir = os.path.dirname(sys.executable)
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = os.path.join(_app_dir, "ms-playwright")

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

    # Try to run as a desktop window via pywebview.
    # On some PCs pywebview/pythonnet may fail because of missing .NET Framework.
    # In that case we fall back to the user's default browser.
    try:
        import webview

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
    except Exception as e:
        logger.warning(f"Не удалось запустить встроенное окно ({e}). Открываю интерфейс в браузере.")
        webbrowser.open(f"http://127.0.0.1:{PORT}")
        # Keep the main thread alive while Flask works
        while True:
            time.sleep(1)


if __name__ == "__main__":
    main()
