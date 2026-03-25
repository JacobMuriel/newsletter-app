#!/usr/bin/env python3
"""
xcode_deploy.py — Telegram-triggered Xcode device install (Session 13)

Flow:
  1. Send Telegram: "Deploy done. Turn your phone on and reply 'ready'."
  2. Poll Telegram for a message containing "ready" (up to 30 min).
  3. Discover connected device UDID at reply time.
  4. Run xcodebuild, then devicectl install.
  5. Send Telegram with result.

Run this as a background process after a successful Render deploy:
  nohup python3 /path/to/xcode_deploy.py > /tmp/xcode_deploy.log 2>&1 &
"""

import os
import random
import string
import subprocess
import sys
import time

import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
TELEGRAM_BOT_TOKEN = "8595682358:AAHvIm6eu4rntFL2RRkye_t_N3ZyZtl2rOw"
CHAT_ID = "8657007613"

REPO_ROOT = "/Users/jacobmuriel/Desktop/news-app"
XCODE_PROJECT = os.path.join(REPO_ROOT, "Briefing/Briefing/Briefing.xcodeproj")
SCHEME = "Briefing"

POLL_INTERVAL_S = 10
MAX_POLLS = 180  # 30 minutes

BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

# ---------------------------------------------------------------------------
# Telegram helpers
# ---------------------------------------------------------------------------

def send_message(text: str) -> None:
    try:
        requests.post(
            f"{BASE_URL}/sendMessage",
            json={"chat_id": CHAT_ID, "text": text},
            timeout=10,
        )
    except Exception as e:
        print(f"[xcode_deploy] Failed to send Telegram message: {e}", file=sys.stderr)


def get_updates(offset: int) -> list:
    try:
        resp = requests.get(
            f"{BASE_URL}/getUpdates",
            params={"offset": offset, "timeout": 10},
            timeout=20,
        )
        data = resp.json()
        if data.get("ok"):
            return data.get("result", [])
    except Exception as e:
        print(f"[xcode_deploy] getUpdates error: {e}", file=sys.stderr)
    return []


def get_baseline_offset() -> int:
    """Return offset = (latest update_id + 1) so we ignore all old messages."""
    updates = get_updates(offset=-1)
    if updates:
        return updates[-1]["update_id"] + 1
    return 0


# ---------------------------------------------------------------------------
# Device discovery
# ---------------------------------------------------------------------------

def find_device_udid() -> str | None:
    """Find the first real (non-simulator) iOS device via xctrace."""
    import re
    try:
        result = subprocess.run(
            ["xcrun", "xctrace", "list", "devices"],
            capture_output=True, text=True, timeout=15,
        )
        in_devices = False
        for line in result.stdout.splitlines():
            if line.strip() == "== Devices ==":
                in_devices = True
                continue
            if line.strip().startswith("=="):
                in_devices = False
                continue
            if not in_devices:
                continue
            # Skip the Mac itself
            if "MacBook" in line or "Mac " in line:
                continue
            # Real device lines: "Name (OS) (UDID)" — UDID has exactly one dash
            m = re.search(r'\(([0-9A-Fa-f]+-[0-9A-Fa-f]+)\)\s*$', line)
            if m:
                return m.group(1)
    except Exception as e:
        print(f"[xcode_deploy] xctrace error: {e}", file=sys.stderr)
    return None


def find_app_bundle(udid: str) -> str | None:
    """Find the built Briefing.app in DerivedData."""
    try:
        result = subprocess.run(
            ["find", os.path.expanduser("~/Library/Developer/Xcode/DerivedData"),
             "-name", "Briefing.app", "-path", "*/Release-iphoneos/*"],
            capture_output=True, text=True, timeout=10,
        )
        lines = [l.strip() for l in result.stdout.splitlines() if l.strip()]
        if lines:
            return lines[0]
    except Exception as e:
        print(f"[xcode_deploy] DerivedData search error: {e}", file=sys.stderr)
    return None


# ---------------------------------------------------------------------------
# Build and install
# ---------------------------------------------------------------------------

def build_and_install(udid: str) -> None:
    send_message("📲 Build started. This takes ~2 minutes...")

    build_cmd = [
        "xcodebuild",
        "-project", XCODE_PROJECT,
        "-scheme", SCHEME,
        "-destination", f"id={udid}",
        "-configuration", "Release",
        "clean", "build",
    ]

    print(f"[xcode_deploy] Running: {' '.join(build_cmd)}", flush=True)
    result = subprocess.run(build_cmd, capture_output=True, text=True)

    if result.returncode != 0:
        last_lines = "\n".join(result.stderr.strip().splitlines()[-20:])
        send_message(f"❌ Xcode build failed — check the Mac for errors.\n\n{last_lines[:3000]}")
        print("[xcode_deploy] Build failed.", file=sys.stderr)
        return

    print("[xcode_deploy] Build succeeded. Looking for .app bundle...", flush=True)
    app_path = find_app_bundle(udid)

    if not app_path:
        send_message("✅ Build succeeded but couldn't find Briefing.app in DerivedData — install manually via Xcode.")
        return

    print(f"[xcode_deploy] Installing {app_path} to {udid}...", flush=True)
    install_result = subprocess.run(
        ["xcrun", "devicectl", "device", "install", "app",
         "--device", udid, app_path],
        capture_output=True, text=True, timeout=120,
    )

    if install_result.returncode == 0:
        send_message("✅ Briefing installed to device.")
        print("[xcode_deploy] Install complete.", flush=True)
    else:
        err = install_result.stderr.strip()[-1000:]
        send_message(f"❌ Install failed after successful build.\n\n{err}")
        print(f"[xcode_deploy] Install failed: {err}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Main polling loop
# ---------------------------------------------------------------------------

def main() -> None:
    token = "".join(random.choices(string.digits, k=4))
    print(f"[xcode_deploy] Starting. Session token: {token}. Getting baseline offset...", flush=True)
    offset = get_baseline_offset()
    print(f"[xcode_deploy] Baseline offset: {offset}", flush=True)

    send_message(
        f"✅ Deploy complete. Turn your phone on, plug it in, unlock it, "
        f"and reply 'ready {token}' to install Briefing to device."
    )

    for i in range(MAX_POLLS):
        time.sleep(POLL_INTERVAL_S)
        updates = get_updates(offset=offset)

        for update in updates:
            offset = update["update_id"] + 1
            msg = update.get("message") or update.get("edited_message")
            if not msg:
                continue
            text = msg.get("text", "").strip().lower()
            chat_id = str(msg.get("chat", {}).get("id", ""))

            if chat_id != CHAT_ID:
                continue

            if "ready" in text and token in text:
                print("[xcode_deploy] Got 'ready' — discovering device...", flush=True)
                udid = find_device_udid()
                if not udid:
                    send_message(
                        "❌ No device found. Is your phone plugged in and unlocked? "
                        "Reply 'ready' again once it's connected."
                    )
                    continue  # keep polling

                print(f"[xcode_deploy] Device UDID: {udid}", flush=True)
                build_and_install(udid)
                return

        elapsed_min = (i + 1) * POLL_INTERVAL_S // 60
        if (i + 1) % 6 == 0:
            print(f"[xcode_deploy] Still waiting... ({elapsed_min} min elapsed)", flush=True)

    send_message("⏰ Xcode deploy timed out waiting for your reply.")
    print("[xcode_deploy] Timed out.", flush=True)


if __name__ == "__main__":
    main()
