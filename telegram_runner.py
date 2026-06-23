"""Automated pipeline runner to execute daily scans and send reports to Telegram.

Fails fast: requires TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID to be set in the
environment variables. If any execution fails or network requests drop, the
process crashes loudly to ensure immediate visibility.
"""

import os
import subprocess
import sys
import requests


def run_script(script_name: str) -> str:
    """Execute a python script as a subprocess and return its standard output.

    Uses sys.executable to maintain the active conda environment context.
    """
    result = subprocess.run(
        [sys.executable, script_name],
        capture_output=True,
        text=True,
        check=True
    )
    return result.stdout


def send_telegram_report(token: str, chat_id: str, title: str, report_text: str) -> None:
    """Send a monospaced text report to Telegram using safe HTML block structures."""
    url = f"https://api.telegram.org/bot{token}/sendMessage"

    # Explicitly escape basic HTML syntax entities to prevent parsing errors
    escaped_text = report_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    full_body = f"<b>{title}</b>\n<pre>{escaped_text}</pre>"

    # If the combined payload exceeds safe limits, split it cleanly
    if len(full_body) > 4000:
        # Deliver the section header first
        requests.post(url, json={"chat_id": chat_id, "text": f"<b>{title}</b>", "parse_mode": "HTML"},
                      timeout=30).raise_for_status()

        max_chunk = 3800
        for i in range(0, len(escaped_text), max_chunk):
            chunk = escaped_text[i:i + max_chunk]
            payload = {"chat_id": chat_id, "text": f"<pre>{chunk}</pre>", "parse_mode": "HTML"}
            requests.post(url, json=payload, timeout=30).raise_for_status()
    else:
        payload = {"chat_id": chat_id, "text": full_body, "parse_mode": "HTML"}
        requests.post(url, json=payload, timeout=30).raise_for_status()


def main() -> None:
    # Fail fast: Access variables directly. Program crashes if missing.
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]

    # Run the daily buy candidates discovery scan
    buy_output = run_script("scan_today.py")
    send_telegram_report(token, chat_id, "🔭 DAILY BUY SCAN CANDIDATES", buy_output)

    # Run the open holdings stop-loss/discretionary sell evaluation
    sell_output = run_script("scan_sell_today.py")
    send_telegram_report(token, chat_id, "🚨 DAILY SELL VERDICTS REPORT", sell_output)


if __name__ == "__main__":
    main()