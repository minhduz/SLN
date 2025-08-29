from django.conf import settings
from twilio.rest import Client
import phonenumbers

def normalize_phone_to_e164(raw_phone: str, default_region: str = "VN") -> str:
    """
    Convert user input to E.164. If user types 098..., we assume VN by default.
    """
    num = phonenumbers.parse(raw_phone, default_region)
    if not phonenumbers.is_possible_number(num) or not phonenumbers.is_valid_number(num):
        raise ValueError("Invalid phone number")
    return phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.E164)


def issue_otp(phone_raw: str, purpose: str) -> str:
    """
    Request Twilio Verify to send an OTP.
    """
    phone_e164 = normalize_phone_to_e164(phone_raw)
    client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)

    verification = client.verify.v2.services(settings.TWILIO_VERIFY_SID) \
        .verifications \
        .create(to=phone_e164, channel="sms")

    return phone_e164  # return normalized number


def verify_otp(phone_raw: str, code: str) -> bool:
    """
    Verify OTP with Twilio Verify API.
    """
    phone_e164 = normalize_phone_to_e164(phone_raw)
    client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)

    verification_check = client.verify.v2.services(settings.TWILIO_VERIFY_SID) \
        .verification_checks \
        .create(to=phone_e164, code=code)

    return verification_check.status == "approved"
