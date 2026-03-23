# SESSION_13 — Telegram-Triggered Xcode Deploy
Last updated: March 21, 2026

---

## Goal

Extend the deploy flow with a two-phase process:

- **Phase 1 (automated):** Pipeline → Render deploy → Telegram message: "Deploy done. Turn your phone on and reply 'ready' to install to device."
- **Phase 2 (triggered):** A polling script running on the Mac waits for the Telegram reply, then runs `xcodebuild` to build and install the app to the connected iPhone.

This is needed because Xcode device install requires the phone to be on, unlocked, and trusted — so it can't be part of the fully automated Phase 1.

---

## Step 0 — Discover Local Paths and Config

Before writing any code, Claude Code must run the following discovery commands and use the real values in all generated scripts. Do not hardcode assumptions.

### 0a. Find the repo root

```bash
git rev-parse --show-toplevel
```

Store this as `REPO_ROOT`. All paths in generated scripts must be absolute using this value.

### 0b. Find the Xcode project

```bash
find "$REPO_ROOT" -name "*.xcodeproj" -maxdepth 5 2>/dev/null
find "$REPO_ROOT" -name "*.xcworkspace" -maxdepth 5 2>/dev/null
```

Pick the correct project/workspace file. Based on project history, expect something like `Briefing/Briefing/Briefing.xcodeproj` or a `.xcworkspace`. Use the workspace if one exists (CocoaPods/SPM projects require it).

### 0c. Find the Xcode scheme

```bash
xcodebuild -list -project <path_from_0b>
# or if workspace:
xcodebuild -list -workspace <path_from_0b>
```

The scheme name is expected to be `Briefing` based on project history. Confirm it appears in the output.

### 0d. Find the connected device UDID

```bash
xcrun devicectl list devices 2>/dev/null
# fallback if devicectl not available:
xcrun xctrace list devices 2>/dev/null
```

Look for an iPhone in the output. Extract the UDID (long hex string). If no device is found (phone is off/unplugged), that's expected — the script will discover it at runtime when the phone is actually connected.

### 0e. Find the Telegram bot token

Check in this order:
1. `echo $TELEGRAM_BOT_TOKEN`
2. `cat ~/.env` or `cat ~/.secrets` or `cat "$REPO_ROOT/.env"` — look for a `TELEGRAM_BOT_TOKEN=` line
3. `cat "$REPO_ROOT/_app_build/secrets.env"` if it exists

If found, store it. If not found anywhere, **stop and ask the user**: "I can't find your TELEGRAM_BOT_TOKEN. Where is it stored, or please paste it and I'll add it to your .env."

The Telegram chat ID is `8657007613` — hardcode this in the script.

---

## Step 1 — Create `scripts/xcode_deploy.py`

Create `$REPO_ROOT/scripts/xcode_deploy.py`. This script:

1. Sends a Telegram message: `"✅ Deploy complete. Turn your phone on, plug it in, unlock it, and reply 'ready' to install Briefing to device."`
2. Polls the Telegram bot for a reply containing the word `ready` (case-insensitive)
3. On match: runs `xcodebuild` to build and install to the device
4. Sends a follow-up Telegram: `"📲 Build started. This takes ~2 minutes..."` then `"✅ Briefing installed to device."` or `"❌ Xcode build failed — check the Mac for errors."`

### Script requirements

- **Pure Python stdlib + `requests`** — no new dependencies beyond what's already used in the project
- **Timeout:** Poll for up to 30 minutes (180 iterations × 10s sleep). If no reply, send `"⏰ Xcode deploy timed out waiting for your reply."` and exit.
- **Deduplication:** Track the `update_id` of the last processed Telegram message so the script doesn't re-trigger on old messages. On startup, call `getUpdates` once with `offset=-1` to get the latest update_id and use that as the baseline — only process messages newer than this.
- **Device discovery at runtime:** At the moment the user replies `ready`, run `xcrun devicectl list devices` again to find the UDID of the connected phone. Don't rely on a UDID discovered at script-write time since the phone won't be plugged in during Phase 1.
- **Xcode build command shape:**

```bash
xcodebuild \
  -workspace <WORKSPACE_PATH> \     # or -project if no workspace
  -scheme Briefing \
  -destination "id=<DEVICE_UDID>" \
  -configuration Release \
  clean build
```

Use `subprocess.run(..., capture_output=True, text=True)`. Check `returncode == 0`. If non-zero, include the last 20 lines of stderr in the failure Telegram message.

- **After successful build**, also run:

```bash
xcrun devicectl device install app \
  --device <DEVICE_UDID> \
  <path_to_.app_bundle>
```

The `.app` bundle path is typically inside `~/Library/Developer/Xcode/DerivedData/Briefing-.../Build/Products/Release-iphoneos/Briefing.app`. Find it dynamically with:

```bash
find ~/Library/Developer/Xcode/DerivedData -name "Briefing.app" -path "*/Release-iphoneos/*" 2>/dev/null | head -1
```

If `devicectl` is unavailable (older Xcode), fall back to `ios-deploy` if installed, otherwise note in the Telegram failure message that manual install is needed.

### Telegram API helpers

Use these endpoints directly with `requests` (no third-party Telegram library):

```
GET https://api.telegram.org/bot{TOKEN}/getUpdates?offset={offset}&timeout=10
POST https://api.telegram.org/bot{TOKEN}/sendMessage  body: {"chat_id": "8657007613", "text": "..."}
```

---

## Step 2 — Update the deploy notification call site

Find where the existing Telegram notification is sent after a successful deploy. Based on project history this is likely in `cron_pipeline.py` or a deploy script. Search:

```bash
grep -r "telegram\|8657007613\|sendMessage" "$REPO_ROOT" --include="*.py" -l
```

In that file, after the existing "deploy complete" Telegram message, add a call to launch `xcode_deploy.py` as a **background subprocess** so it doesn't block the pipeline:

```python
import subprocess, sys, os
scripts_dir = os.path.join(os.path.dirname(__file__), "scripts")
subprocess.Popen(
    [sys.executable, os.path.join(scripts_dir, "xcode_deploy.py")],
    start_new_session=True,   # detach from parent process
)
```

If the Telegram notification lives in a shell script instead of Python, launch it with:

```bash
nohup python3 "$REPO_ROOT/scripts/xcode_deploy.py" > /tmp/xcode_deploy.log 2>&1 &
```

**Do not** await this process. It runs independently in the background while the pipeline exits normally.

---

## Step 3 — Make the script executable and test the Telegram leg

```bash
chmod +x "$REPO_ROOT/scripts/xcode_deploy.py"
```

Do a dry run of just the Telegram polling leg (without triggering the actual Xcode build) to confirm:
1. The bot token is valid
2. The chat ID receives the "turn your phone on" message
3. Replying "ready" is detected within one poll cycle

To test without triggering a real build, temporarily stub the build step with `print("BUILD WOULD RUN HERE")` and restore it after confirmation.

---

## Step 4 — Commit

```bash
cd "$REPO_ROOT"
git add scripts/xcode_deploy.py
git add <any modified files from Step 2>
git commit -m "feat: Telegram-triggered Xcode deploy (Session 13)"
git push origin main
```

The iOS submodule (`Briefing/Briefing`) has no remote configured — do not attempt to push it. Only push from the repo root.

---

## What NOT to do

- Do not add `xcode_deploy.py` to the GitHub Actions cron workflow — this only runs locally on the Mac
- Do not block the pipeline on the Telegram poll — it must be fire-and-forget
- Do not hardcode the UDID in the script — discover it at runtime when the phone is connected
- Do not install new Python packages beyond `requests` (already a project dependency)
- Do not attempt `xcodebuild` without first confirming a device UDID was found — if no device is detected after the user replies "ready", send `"❌ No device found. Is your phone plugged in and unlocked?"` and re-enter the polling loop for another attempt

---

## Success Criteria

- `scripts/xcode_deploy.py` exists and is executable
- Running the script sends the "turn your phone on" Telegram message
- Replying "ready" triggers `xcodebuild` and sends status updates
- The pipeline deploy flow (Phase 1) is unaffected — same timing, same final Telegram message, plus the background launch of the new script
- No new Python package dependencies introduced
