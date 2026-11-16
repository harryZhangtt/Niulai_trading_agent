"""Workspace-local scheduling and model execution infrastructure.

Submodules own their explicit imports.  Importing this package performs no eager
business/model/provider loading, so source-attested candidates can bind only the
modules they execute.
"""
