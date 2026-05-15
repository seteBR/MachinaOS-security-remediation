from .._base import AndroidServiceBase


class AppListNode(AndroidServiceBase):
    type = "appList"
    display_name = "App List"
    description = "Get list of installed applications"
    tool_name = "android_app_list"
