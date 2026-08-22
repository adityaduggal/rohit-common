#  Copyright (c) 2026. Rohit Industries Group Private Limited and Contributors.
#  For license information, please see license.txt
# -*- coding: utf-8 -*-
"""
Thin GSP-provider contract, per docs/designs/gst-asp-migration-whitebooks.md
(Approach B). Any module implementing this contract can serve as the
auth/base-URL layer behind india_gst_api's payload builders
(einv.py, eway_bill_api.py, gst_public_api.py).

Structural typing only (typing.Protocol) — a provider module is a set of
three module-level functions, not a class. This mirrors gsp_session.py's
existing functional style rather than introducing a class hierarchy for a
single real implementation. whitebooks_provider.py is the only
implementation; a future ASP swap gets a new module implementing the same
three functions, not a rewrite of the modules that call them.
"""
from typing import Protocol


class GSPProvider(Protocol):
    def get_headers(self, api_name: str) -> dict:
        """Auth headers for a call to the named API family.

        api_name is one of "einvoice", "eway", "gst" (Public GST API) —
        see whitebooks_provider.API_FAMILIES. Implementations may return
        the same headers for every family (WhiteBooks does, per its single
        OAuth2 mechanism) or vary them per family.
        """
        ...

    def get_base_url(self, api_name: str) -> str:
        """Base URL for the named API family, sandbox- or production-scoped
        per the caller's own environment selection (see
        common.get_base_url's sandbox_mode pattern)."""
        ...

    def refresh_session(self, api_name: str) -> None:
        """Invalidate any cached auth state for the named API family,
        forcing the next get_headers(api_name) call to fetch fresh
        credentials. Call after a 401/session-invalid response — see
        gsp_session.invalidate_session() for the existing precedent this
        mirrors. Takes api_name (revised 2026-08-22) because WhiteBooks
        issues separate credentials per API family, so cached auth state
        is per-family too, not global."""
        ...
