### desktop_screenshot
capture the user's real Windows desktop (all monitors as one image) and look at it; no arguments
use when the user refers to something on screen, or to check a GUI before/after acting
- coordinates for `desktop_control` are in the desktop size the result states, from the image's top-left, not the image's pixel size
- one screenshot, act, then one more to verify; never loop it
~~~json
{"thoughts": ["Check what is on the user's screen"], "headline": "Looking at the desktop", "tool_name": "desktop_screenshot", "tool_args": {}}
~~~
