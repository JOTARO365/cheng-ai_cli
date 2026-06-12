"""Alert delivery — the one outbound the agent is allowed (Line / Teams / Email).

Opt-in by design: a channel only fires if its credential is set in .env. With the
default (empty) config nothing leaves the machine — see alert/dispatch.py.
"""
