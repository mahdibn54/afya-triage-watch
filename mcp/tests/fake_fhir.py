"""In-memory FHIR store implementing the subset of behaviour afya-mcp relies on."""
from __future__ import annotations

import copy
import itertools
from typing import Any

from afya_mcp.fhir import FhirNotFound, FhirUnavailable


class FakeFhir:
    def __init__(self) -> None:
        self.data: dict[str, dict[str, dict[str, Any]]] = {}
        self._ids = itertools.count(100)
        self.down = False
        self.creates = 0

    def _check(self) -> None:
        if self.down:
            raise FhirUnavailable("fake FHIR is down")

    def put(self, resource: dict[str, Any]) -> dict[str, Any]:
        self.data.setdefault(resource["resourceType"], {})[resource["id"]] = copy.deepcopy(resource)
        return resource

    def read(self, rtype: str, rid: str) -> dict[str, Any]:
        self._check()
        try:
            return copy.deepcopy(self.data[rtype][rid])
        except KeyError:
            raise FhirNotFound(f"GET {rtype}/{rid}: HTTP 404") from None

    def search(self, rtype: str, params: dict[str, str]) -> list[dict[str, Any]]:
        self._check()
        out = list(self.data.get(rtype, {}).values())
        if "encounter" in params:
            out = [r for r in out if r.get("encounter", {}).get("reference") == params["encounter"]]
        if "subject" in params:
            out = [r for r in out if r.get("subject", {}).get("reference") == params["subject"]]
        if "identifier" in params:
            system, value = params["identifier"].split("|", 1)
            out = [r for r in out if any(i.get("system") == system and i.get("value") == value
                                         for i in r.get("identifier", []))]
        if "status" in params:
            out = [r for r in out if r.get("status") in params["status"].split(",")]
        if params.get("_sort") == "-date":
            out.sort(key=lambda r: r.get("effectiveDateTime", ""), reverse=True)
        return copy.deepcopy(out[: int(params.get("_count", "100"))])

    def conditional_create(self, resource: dict[str, Any], identifier: str) -> dict[str, Any]:
        self._check()
        system, value = identifier.split("|", 1)
        for existing in self.data.get(resource["resourceType"], {}).values():
            if any(i.get("system") == system and i.get("value") == value for i in existing.get("identifier", [])):
                return copy.deepcopy(existing)
        self.creates += 1
        new = copy.deepcopy(resource)
        new["id"] = str(next(self._ids))
        return self.put(new)

    def update(self, resource: dict[str, Any]) -> dict[str, Any]:
        self._check()
        return self.put(resource)
