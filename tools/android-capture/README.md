# Veridex Capture for Android (in progress)

Open this directory as an Android Studio project. This first slice pairs with a
Veridex server in LAN mode on port 8765 using its one-time pairing URL. The
session cookie is stored in the app's private preferences and is not backed up.
The connection uses HTTP on trusted private Wi-Fi, matching Veridex LAN mode.

Screen capture, delivery and review are not implemented yet. Do not treat this
project as a complete capture app. Build requirements: Android SDK 36 and the
Gradle version required by Android Gradle Plugin 8.13.2.
