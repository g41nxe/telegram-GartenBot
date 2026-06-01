import threading
from typing import Type, Callable, Dict, List, Any

class Event:
    """Basisklasse für alle Ereignisse (Events) im System."""
    pass

class EventBus:
    """Ein thread-sicherer, synchroner systeminterner Ereignis-Kanal (Event Bus)."""
    def __init__(self):
        self._listeners: Dict[Type[Event], List[Callable[[Any], None]]] = {}
        self._lock = threading.Lock()

    def subscribe(self, event_type: Type[Event], callback: Callable[[Any], None]):
        """Registriert einen Listener-Callback für einen bestimmten Event-Typ."""
        with self._lock:
            if event_type not in self._listeners:
                self._listeners[event_type] = []
            self._listeners[event_type].append(callback)

    def publish(self, event: Event):
        """Verteilt ein Event synchron an alle registrierten Listener dieses Event-Typs."""
        event_type = type(event)
        callbacks = []
        
        with self._lock:
            if event_type in self._listeners:
                # Kopieren der Liste unter Lock, um Race Conditions beim Aufruf zu verhindern
                callbacks = list(self._listeners[event_type])
        
        for callback in callbacks:
            try:
                callback(event)
            except Exception as e:
                # Verhindert, dass Fehler in einem Listener andere blockieren oder das System crashen
                import logging
                logging.getLogger("garden_event_bus").error(
                    f"Fehler beim Ausführen des Event-Listeners {callback.__name__ if hasattr(callback, '__name__') else callback} für {event_type.__name__}: {e}"
                )
