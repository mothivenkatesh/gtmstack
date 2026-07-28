"""
CRM providers behind one protocol. HubSpot and Salesforce as peers.

The shape this replaces: `_crm.py` hardcoded HubSpot and carried
`"salesforce": False` as a placeholder. That is the same declared-but-not-built
pattern deleted from the agent roster, and it would have grown into an if-ladder
the moment a second provider arrived.

The protocol is the one already proven by the Signals source adapters: every
provider exposes the same four calls, normalises to the graph's ontology, and a
provider that is not configured degrades honestly instead of failing.

NORMALISATION IS THE ACTUAL WORK. HubSpot's `lifecyclestage` and Salesforce's
`Status`/`StageName` do not map cleanly, and if they land in different shapes
Steward cannot dedupe across them: you get two disconnected halves of a graph,
which is exactly the toolkit-versus-harness split this project just fixed. So
every provider returns the SAME dict keys, and the mapping tables live here in
the open rather than being buried in each fetcher.

Auth differs on purpose and the protocol absorbs it: HubSpot is a static bearer
token, Salesforce is OAuth2 with a per-org instance host and a refresh token.

No em dashes.
"""
from __future__ import annotations

import os

try:
    import requests
except ImportError:                                              # pragma: no cover
    requests = None

# One vocabulary both providers map into. Without this the graph holds
# "customer" from one CRM and "Closed Won" from the other and nothing can
# reason across them.
LIFECYCLE = {
    # HubSpot
    "subscriber": "subscriber", "lead": "lead", "marketingqualifiedlead": "mql",
    "salesqualifiedlead": "sql", "opportunity": "opportunity",
    "customer": "customer", "evangelist": "advocate", "other": "other",
    # Salesforce
    "open - not contacted": "lead", "working - contacted": "lead",
    "closed - converted": "customer", "closed - not converted": "disqualified",
    "qualified": "sql", "unqualified": "disqualified",
}


def _lifecycle(v):
    return LIFECYCLE.get((v or "").strip().lower(), (v or "").strip().lower() or None)


class Provider:
    """The contract. A provider that cannot answer returns an empty list rather
    than raising, so one broken CRM never takes a sync down."""

    id = ""
    name = ""

    def configured(self) -> bool:
        return False

    def contacts(self, limit=1000):
        return []

    def companies(self, limit=1000):
        return []

    def deals(self, limit=1000):
        return []

    def status(self):
        return {"id": self.id, "name": self.name, "configured": self.configured(),
                "note": self._note()}

    def _note(self):
        return "Connected." if self.configured() else f"{self.name} is not connected."


# ── HubSpot ─────────────────────────────────────────────────────────────────

class HubSpot(Provider):
    id, name = "hubspot", "HubSpot"
    BASE = "https://api.hubapi.com"

    def configured(self):
        return bool(os.getenv("HUBSPOT_TOKEN") and requests)

    def _note(self):
        return ("Connected." if self.configured()
                else "Set HUBSPOT_TOKEN (a private app token).")

    def _pages(self, path, props, limit):
        tok = os.getenv("HUBSPOT_TOKEN")
        after, got = None, 0
        while got < limit:
            params = {"limit": min(100, limit - got), "properties": ",".join(props)}
            if after:
                params["after"] = after
            r = requests.get(f"{self.BASE}{path}",
                             headers={"Authorization": f"Bearer {tok}"},
                             params=params, timeout=30)
            if r.status_code == 401:
                raise RuntimeError("HubSpot rejected the token")
            if r.status_code == 429:
                raise RuntimeError("HubSpot rate limit, try again shortly")
            r.raise_for_status()
            data = r.json()
            rows = data.get("results") or []
            for row in rows:
                yield row
                got += 1
            after = ((data.get("paging") or {}).get("next") or {}).get("after")
            if not after or not rows:
                return

    def contacts(self, limit=1000):
        if not self.configured():
            return []
        props = ("email", "firstname", "lastname", "phone", "company", "jobtitle",
                 "lifecyclestage", "hs_lead_status", "createdate")
        out = []
        for row in self._pages("/crm/v3/objects/contacts", props, limit):
            p = row.get("properties") or {}
            email = (p.get("email") or "").strip().lower()
            out.append({
                "crm": self.id, "crm_id": row.get("id"),
                "key": email or f"{self.id}:contact:{row.get('id')}",
                "email": email,
                "name": " ".join(x for x in (p.get("firstname"), p.get("lastname")) if x) or None,
                "phone": p.get("phone"), "company": p.get("company"),
                "title": p.get("jobtitle"),
                "lifecycle": _lifecycle(p.get("lifecyclestage")),
                "created_at": p.get("createdate"),
                "url": f"https://app.hubspot.com/contacts/0/contact/{row.get('id')}",
            })
        return out

    def companies(self, limit=1000):
        if not self.configured():
            return []
        props = ("name", "domain", "industry", "numberofemployees", "city",
                 "country", "lifecyclestage", "createdate")
        out = []
        for row in self._pages("/crm/v3/objects/companies", props, limit):
            p = row.get("properties") or {}
            dom = (p.get("domain") or "").strip().lower()
            out.append({
                "crm": self.id, "crm_id": row.get("id"),
                "key": dom or f"{self.id}:company:{row.get('id')}",
                "name": p.get("name"), "domain": dom, "industry": p.get("industry"),
                "employees": p.get("numberofemployees"), "city": p.get("city"),
                "country": p.get("country"),
                "lifecycle": _lifecycle(p.get("lifecyclestage")),
                "created_at": p.get("createdate"),
                "url": f"https://app.hubspot.com/contacts/0/company/{row.get('id')}",
            })
        return out

    def deals(self, limit=1000):
        if not self.configured():
            return []
        props = ("dealname", "amount", "dealstage", "pipeline", "closedate", "createdate")
        out = []
        for row in self._pages("/crm/v3/objects/deals", props, limit):
            p = row.get("properties") or {}
            out.append({
                "crm": self.id, "crm_id": row.get("id"),
                "key": f"{self.id}:deal:{row.get('id')}",
                "name": p.get("dealname"), "amount": p.get("amount"),
                "stage": p.get("dealstage"), "pipeline": p.get("pipeline"),
                "close_date": p.get("closedate"), "created_at": p.get("createdate"),
                "url": f"https://app.hubspot.com/contacts/0/deal/{row.get('id')}",
            })
        return out


# ── Salesforce ──────────────────────────────────────────────────────────────

class Salesforce(Provider):
    """OAuth2 with a per-org instance host, which is the real difference from
    HubSpot's static token. Reads go through SOQL rather than a REST object API,
    so the shape of the fetch differs while the OUTPUT does not."""

    id, name = "salesforce", "Salesforce"
    VERSION = "v60.0"

    def configured(self):
        return bool(os.getenv("SALESFORCE_INSTANCE_URL")
                    and (os.getenv("SALESFORCE_ACCESS_TOKEN")
                         or (os.getenv("SALESFORCE_REFRESH_TOKEN")
                             and os.getenv("SALESFORCE_CLIENT_ID")))
                    and requests)

    def _note(self):
        if self.configured():
            return "Connected."
        return ("Set SALESFORCE_INSTANCE_URL plus SALESFORCE_ACCESS_TOKEN, or a "
                "refresh token with SALESFORCE_CLIENT_ID and _CLIENT_SECRET.")

    def _token(self):
        """A live access token, refreshed when only a refresh token is held.
        Salesforce access tokens are short-lived, so a connector that only
        accepts a static token works for an hour and then looks broken."""
        tok = os.getenv("SALESFORCE_ACCESS_TOKEN")
        if tok:
            return tok
        rt, cid = os.getenv("SALESFORCE_REFRESH_TOKEN"), os.getenv("SALESFORCE_CLIENT_ID")
        cs = os.getenv("SALESFORCE_CLIENT_SECRET", "")
        if not (rt and cid):
            raise RuntimeError("Salesforce is not connected")
        r = requests.post(
            f"{os.getenv('SALESFORCE_LOGIN_URL', 'https://login.salesforce.com')}"
            "/services/oauth2/token",
            data={"grant_type": "refresh_token", "refresh_token": rt,
                  "client_id": cid, "client_secret": cs}, timeout=30)
        r.raise_for_status()
        return r.json().get("access_token")

    def _soql(self, query, limit):
        base = os.getenv("SALESFORCE_INSTANCE_URL", "").rstrip("/")
        tok = self._token()
        url = f"{base}/services/data/{self.VERSION}/query"
        params, got = {"q": f"{query} LIMIT {min(limit, 2000)}"}, 0
        while url and got < limit:
            r = requests.get(url, headers={"Authorization": f"Bearer {tok}"},
                             params=params, timeout=30)
            if r.status_code == 401:
                raise RuntimeError("Salesforce rejected the token")
            r.raise_for_status()
            d = r.json()
            for row in d.get("records") or []:
                yield row
                got += 1
            nxt = d.get("nextRecordsUrl")
            url, params = (f"{base}{nxt}" if nxt else None), None

    def contacts(self, limit=1000):
        if not self.configured():
            return []
        q = ("SELECT Id, Email, Name, Phone, Title, Account.Name, CreatedDate, "
             "LeadSource FROM Contact")
        out = []
        for row in self._soql(q, limit):
            email = (row.get("Email") or "").strip().lower()
            out.append({
                "crm": self.id, "crm_id": row.get("Id"),
                "key": email or f"{self.id}:contact:{row.get('Id')}",
                "email": email, "name": row.get("Name"), "phone": row.get("Phone"),
                "company": ((row.get("Account") or {}) or {}).get("Name"),
                "title": row.get("Title"), "lifecycle": _lifecycle(row.get("LeadSource")),
                "created_at": row.get("CreatedDate"),
                "url": f"{os.getenv('SALESFORCE_INSTANCE_URL','').rstrip('/')}"
                       f"/lightning/r/Contact/{row.get('Id')}/view",
            })
        return out

    def companies(self, limit=1000):
        if not self.configured():
            return []
        q = ("SELECT Id, Name, Website, Industry, NumberOfEmployees, "
             "BillingCity, BillingCountry, CreatedDate FROM Account")
        out = []
        for row in self._soql(q, limit):
            site = (row.get("Website") or "").strip().lower()
            dom = site.replace("https://", "").replace("http://", "").split("/")[0]
            dom = dom[4:] if dom.startswith("www.") else dom
            out.append({
                "crm": self.id, "crm_id": row.get("Id"),
                "key": dom or f"{self.id}:company:{row.get('Id')}",
                "name": row.get("Name"), "domain": dom,
                "industry": row.get("Industry"),
                "employees": row.get("NumberOfEmployees"),
                "city": row.get("BillingCity"), "country": row.get("BillingCountry"),
                "lifecycle": None, "created_at": row.get("CreatedDate"),
                "url": f"{os.getenv('SALESFORCE_INSTANCE_URL','').rstrip('/')}"
                       f"/lightning/r/Account/{row.get('Id')}/view",
            })
        return out

    def deals(self, limit=1000):
        if not self.configured():
            return []
        q = ("SELECT Id, Name, Amount, StageName, CloseDate, CreatedDate "
             "FROM Opportunity")
        out = []
        for row in self._soql(q, limit):
            out.append({
                "crm": self.id, "crm_id": row.get("Id"),
                "key": f"{self.id}:deal:{row.get('Id')}",
                "name": row.get("Name"), "amount": row.get("Amount"),
                "stage": row.get("StageName"), "pipeline": None,
                "close_date": row.get("CloseDate"), "created_at": row.get("CreatedDate"),
                "url": f"{os.getenv('SALESFORCE_INSTANCE_URL','').rstrip('/')}"
                       f"/lightning/r/Opportunity/{row.get('Id')}/view",
            })
        return out


PROVIDERS = {p.id: p for p in (HubSpot(), Salesforce())}


def configured():
    st = {pid: p.configured() for pid, p in PROVIDERS.items()}
    st["any"] = any(st.values())
    return st


def active():
    return [p for p in PROVIDERS.values() if p.configured()]


def status():
    return {"providers": [p.status() for p in PROVIDERS.values()],
            "any": bool(active())}
