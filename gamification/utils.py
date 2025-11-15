# gamification/utils.py
from django.utils import timezone
from datetime import datetime, time, timedelta


def get_user_timezone(user):
    """
    Get user's timezone object
    Uses the helper method from User model
    """
    return user.get_timezone()  # ✅ Use the model's helper method


def get_time_until_daily_reset(user):
    """
    Get seconds until next daily reset (2:00 AM in user's timezone)
    """
    user_tz = get_user_timezone(user)

    # Get current time in user's timezone
    now = timezone.now().astimezone(user_tz)
    today = now.date()

    # 2:00 AM today in user's timezone
    reset_time = user_tz.localize(datetime.combine(today, time(2, 0)))

    # If we're past 2:00 AM today, reset is tomorrow at 2:00 AM
    if now >= reset_time:
        tomorrow = today + timedelta(days=1)
        reset_time = user_tz.localize(datetime.combine(tomorrow, time(2, 0)))

    time_left = reset_time - now
    return int(time_left.total_seconds())


def get_time_until_weekly_reset(user):
    """
    Get seconds until next weekly reset (Monday 2:00 AM in user's timezone)
    """
    user_tz = get_user_timezone(user)

    # Get current time in user's timezone
    now = timezone.now().astimezone(user_tz)
    today = now.date()

    # Calculate days until next Monday
    days_until_monday = (7 - today.weekday()) % 7

    if days_until_monday == 0:
        # Today is Monday - check if we're before or after 2 AM
        reset_time = user_tz.localize(datetime.combine(today, time(2, 0)))

        if now >= reset_time:
            # Past 2 AM on Monday, next reset is next Monday
            days_until_monday = 7

    # Calculate next Monday at 2:00 AM in user's timezone
    next_monday = today + timedelta(days=days_until_monday)
    reset_time = user_tz.localize(datetime.combine(next_monday, time(2, 0)))

    time_left = reset_time - now
    return int(time_left.total_seconds())


def should_reset_daily_missions(user):
    """
    Check if it's time to reset daily missions for this user
    (between 2:00 AM and 2:05 AM in their timezone)
    """
    user_tz = get_user_timezone(user)
    now = timezone.now().astimezone(user_tz)

    current_hour = now.hour
    current_minute = now.minute

    # Check if it's between 2:00 and 2:05 AM
    return current_hour == 2 and current_minute < 5


def should_reset_weekly_missions(user):
    """
    Check if it's time to reset weekly missions for this user
    (Monday between 2:00 AM and 2:05 AM in their timezone)
    """
    user_tz = get_user_timezone(user)
    now = timezone.now().astimezone(user_tz)

    is_monday = now.weekday() == 0
    current_hour = now.hour
    current_minute = now.minute

    # Check if it's Monday between 2:00 and 2:05 AM
    return is_monday and current_hour == 2 and current_minute < 5


def get_next_reset_time(user, cycle_type):
    """
    Get the next reset datetime for a given cycle type in user's timezone

    Args:
        user: User instance with timezone field
        cycle_type: 'daily' or 'weekly'

    Returns:
        datetime: Next reset time in user's timezone
    """
    user_tz = get_user_timezone(user)

    # Get current time in user's timezone
    now = timezone.now().astimezone(user_tz)
    today = now.date()

    if cycle_type == 'daily':
        # Next 2:00 AM in user's timezone
        reset_time = user_tz.localize(datetime.combine(today, time(2, 0)))

        if now >= reset_time:
            tomorrow = today + timedelta(days=1)
            reset_time = user_tz.localize(datetime.combine(tomorrow, time(2, 0)))

    elif cycle_type == 'weekly':
        # Next Monday 2:00 AM in user's timezone
        days_until_monday = (7 - today.weekday()) % 7

        if days_until_monday == 0:
            reset_time = user_tz.localize(datetime.combine(today, time(2, 0)))

            if now >= reset_time:
                days_until_monday = 7

        next_monday = today + timedelta(days=days_until_monday)
        reset_time = user_tz.localize(datetime.combine(next_monday, time(2, 0)))
    else:
        return None

    return reset_time


def get_user_current_date(user):
    """
    Get the current date in user's timezone
    """
    user_tz = get_user_timezone(user)
    return timezone.now().astimezone(user_tz).date()