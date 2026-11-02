# Reusable local tools

## Phone capture requests (in progress)

`phone_capture.py` provides an in-memory, short-lived, single-use request token
bound to a workspace and session. Import `CaptureRequests` from
`tools.phone_capture`. Requests expire after 120 seconds by default and are lost
when the process stops. The helper does not authenticate devices, capture images,
transfer files, or verify artifacts; callers must provide those boundaries.

Veridex's Betting capture receiver uses this helper. The Android companion and
complete capture/review workflow are not yet available, so this is not a finished
standalone tool.

`android-capture/` contains the in-progress Android companion project; its first
slice pairs a phone with Veridex LAN mode. See its README for current limits.
