"""Application-layer composition helpers.

This package owns wiring between infrastructure services and the desktop UI. Keeping
composition here prevents the bootstrap module from becoming a second service layer.
"""

from mcmahon_dispatch.application.services import ServiceContainer, build_services

__all__ = ["ServiceContainer", "build_services"]
