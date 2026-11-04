"""Clients for the external systems Bonkverse talks to, one module per system.

Owns: URLs, request shapes, headers, timeouts, response parsing and token
redaction for each external system (RFC-0001). Only modules in this package
import `requests` (tests/test_architecture.py keeps the list of exceptions).
Does not own: models, Django request objects, or what users see.
"""
