"""Connector wiring registry (L3 local extension).

Decides which :class:`~local_ingestion.core.connectors.base.SourceConnector`
serves a given ``ds_type``. Implementations stay in ``core.connectors`` (L1
upstream sync area); only the mapping lives here.

Third-party datasources register a :class:`ConnectorSpec` through the
``local_ingestion.connectors`` entry-point group or
``LOCAL_INGESTION_CONNECTOR_SPECS`` — no code change and no rebuild.
"""
from .registry import (
    BUILTIN_SPECS,
    ENV_SPECS,
    ENTRY_POINT_GROUP,
    ConnectorImportError,
    ConnectorRegistryError,
    ConnectorSpec,
    UnknownConnectorError,
    build_connection,
    connection_options,
    get_spec,
    known_specs,
    load_external,
    make_connector,
    register,
    reset_to_builtins,
    resolve,
    supported_ds_types,
    unregister,
)

__all__ = [
    "BUILTIN_SPECS",
    "ENV_SPECS",
    "ENTRY_POINT_GROUP",
    "ConnectorImportError",
    "ConnectorRegistryError",
    "ConnectorSpec",
    "UnknownConnectorError",
    "build_connection",
    "connection_options",
    "get_spec",
    "known_specs",
    "load_external",
    "make_connector",
    "register",
    "reset_to_builtins",
    "resolve",
    "supported_ds_types",
    "unregister",
]
