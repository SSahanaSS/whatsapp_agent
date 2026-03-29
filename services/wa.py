from config import client, TWILIO_WHATSAPP_NUMBER
from twilio.base.exceptions import TwilioRestException

def send_whatsapp(to_number, text):
    if not to_number.startswith("whatsapp:"):
        to_number = f"whatsapp:{to_number}"
    try:
        client.messages.create(
            from_=TWILIO_WHATSAPP_NUMBER,
            to=to_number,
            body=text
        )
    except TwilioRestException as e:
        print("Twilio Error:", e)
        print("Fallback message instead of sending:")
        print(text)