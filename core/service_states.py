"""
Service States
==============
Enumeration of all possible service states for the ServiceManager.
"""

from enum import Enum


class ServiceState(Enum):
    """Possible states for a service"""
    DISABLED = "disabled"      # Service is disabled in config
    STARTING = "starting"      # Service is starting up
    RUNNING = "running"        # Service is running normally
    DEGRADED = "degraded"      # Service is running but with reduced functionality
    FAILED = "failed"          # Service failed to start or crashed
    STOPPED = "stopped"        # Service was stopped gracefully
    STOPPING = "stopping"      # Service is in the process of stopping


class ServiceHealth(Enum):
    """Health status of a service"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


# State transition rules: which states can transition to which
VALID_TRANSITIONS = {
    ServiceState.DISABLED: [ServiceState.STARTING],
    ServiceState.STARTING: [ServiceState.RUNNING, ServiceState.DEGRADED, ServiceState.FAILED],
    ServiceState.RUNNING: [ServiceState.DEGRADED, ServiceState.FAILED, ServiceState.STOPPING, ServiceState.STOPPED],
    ServiceState.DEGRADED: [ServiceState.RUNNING, ServiceState.FAILED, ServiceState.STOPPING, ServiceState.STOPPED],
    ServiceState.FAILED: [ServiceState.STARTING, ServiceState.STOPPED],
    ServiceState.STOPPING: [ServiceState.STOPPED],
    ServiceState.STOPPED: [ServiceState.STARTING, ServiceState.DISABLED],
}


def can_transition(from_state: ServiceState, to_state: ServiceState) -> bool:
    """Check if a state transition is valid"""
    return to_state in VALID_TRANSITIONS.get(from_state, [])