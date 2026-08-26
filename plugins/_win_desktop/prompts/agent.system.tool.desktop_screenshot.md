### desktop_screenshot
capture the user's real Windows desktop and look at it
takes no arguments
returns the screen resolution and attaches the image for you to see

use when:
- the user refers to something on their screen ("what does this say", "fix this error")
- you need to confirm the state of a GUI application before or after acting on it
- verifying the result of a desktop_control action

notes:
- this is the live desktop of the signed-in user, not a virtual display
- coordinates you report or pass to `desktop_control` must be in screen
  space (the resolution stated in the result), not the attached image's size
- do not call it repeatedly in a loop; take one screenshot, act, then take
  another to verify

example:
~~~json
{
  "thoughts": ["I need to see what is currently on the user's screen."],
  "headline": "Looking at the desktop",
  "tool_name": "desktop_screenshot",
  "tool_args": {}
}
~~~
