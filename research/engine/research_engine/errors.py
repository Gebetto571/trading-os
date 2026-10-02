"""Fail-closed errors surfaced by the local research process."""


class EngineError(RuntimeError):
    """Base error for a rejected A0 operation."""


class ConfigError(EngineError):
    """The strictly limited local TOML configuration is invalid."""


class DatasetIntegrityError(EngineError):
    """The requested read-only dataset is missing, unsafe, or mismatched."""


class RegistryBusy(EngineError):
    """Another registry writer owns the SQLite write boundary."""


class RegistryConflict(EngineError):
    """A non-completed record prevents an idempotent result from being reused."""


class RuntimeBoundaryError(EngineError):
    """A runtime path could escape A0's owned local storage boundary."""
