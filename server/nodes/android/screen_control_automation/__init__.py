from .._base import AndroidServiceBase


class ScreenControlAutomationNode(AndroidServiceBase):
    type = "screenControlAutomation"
    display_name = "Screen Control"
    description = "Screen control - brightness, wake screen, auto-brightness"
    tool_name = "android_screen_control"
