# 🇺🇸💭📞 American Dream Phone 🇺🇸💭📞

<img src="images/america.png" width="250px"> + <img src="images/dream-phone-og.jpg" width="240px"> = <img src="images/american-dream-phone-usa-horray.jpeg" width="130px">

> Democracy dies in silence


The first thing you need to know is that in the 90's, there was a board game called [Dream Phone](https://consolemods.org/wiki/Dreamphone). This is a real thing that exists.
With that whimsy in mind, `American Dream Phone` is a Voice AI Agent [Pipecat](https://github.com/pipecat-ai/pipecat) app to call your representatives. Revenge of the robo-calls. But also, civic engagement. Yay.

## dependencies

- Python 3.10+
- API keys. See [services](##services).

## setup

```bash
cp env.example .env
```
Add API keys as needed. All services (transport, LLM, STT, and TTS) are all changeable. See [services](##services).

```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## run

### server

```bash
python bot_runner.py
```

### make a call

#### test (webrtc)
```bash
curl -X POST "http://localhost:7860/start" \
-H "Content-Type: application/json" \
-d '{
  "config": {"testInPrebuilt": true}
 }'
==>
{"status":"Bot started","bot_type":"bot","room_url":"https://YOUR_DOMAIN.daily.co/ROOM"}
```
This will return a daily prebuilt URL. Navigate there to talk to and test the bot.

#### phone call
```bash
curl -X POST "http://localhost:7860/start" \
-H "Content-Type: application/json" \
-d '{
  "config": {
    "dialout_settings": [{
        "phoneNumber": "+15551234567"
      }]
    }
 }'
==>
{"status":"Bot started","bot_type":"bot","dialing_to":"phone:+15551234567"}
```
This actually calls the phone number.

## services
By using pipecat, all services (transport, LLM, STT, and TTS) are all changeable. These are just the ones I started with.

- "Orchestration"
	- [`Pipecat`](https://github.com/pipecat-ai/pipecat) - ᓚᘏᗢ Python framework; the glue that makes it all possible.
- transport
	- [`Daily`](https://www.daily.co/) - webrtc transport [docs](https://docs.pipecat.ai/client/ios/transports/daily)
	- The domain needs to have dialout enabled and a phone number purchased. 
- LLM
	- [`OpenAI`](https://platform.openai.com/api-keys)
- STT
	- [`Cartesia`](https://play.cartesia.ai/keys)
- TTS
	- [`PlayAI`](https://app.play.ht/api/keys)
   	- I used this service to clone my voice.
- MCP server for fetch
	- mcp.run - [`"mcp.run"`](https://www.mcp.run/)
	- Connect as many MCP servers as you like...

## TODO list / notes to self / ideas / creedthoughts

- use some API to get rep phone numbers like https://5calls.org/representatives-api/ (maybe an MCP around this?)
- call before or after hours to focus on leaving messages; less on voicemail detection.

## credits

- huge shout out to [this pipecat example](https://github.com/pipecat-ai/pipecat/tree/main/examples/phone-chatbot)
- [E l e c t r o n i c Dream Phone](https://consolemods.org/wiki/Dreamphone)
