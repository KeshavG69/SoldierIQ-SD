"""Cyber threat feeds and sanctions lists."""

from __future__ import annotations

import csv
import difflib
import io
import re
import xml.etree.ElementTree as ET

from app.settings import settings
from osint.core import SourceError, cached, get_json, get_text, http

CISA_KEV_URL = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
FEODO_URL = "https://feodotracker.abuse.ch/downloads/ipblocklist.json"
RANSOMWARE_URL = "https://api.ransomware.live/v2/recentvictims"
URLHAUS_URL = "https://urlhaus-api.abuse.ch/v1/urls/recent/limit/200/"
THREATFOX_URL = "https://threatfox-api.abuse.ch/api/v1/"
OFAC_SDN_URL = "https://www.treasury.gov/ofac/downloads/sdn.csv"
OFAC_ALT_URL = "https://www.treasury.gov/ofac/downloads/alt.csv"
UN_SANCTIONS_URL = "https://scsanctions.un.org/resources/xml/en/consolidated.xml"


async def cisa_kev() -> tuple[list[dict], str]:
    async def fetch():
        data = await get_json(CISA_KEV_URL, timeout=40)
        vulns = data.get("vulnerabilities") or []
        vulns.sort(key=lambda v: v.get("dateAdded") or "", reverse=True)
        return [{
            "cve": v.get("cveID"), "vendor": v.get("vendorProject"), "product": v.get("product"),
            "name": v.get("vulnerabilityName"), "date_added": v.get("dateAdded"), "due_date": v.get("dueDate"),
            "ransomware_use": v.get("knownRansomwareCampaignUse"),
        } for v in vulns[:300]]

    return await cached("cyber:kev", 6 * 3600, fetch)


async def feodo_c2() -> tuple[list[dict], str]:
    async def fetch():
        data = await get_json(FEODO_URL, timeout=40)
        return [{
            "ip": d.get("ip_address"), "port": d.get("port"), "status": d.get("status"), "malware": d.get("malware"),
            "asn": d.get("as_number"), "as_name": d.get("as_name"), "country": d.get("country"),
            "first_seen": d.get("first_seen"), "last_online": d.get("last_online"),
        } for d in data or []]

    return await cached("cyber:feodo", 2 * 3600, fetch)


async def ransomware_victims() -> tuple[list[dict], str]:
    async def fetch():
        data = await get_json(RANSOMWARE_URL, timeout=40)
        return [{
            "victim": d.get("victim"), "group": d.get("group"), "country": d.get("country"),
            "sector": d.get("activity"), "attack_date": d.get("attackdate"), "discovered": d.get("discovered"),
            "domain": d.get("domain") or None, "url": d.get("url"),
        } for d in data or []]

    return await cached("cyber:ransomware", 3600, fetch)


async def urlhaus_recent() -> tuple[list[dict], str]:
    if not settings.ABUSECH_AUTH_KEY:
        raise SourceError("ABUSECH_AUTH_KEY not configured")

    async def fetch():
        resp = await http().get(URLHAUS_URL, headers={"Auth-Key": settings.ABUSECH_AUTH_KEY}, timeout=40)
        if resp.status_code >= 400:
            raise SourceError(f"URLhaus returned HTTP {resp.status_code}")
        return [{
            "url": u.get("url"), "status": u.get("url_status"), "threat": u.get("threat"),
            "tags": u.get("tags"), "date_added": u.get("date_added"), "host": u.get("host"),
        } for u in (resp.json().get("urls") or [])]

    return await cached("cyber:urlhaus", 1800, fetch)


async def threatfox_iocs(days: int = 1) -> tuple[list[dict], str]:
    if not settings.ABUSECH_AUTH_KEY:
        raise SourceError("ABUSECH_AUTH_KEY not configured")

    async def fetch():
        resp = await http().post(THREATFOX_URL, json={"query": "get_iocs", "days": max(1, min(days, 7))},
                                 headers={"Auth-Key": settings.ABUSECH_AUTH_KEY}, timeout=40)
        if resp.status_code >= 400:
            raise SourceError(f"ThreatFox returned HTTP {resp.status_code}")
        return [{
            "ioc": i.get("ioc"), "type": i.get("ioc_type"), "threat": i.get("threat_type"),
            "malware": i.get("malware_printable"), "confidence": i.get("confidence_level"),
            "first_seen": i.get("first_seen"), "tags": i.get("tags"),
        } for i in (resp.json().get("data") or [])[:500]]

    return await cached(f"cyber:threatfox:{days}", 1800, fetch)


# ── Sanctions ───────────────────────────────────────────────────────────────

async def ofac_sdn() -> tuple[list[dict], str]:
    """OFAC Specially Designated Nationals list, with aliases (cached 24h)."""

    async def fetch():
        sdn_text = await get_text(OFAC_SDN_URL, timeout=120)
        try:
            alt_text = await get_text(OFAC_ALT_URL, timeout=120)
        except SourceError:
            alt_text = ""
        aliases: dict[str, list[str]] = {}
        for row in csv.reader(io.StringIO(alt_text)):
            if len(row) >= 4:
                aliases.setdefault(row[0], []).append(row[3].strip())
        out = []
        for row in csv.reader(io.StringIO(sdn_text)):
            if len(row) < 12 or not row[0].strip().isdigit():
                continue
            nul = lambda v: None if v.strip() in ("-0-", "") else v.strip()  # noqa: E731
            out.append({
                "list": "OFAC SDN", "id": row[0], "name": row[1].strip(), "type": nul(row[2]) or "entity",
                "programs": nul(row[3]), "title": nul(row[4]), "vessel_type": nul(row[6]), "vessel_flag": nul(row[9]),
                "remarks": (nul(row[11]) or "")[:300] or None, "aliases": aliases.get(row[0], [])[:10],
            })
        if len(out) < 1000:
            raise SourceError("OFAC SDN list looked incomplete")
        return out

    return await cached("sanctions:ofac_sdn", 24 * 3600, fetch)


async def un_consolidated() -> tuple[list[dict], str]:
    """UN Security Council consolidated sanctions list (cached 24h)."""

    async def fetch():
        text = await get_text(UN_SANCTIONS_URL, timeout=120)
        root = ET.fromstring(text.encode("utf-8"))
        out = []
        for kind, tag in (("individual", "INDIVIDUAL"), ("entity", "ENTITY")):
            for el in root.iter(tag):
                g = lambda t: (el.findtext(t) or "").strip()  # noqa: E731
                name = " ".join(x for x in (g("FIRST_NAME"), g("SECOND_NAME"), g("THIRD_NAME"), g("FOURTH_NAME")) if x)
                aliases = [a.findtext("ALIAS_NAME") for a in el.iter(f"{tag}_ALIAS") if a.findtext("ALIAS_NAME")]
                out.append({
                    "list": "UN Consolidated", "id": g("REFERENCE_NUMBER"), "name": name, "type": kind,
                    "programs": g("UN_LIST_TYPE"), "listed_on": g("LISTED_ON"),
                    "remarks": g("COMMENTS1")[:300] or None, "aliases": [a.strip() for a in aliases][:10],
                })
        return out

    return await cached("sanctions:un", 24 * 3600, fetch)


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", s.lower()).strip()


def search_sanctions(records: list[dict], query: str, limit: int = 20) -> list[dict]:
    """Substring match first, then fuzzy match on names and aliases."""
    q = _norm(query)
    if not q:
        return []
    scored = []
    for r in records:
        names = [r["name"], *r.get("aliases", [])]
        best = 0.0
        for n in names:
            nn = _norm(n or "")
            if not nn:
                continue
            if q == nn:
                best = 1.0
                break
            if q in nn or all(tok in nn.split() for tok in q.split()):
                best = max(best, 0.9)
            else:
                best = max(best, difflib.SequenceMatcher(None, q, nn).ratio())
        if best >= 0.82:
            scored.append((best, r))
    scored.sort(key=lambda x: -x[0])
    return [{**r, "match_score": round(s, 2)} for s, r in scored[:limit]]
