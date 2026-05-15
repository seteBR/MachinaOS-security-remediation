from .._base import AndroidServiceBase


class EnvironmentalSensorsNode(AndroidServiceBase):
    type = "environmentalSensors"
    display_name = "Environmental Sensors"
    description = "Temperature, humidity, pressure, light level"
    tool_name = "android_environmental_sensors"
