"""Telegram bot for TutorTab.

A separate process (`python -m bot.main`) that talks to the same database as
the API directly through SQLAlchemy sessions — it does not call the HTTP API.
"""
