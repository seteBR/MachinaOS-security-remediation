from .._base import AndroidServiceBase


class DeviceStateAutomationNode(AndroidServiceBase):
    type = "deviceStateAutomation"
    display_name = "Device State"
    description = "Device state control - airplane mode, screen on/off, brightness"
    tool_name = "android_device_state"
