"""Cyber threats and sanctions screening."""

from __future__ import annotations

import asyncio
from collections import Counter
from datetime import date, timedelta
from typing import Optional

from app.settings import settings
from osint import geo
from osint.core import UNTRUSTED_NOTE, Result, safe_fetch, unavailable
from osint.registry import osint_tool
from osint.sources import security


@osint_tool(group="cyber", tier=1)
async def get_cyber_threats(country: Optional[str] = None, days: int = 7) -> str:
    """Current cyber threat picture: vulnerabilities newly confirmed as exploited in the wild (CISA KEV), live
    botnet command-and-control servers (Feodo Tracker), recent ransomware victims by country and group, and
    (when configured) fresh malware URLs and indicators of compromise from URLhaus and ThreatFox.

    Args:
        country: Optional country name or ISO code to filter C2 servers and ransomware victims.
        days: Look-back for KEV additions and ransomware victims (1-30, default 7).
    """
    c = geo.country(country) if country else None
    if country and not c:
        return unavailable("get_cyber_threats", f"Unknown country {country!r}")
    days = max(1, min(int(days), 30))
    r = Result("get_cyber_threats")
    tasks = [safe_fetch(r, "CISA Known Exploited Vulnerabilities", security.CISA_KEV_URL, security.cisa_kev()),
             safe_fetch(r, "abuse.ch Feodo Tracker", security.FEODO_URL, security.feodo_c2()),
             safe_fetch(r, "ransomware.live", security.RANSOMWARE_URL, security.ransomware_victims())]
    if settings.ABUSECH_AUTH_KEY:
        tasks += [safe_fetch(r, "abuse.ch URLhaus", security.URLHAUS_URL, security.urlhaus_recent()),
                  safe_fetch(r, "abuse.ch ThreatFox", security.THREATFOX_URL, security.threatfox_iocs(1))]
    res = await asyncio.gather(*tasks)
    kev, feodo, ransom = res[0] or [], res[1] or [], res[2] or []
    since = (date.today() - timedelta(days=days)).isoformat()
    new_kev = [k for k in kev if (k.get("date_added") or "") >= since]
    c2 = [x for x in feodo if x.get("status") == "online"]
    victims = [v for v in ransom if (v.get("discovered") or v.get("attack_date") or "")[:10] >= since]
    if c:
        c2 = [x for x in c2 if (x.get("country") or "").upper() == c["iso2"]]
        victims = [v for v in victims if (v.get("country") or "").upper() == c["iso2"]]
    data = {
        "exploited_vulnerabilities_added": {"count": len(new_kev), "items": new_kev[:25]},
        "botnet_c2_online": {"count": len(c2), "by_malware": dict(Counter(x.get("malware") for x in c2).most_common(10)),
                             "by_country": dict(Counter(x.get("country") for x in c2).most_common(10)), "items": c2[:25]},
        "ransomware_victims": {"count": len(victims), "by_group": dict(Counter(v.get("group") for v in victims).most_common(10)),
                               "by_country": dict(Counter(v.get("country") for v in victims).most_common(10)),
                               "items": victims[:25]},
    }
    if settings.ABUSECH_AUTH_KEY:
        urls, iocs = res[3] or [], res[4] or []
        data["malware_urls"] = {"online": sum(1 for u in urls if u.get("status") == "online"),
                                "by_threat": dict(Counter(u.get("threat") for u in urls).most_common(8)), "items": urls[:15]}
        data["iocs_24h"] = {"count": len(iocs), "by_malware": dict(Counter(i.get("malware") for i in iocs).most_common(10)),
                            "items": iocs[:20]}
    else:
        r.notes.append("URLhaus/ThreatFox are off (ABUSECH_AUTH_KEY not configured).")
    r.data = {"country": c["name"] if c else None, "days": days, **data}
    r.notes.append(UNTRUSTED_NOTE)
    return r.to_json()


@osint_tool(group="cyber", tier=1)
async def get_sanctions_data(name: str, list_name: Optional[str] = None, limit: int = 20) -> str:
    """Screen a person, company, vessel or aircraft name against the US OFAC SDN list (with aliases) and the UN
    Security Council consolidated list. Returns matches with list, programs, type and a match score.

    Args:
        name: The name to screen, e.g. "Mahan Air", "IRGC", a vessel name.
        list_name: Optional "ofac" or "un" to search one list only.
        limit: Maximum matches (default 20).
    """
    if not name or len(name.strip()) < 3:
        return unavailable("get_sanctions_data", "Give a name of at least 3 characters")
    r = Result("get_sanctions_data")
    want = (list_name or "").lower()
    tasks = []
    if want in ("", "ofac"):
        tasks.append(safe_fetch(r, "OFAC SDN list", security.OFAC_SDN_URL, security.ofac_sdn()))
    if want in ("", "un"):
        tasks.append(safe_fetch(r, "UN Security Council Consolidated List", security.UN_SANCTIONS_URL, security.un_consolidated()))
    lists = await asyncio.gather(*tasks)
    records = [rec for lst in lists if lst for rec in lst]
    matches = security.search_sanctions(records, name, max(1, min(limit, 50)))
    r.data = {"query": name, "records_searched": len(records), "matches": matches}
    r.notes.append("Screening is name matching only: confirm identity with dates of birth, IDs or IMO numbers "
                   "before acting on a match. The first OFAC download can take up to a minute.")
    return r.to_json()
