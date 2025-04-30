# 🇺🇸💭📞 American Dream Phone 🇺🇸💭📞

<img src="images/america.png" width="250px"> + <img src="images/dream-phone-og.jpg" width="240px"> = <img src="images/american-dream-phone-usa-horray.jpeg" width="130px">

> Democracy dies in silence


`American Dream Phone` is a Voice AI Agent [Pipecat](https://github.com/pipecat-ai/pipecat) app to call your representatives. Revenge of the robo-calls. But also, civic engagement. Yay.
Actual LLM service, STT service, and TTS services are all changeable.

## setup

set env vars
```bash
cp env.example .env
```

### options
todo
- llm
- stt
- tts
- ...


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
- [e l e c t r o n i c Dream Phone](https://consolemods.org/wiki/Dreamphone)

