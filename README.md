# 🇺🇸💭📞 American Dream Phone 🇺🇸💭📞

<img src="images/america.png" width="250px"> + <img src="images/dream-phone-og.jpg" width="240px"> = <img src="images/american-dream-phone-usa-horray.jpeg" width="130px">

> Democracy dies in silence

See a demo of it in action [here](https://www.loom.com/share/ce0e8051e8cb430285a137ef290f0364).


The first thing you need to know is that in the 90's, there was a board game called [Dream Phone](https://consolemods.org/wiki/Dreamphone). This is a real thing that exists.
With that whimsy in mind, `American Dream Phone` is a [Pipecat](https://github.com/pipecat-ai/pipecat) AI Voice Agent to help you call your political representatives. Some may call it 'revenge of the robo-calls', I call it civic engagement.

## dependencies

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- API keys. See [services](##services).

## setup

```bash
cp env.example .env
```
Add API keys as needed. See [services](##services).

```bash
uv sync
```

## run

### start the server

```bash
uv run python bot.py -t daily
```

### make a call

#### test (webrtc)
```bash
curl -X POST http://localhost:7860/start \
  -H "Content-Type: application/json" \
  -d '{"createDailyRoom": true, "body": {"testInPrebuilt": true}}'
```
The response includes a `dailyRoom` URL. Open it in your browser to talk to and test the bot.

#### phone call
```bash
curl -X POST http://localhost:7860/start \
  -H "Content-Type: application/json" \
  -d '{"createDailyRoom": true, "dailyRoomProperties": {"enable_dialout": true}, "body": {"dialout_settings": [{"phoneNumber": "+15551234567"}]}}'
```
This actually calls the phone number. (Debug pro tip — open the `dailyRoom` URL and listen in on the conversation.)

## services
By using pipecat, all services (transport, LLM, STT, and TTS) are all changeable. These are just the ones I started with.

- "Orchestration"
	- [`Pipecat`](https://github.com/pipecat-ai/pipecat) - Python framework; the glue that makes it all possible.
- Transport
	- [`Daily`](https://www.daily.co/) - webrtc transport [docs](https://docs.pipecat.ai/client/ios/transports/daily)
	- The domain needs to have dialout enabled and a phone number purchased.
- LLM
	- [`Anthropic Claude`](https://console.anthropic.com/)
- STT
	- [`Deepgram`](https://console.deepgram.com/)
- TTS
	- [`Cartesia`](https://play.cartesia.ai/keys)

## testing

With the bot server running (`uv run python bot.py -t daily`), use the test harness:

```bash
# Browser test — talk to the bot directly, verify IVR detection + conversation
./test_calls.sh webrtc

# Phone test — calls TEST_PHONE_NUMBER, verify IVR nav + voicemail/human routing
TEST_PHONE_NUMBER=+15551234567 ./test_calls.sh dialout

# Run both
TEST_PHONE_NUMBER=+15551234567 ./test_calls.sh all
```

Each test starts a session and returns a Daily room URL. Open it in your browser to watch both the bot and telephony participant in real time.

## TODO list / notes to self / ideas / creedthoughts

- use some API to auto get representative phone numbers like https://5calls.org/representatives-api/ (maybe an MCP around this?)

## credits

- huge shout out to [this pipecat example](https://github.com/pipecat-ai/pipecat/tree/main/examples/phone-chatbot)
- [E l e c t r o n i c Dream Phone](https://consolemods.org/wiki/Dreamphone)
