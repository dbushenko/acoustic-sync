"""Local server startup with optional browser launch after successful binding."""
import logging
import threading
import webbrowser

import uvicorn


def run_server(app, port=8765, open_browser=False):
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, proxy_headers=False))
    stopped = threading.Event()

    def open_when_ready():
        while not stopped.wait(0.1):
            if server.started:
                url = f"http://127.0.0.1:{port}/"
                try:
                    if not webbrowser.open(url):
                        logging.warning("Browser could not open automatically. Open %s manually.", url)
                except Exception:
                    logging.warning("Browser launch failed. Open %s manually.", url, exc_info=True)
                return

    if open_browser:
        threading.Thread(target=open_when_ready, name="open-web-ui", daemon=True).start()
    try:
        server.run()
    finally:
        stopped.set()
