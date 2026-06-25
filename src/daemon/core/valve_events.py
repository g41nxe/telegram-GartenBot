from .event_bus import Event


class ValveStatusReported(Event):
    """Event, das gefeuert wird, wenn ein neuer Ventil-Zustand empfangen wird.

    `irrigation_volume` trägt die live mitlaufende Menge der aktuellen Bewässerungs-Session
    (`irrigation_schedule_status.actual_irrigation_amount`), NICHT den kumulativen
    `real_time_irrigation_volume`. `schedule_status` ist der Session-Status des Geräts
    (`start`/`running`/`end`); nur bei `running` ist `irrigation_volume` als Guss-Volumen
    gültig. Siehe ADR 0007.
    """
    def __init__(self, mqtt_name: str, state: str, flow_rate: float, battery: int, linkquality: int,
                 valve_abnormal_state: str = "normal", irrigation_volume: float = 0.0,
                 schedule_status: str = None):
        self.mqtt_name = mqtt_name
        self.state = state
        self.flow_rate = flow_rate
        self.battery = battery
        self.linkquality = linkquality
        self.valve_abnormal_state = valve_abnormal_state
        self.irrigation_volume = irrigation_volume
        self.schedule_status = schedule_status


class DeviceJoinedEvent(Event):
    """Event, das gefeuert wird, wenn ein neues Zigbee-Gerät beigetreten ist."""
    def __init__(self, ieee_address: str):
        self.ieee_address = ieee_address
