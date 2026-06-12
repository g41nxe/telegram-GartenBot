from .event_bus import Event


class ValveStatusReported(Event):
    """Event, das gefeuert wird, wenn ein neuer Ventil-Zustand empfangen wird."""
    def __init__(self, mqtt_name: str, state: str, flow_rate: float, battery: int, linkquality: int, valve_abnormal_state: str = "normal"):
        self.mqtt_name = mqtt_name
        self.state = state
        self.flow_rate = flow_rate
        self.battery = battery
        self.linkquality = linkquality
        self.valve_abnormal_state = valve_abnormal_state


class DeviceJoinedEvent(Event):
    """Event, das gefeuert wird, wenn ein neues Zigbee-Gerät beigetreten ist."""
    def __init__(self, ieee_address: str):
        self.ieee_address = ieee_address
