import hashlib
from datetime import timedelta
from django.utils import timezone
from rest_framework_simplejwt.tokens import RefreshToken as JWTRefreshToken
from rest_framework_simplejwt.exceptions import InvalidToken

from ..models import RefreshToken as RefreshTokenModel


def generate_and_store_tokens(user, request=None):
    """
    Generate new access & refresh tokens,
    store refresh token hash in DB,
    and return both tokens.
    """
    refresh = JWTRefreshToken.for_user(user)
    access_token = str(refresh.access_token)
    refresh_token = str(refresh)

    # Hash refresh token before storing
    token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()

    RefreshTokenModel.objects.create(
        user=user,
        token_hash=token_hash,
        expires_at=timezone.now() + timedelta(days=7),  # match JWT config
        device_info=request.META.get("HTTP_USER_AGENT", "") if request else "",
        ip_address=request.META.get("REMOTE_ADDR", "") if request else "",
    )

    return access_token, refresh_token


def refresh_tokens(refresh_token, request=None):
    """
    Validate and rotate refresh tokens.
    """
    # Hash incoming refresh token
    token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()

    # Check if token exists and is active
    try:
        stored_token = RefreshTokenModel.objects.get(
            token_hash=token_hash, revoked=False
        )
    except RefreshTokenModel.DoesNotExist:
        raise InvalidToken("Refresh token not recognized")

    # Expiration check
    if stored_token.expires_at < timezone.now():
        stored_token.revoked = True
        stored_token.save(update_fields=["revoked"])
        raise InvalidToken("Refresh token expired")

    # Revoke old token
    stored_token.revoked = True
    stored_token.save(update_fields=["revoked"])

    # Generate new tokens + store
    return generate_and_store_tokens(stored_token.user, request)

def revoke_refresh_token(refresh_token: str):
    """
    Revoke a given refresh token.
    """
    token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()

    try:
        stored_token = RefreshTokenModel.objects.get(
            token_hash=token_hash, revoked=False
        )
    except RefreshTokenModel.DoesNotExist:
        raise InvalidToken("Refresh token not recognized")

    stored_token.revoked = True
    stored_token.save(update_fields=["revoked"])
    return True
