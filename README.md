# 🇺🇸💭📞 American Dream Phone 🇺🇸💭📞

<img src="images/america.png" width="250px"> + <img src="images/dream-phone-og.jpg" width="240px"> = <img src="images/american-dream-phone-usa-horray.jpeg" width="130px">

> Democracy dies in silence


The first thing you need to know is that in the 90's, there was a board game called Electronic Dream Phone. This is a real thing that existed.
With that whimsy in mind, `American Dream Phone` is a Voice AI Agent [Pipecat](https://github.com/pipecat-ai/pipecat) app to call your representatives. Revenge of the robo-calls. But also, civic engagement. Yay.

> LLM, STT, and TTS (& more) services are all changeable.

## setup

set env vars
```bash
cp env.example .env
```

```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### services
By using pipecat, all services (transport, LLM, STT, and TTS) can all be changed. These are just the ones I started with.

- "Orchestration"
	- [pipecat](https://github.com/pipecat-ai/pipecat) - Python framework; the glue that makes it all possible.
- transport
	- [Daily](https://www.daily.co/) - webrtc transport [docs](https://docs.pipecat.ai/client/ios/transports/daily)
- LLM
	- OpenAI - get API key at [`"platform.openai.com/api-keys"`](https://platform.openai.com/api-keys)
- STT
	- Cartesia - get API key at [`"play.cartesia.ai/keys"`](https://play.cartesia.ai/keys)
- TTS
	- PlayAI - get API key at [`"app.play.ht/api/keys"`](https://app.play.ht/api/keys)
- MCP server for fetch
	- mcp.run - [`"mcp.run"`](https://www.mcp.run/)
	- connect as many MCP servers as you like...


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
```

#### phone call
```bash
curl -X POST "http://localhost:7860/start" \
-H "Content-Type: application/json" \
-d '{
  "config": {
    "dialout_settings": [{
        "phoneNumber": "+15551234567",
      }],
    }
 }'
```

## credits

- huge shout out to [this pipecat example](https://github.com/pipecat-ai/pipecat/tree/main/examples/phone-chatbot)
- [E l e c t r o n i c Dream Phone](https://consolemods.org/wiki/Dreamphone)

