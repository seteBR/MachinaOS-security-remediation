"""Apify credential (Wave 11.E.1 — per-domain).

The crawlee_scraper plugin in this folder may also add its own Credential
subclasses here in future.
"""

from __future__ import annotations

from services.plugin.credential import ApiKeyCredential, ProbeResult


class ApifyCredential(ApiKeyCredential):
    id = "apify"
    display_name = "Apify"
    category = "Scrapers"
    key_name = "Authorization"
    key_location = "bearer"
    docs_url = "https://docs.apify.com/api/v2"

    @classmethod
    async def _probe(cls, api_key: str) -> ProbeResult:
        """Probe Apify ``/users/me`` to verify the token + capture
        username / email / plan for display in the credentials panel.

        ``validate_apify_token`` lives on the plugin module
        (``apify_actor.py``) and uses the official ``apify_client`` SDK.
        It returns a dict; we translate to :class:`ProbeResult` so the
        base ``Credential.validate`` handles storage / broadcast.
        """
        from .apify_actor import validate_apify_token

        result = await validate_apify_token(api_key)
        if not result.get("valid"):
            return ProbeResult(
                valid=False,
                message=result.get("error", "Invalid API token"),
            )
        return ProbeResult(
            valid=True,
            message=f"Apify token validated — user: {result.get('username', 'unknown')}",
            extra={
                "username": result.get("username"),
                "email": result.get("email"),
                "plan": result.get("plan"),
            },
        )
