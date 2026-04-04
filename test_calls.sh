#!/usr/bin/env bash
#
# Test harness for American Dream Phone
#
# Prerequisites:
#   1. Bot server running: uv run python bot.py -t daily
#   2. .env has all required API keys
#   3. Set TEST_PHONE_NUMBER for phone tests (optional)
#
# Usage:
#   ./test_calls.sh webrtc       # Test basic conversation (opens browser room)
#   ./test_calls.sh dialout      # Test phone dialout (requires TEST_PHONE_NUMBER)
#   ./test_calls.sh all          # Run all tests
#

set -euo pipefail

BOT_URL="${BOT_URL:-http://localhost:7860}"
TEST_PHONE_NUMBER="${TEST_PHONE_NUMBER:-}"

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}[TEST]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
err()  { echo -e "${RED}[FAIL]${NC} $1"; }

check_server() {
    log "Checking bot server at $BOT_URL..."
    if ! curl -sf "$BOT_URL" > /dev/null 2>&1; then
        # The runner may not have a root endpoint, try /start with bad data
        # just to see if something is listening
        if ! curl -sf -o /dev/null -w "%{http_code}" -X POST "$BOT_URL/start" \
            -H "Content-Type: application/json" -d '{}' 2>/dev/null | grep -qE "^[245]"; then
            err "Bot server not reachable at $BOT_URL"
            echo "Start it with: uv run python bot.py -t daily"
            exit 1
        fi
    fi
    log "Server is up."
}

# ============================================================
# Test 1: WebRTC browser test (basic conversation + IVR detect)
# ============================================================
test_webrtc() {
    log "=== Test: WebRTC browser session ==="
    log "Starting bot in test mode (no dialout)..."

    RESPONSE=$(curl -s -X POST "$BOT_URL/start" \
        -H "Content-Type: application/json" \
        -d '{"createDailyRoom": true, "body": {"testInPrebuilt": true}}')

    echo "$RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$RESPONSE"

    ROOM_URL=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('dailyRoom',''))" 2>/dev/null)

    if [ -z "$ROOM_URL" ]; then
        err "No dailyRoom URL in response"
        return 1
    fi

    log "Room URL: $ROOM_URL"
    echo ""
    log "Manual test steps:"
    echo "  1. Open the room URL in your browser"
    echo "  2. Talk to the bot — it should detect you as a human (not IVR/voicemail)"
    echo "  3. The IVR navigator should fire on_conversation_detected"
    echo "  4. Bot should switch to human conversation pipeline"
    echo "  5. Bot should greet you as Vanessa and discuss constituent concerns"
    echo "  6. Say 'that is all' — bot should say goodbye and terminate"
    echo ""

    # Open in browser if possible
    if command -v open &> /dev/null; then
        read -p "Open room in browser? [Y/n] " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Nn]$ ]]; then
            open "$ROOM_URL"
        fi
    fi

    log "=== WebRTC test started ==="
}

# ============================================================
# Test 2: Phone dialout (IVR navigation + voicemail/human routing)
# ============================================================
test_dialout() {
    log "=== Test: Phone dialout ==="

    if [ -z "$TEST_PHONE_NUMBER" ]; then
        err "TEST_PHONE_NUMBER not set. Export it or add to .env:"
        echo "  export TEST_PHONE_NUMBER=+15551234567"
        return 1
    fi

    log "Dialing $TEST_PHONE_NUMBER..."

    RESPONSE=$(curl -s -X POST "$BOT_URL/start" \
        -H "Content-Type: application/json" \
        -d "{\"createDailyRoom\": true, \"body\": {\"dialout_settings\": [{\"phoneNumber\": \"$TEST_PHONE_NUMBER\"}]}}")

    echo "$RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$RESPONSE"

    ROOM_URL=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('dailyRoom',''))" 2>/dev/null)

    if [ -z "$ROOM_URL" ]; then
        err "No dailyRoom URL in response"
        return 1
    fi

    log "Room URL (listen in): $ROOM_URL"
    echo ""
    log "Manual verification:"
    echo "  1. Open the room URL to listen in on the call"
    echo "  2. Watch server logs for:"
    echo "     - 'Dial-out answered' — phone was picked up"
    echo "     - 'IVR status changed' — IVR detection events"
    echo "     - 'Conversation detected' — human/voicemail classification"
    echo "     - 'Voicemail detected' OR 'Human detected' — routing decision"
    echo "  3. If voicemail: bot should leave the voicemail message and hang up"
    echo "  4. If human: bot should switch to conversation pipeline as Vanessa"
    echo ""

    if command -v open &> /dev/null; then
        read -p "Open room to listen in? [Y/n] " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Nn]$ ]]; then
            open "$ROOM_URL"
        fi
    fi

    log "=== Dialout test started ==="
}

# ============================================================
# Main
# ============================================================
usage() {
    echo "Usage: $0 {webrtc|dialout|all}"
    echo ""
    echo "  webrtc   - Browser test: basic conversation + IVR detection"
    echo "  dialout  - Phone test: IVR nav + voicemail/human routing"
    echo "  all      - Run all tests"
    echo ""
    echo "Environment variables:"
    echo "  BOT_URL            Bot server URL (default: http://localhost:7860)"
    echo "  TEST_PHONE_NUMBER  Phone number for dialout test (e.g. +15551234567)"
}

case "${1:-}" in
    webrtc)
        check_server
        test_webrtc
        ;;
    dialout)
        check_server
        test_dialout
        ;;
    all)
        check_server
        test_webrtc
        echo ""
        test_dialout
        ;;
    *)
        usage
        exit 1
        ;;
esac
