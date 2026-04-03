import json

from typing import Any, Dict, List, Optional


class DialOutHelper:
    def __init__(self, body):
        super().__init__()

        self._body = json.loads(body) if body else {}

    async def start_dialout(self, transport, dialout_settings=None):
        """Helper function to start dialout using the provided settings or from body.

        Args:
            transport: The transport instance to use for dialout
            dialout_settings: Optional override for dialout settings

        Returns:
            None
        """
        # Use provided settings or get from body
        settings = dialout_settings or self.get_dialout_settings()
        if not settings:
            print("No dialout settings available")
            return

        for setting in settings:
            if "phoneNumber" in setting:
                print(f"Dialing number: {setting['phoneNumber']}")
                if "callerId" in setting:
                    print(f"with callerId: {setting['callerId']}")
                    await transport.start_dialout(
                        {
                            "phoneNumber": setting["phoneNumber"],
                            "callerId": setting["callerId"],
                        }
                    )
                else:
                    print("with no callerId")
                    await transport.start_dialout(
                        {"phoneNumber": setting["phoneNumber"]}
                    )
            elif "sipUri" in setting:
                print(f"Dialing sipUri: {setting['sipUri']}")
                await transport.start_dialout({"sipUri": setting["sipUri"]})
            else:
                print(f"Unknown dialout setting format: {setting}")

    def get_dialout_settings(self) -> Optional[List[Dict[str, Any]]]:
        """Extract dialout settings from the body.

        Returns:
            List of dialout setting objects or None if not present
        """
        # Check if we have dialout settings
        if "dialout_settings" in self._body:
            dialout_settings = self._body["dialout_settings"]

            # Convert to list if it's an object (for backward compatibility)
            if isinstance(dialout_settings, dict):
                return [dialout_settings]
            elif isinstance(dialout_settings, list):
                return dialout_settings

        return None

    def get_is_test_mode(self) -> Optional[List[Dict[str, Any]]]:
        print(f"_____bot_helper.py * self._body: {self._body}")
        test_mode = False
        if "testInPrebuilt" in self._body:
            test_mode = True
        print(f"_____bot_helper.py * test_mode: {test_mode}")

        return test_mode
