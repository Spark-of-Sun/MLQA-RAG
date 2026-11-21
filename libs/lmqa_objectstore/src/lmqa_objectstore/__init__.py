"""S3 adapter with application-level envelope encryption (doc 10.2, 12.3)."""

from lmqa_objectstore.store import ObjectNotFoundError, ObjectStore, object_key, quarantine_key

__all__ = ["ObjectNotFoundError", "ObjectStore", "object_key", "quarantine_key"]
