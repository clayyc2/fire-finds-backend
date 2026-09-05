"""Non-purchasing supplier adapter, limited to explicitly owned quote carts."""
from __future__ import annotations

from urllib.parse import parse_qs, quote, urlsplit

from .randmar import RandmarClient, SupplierOrdersDisabled
from .randmar_readonly import ReadOnlyRandmarClient


class QuoteOnlyRandmarClient(ReadOnlyRandmarClient):
    def __init__(self, secrets_dir, reseller_id, *, cart_names):
        super().__init__(secrets_dir, reseller_id)
        if not cart_names or any(not isinstance(c, str) or not c.startswith("ff-quote-") or
                                 len(c) > 80 or not c.replace("-", "").isalnum() for c in cart_names):
            raise ValueError("Explicit owned ff-quote cart names required")
        self._quote_carts = frozenset(cart_names)

    def _request_json(self, method, url, **kwargs):
        base = self._reseller_path("").rstrip("/")
        parsed = urlsplit(url)
        for name in self._quote_carts:
            cart = quote(name, safe="")
            exact = url == base + "/Cart/" + cart
            shipping = url == base + "/Cart/ShippingMethods/" + cart
            prefix = base + "/Cart/AddItem/" + cart + "/"
            clean_url = url.split("?", 1)[0]
            suffix = clean_url[len(prefix):] if clean_url.startswith(prefix) else ""
            add = suffix.endswith("/DefaultOpportunity") and suffix.count("/") == 1
            query = parse_qs(parsed.query, keep_blank_values=True)
            quantity = query.get("quantity", [])
            if ((method in {"GET", "DELETE"} and exact and not parsed.query) or
                    (method == "POST" and shipping and not parsed.query) or
                    (method == "POST" and add and set(query) == {"quantity"} and len(quantity) == 1 and
                     quantity[0].isascii() and quantity[0].isdigit() and 1 <= int(quantity[0]) <= 100)):
                return RandmarClient._request_json(self, method, url, **kwargs)
        # Read-only superclass rejects ProcessNew, checkout, arbitrary cart
        # mutation, labels, or changes to another operator's cart.
        return super()._request_json(method, url, **kwargs)

    def process_cart(self, *args, **kwargs):
        raise SupplierOrdersDisabled("Quote-only adapter cannot purchase")
