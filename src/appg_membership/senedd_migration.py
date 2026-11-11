from __future__ import annotations

import json
import re
import subprocess
from datetime import date
from pathlib import Path
from typing import NamedTuple
from urllib.parse import parse_qs, urlparse

from mysoc_validator import Popolo
from pydantic import HttpUrl

from .models import APPG, Parliament
from .senedd import (
    LIST_PAGE,
    SENEDD_EN_BASE,
    fetch_page,
    parse_current_cpg_list,
    save_appg,
)
from .senedd_lifecycle import (
    SIXTH_ARCHIVE,
    SeneddMembershipChecker,
    archive_group,
    bound_senedd_group,
)
from .senedd_models import SeneddRegistration


class MigrationResult(NamedTuple):
    """
    Counts of verified legacy records and recovered historical registrations.
    """

    sixth: int
    seventh: int
    unverified: int
    recovered: int


def body_id_from_group(group: APPG) -> str | None:
    """
    Read the source registration ID without using a name or a numeric ID threshold.
    """
    if not group.source_url:
        return None
    values = parse_qs(urlparse(str(group.source_url)).query).get("ID", [])
    return values[0] if len(values) == 1 and values[0].isdigit() else None


def archive_body_ids(html: str) -> set[str]:
    """
    Recognise the official Sixth Senedd archive and its registered source bodies.
    """
    if not re.search(r"Cross-Party Groups - Sixth Senedd", html, re.I):
        raise ValueError("Unrecognised Sixth Senedd archive")
    ids = set(re.findall(r"mgOutsideBodyDetails\.aspx\?ID=(\d+)", html, re.I))
    if not ids:
        raise ValueError("Sixth Senedd archive contains no registration evidence")
    return ids


def migrate_senedd_data(
    data_dir: Path,
    popolo: Popolo,
    archive_html: str,
    current_html: str,
    sixth_ref: str | None = None,
) -> MigrationResult:
    """
    Classify legacy records from official body IDs and recover overwritten history.

    An optional git revision supplies pre-election snapshots. Only registrations
    independently identified in the official Sixth Senedd archive are recovered.
    No observation or membership start date is invented for legacy snapshots.
    """
    sixth_ids = archive_body_ids(archive_html)
    seventh_ids = {entry.body_id for entry in parse_current_cpg_list(current_html)}
    if sixth_ids & seventh_ids:
        raise ValueError("Conflicting term evidence; migration has not changed data")
    checker = SeneddMembershipChecker(popolo)
    sixth = seventh = unverified = recovered = 0
    updates: list[APPG] = []
    archives: list[APPG] = []
    for parliament in (Parliament.SENEDD_EN, Parliament.SENEDD_CY):
        folder = data_dir / APPG._get_parliament_folder(parliament)
        for path in sorted(folder.glob("*.json")):
            group = APPG.model_validate_json(path.read_text(encoding="utf-8"))
            body_id = body_id_from_group(group)
            if group.senedd_registration is not None:
                continue
            if body_id in sixth_ids:
                term = 6
                evidence_url = SIXTH_ARCHIVE
                sixth += 1
            elif body_id in seventh_ids:
                term = 7
                evidence_url = SENEDD_EN_BASE + LIST_PAGE
                seventh += 1
            else:
                unverified += 1
                archives.append(group)
                continue
            group.senedd_registration = SeneddRegistration(
                body_id=body_id,
                term=term,
                verified=True,
                evidence_url=HttpUrl(evidence_url),
            )
            updates.append(bound_senedd_group(group, checker))

        if sixth_ref:
            repo_dir = Path(__file__).resolve().parents[2]
            tree_folder = f"data/{folder.name}"
            paths = subprocess.run(
                ["git", "ls-tree", "-r", "--name-only", sixth_ref, "--", tree_folder],
                cwd=repo_dir,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.splitlines()
            for name in paths:
                if not name.endswith(".json"):
                    continue
                content = subprocess.run(
                    ["git", "show", f"{sixth_ref}:{name}"],
                    cwd=repo_dir,
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout
                group = APPG.model_validate_json(content)
                body_id = body_id_from_group(group)
                if body_id not in sixth_ids:
                    continue
                group.senedd_registration = SeneddRegistration(
                    body_id=body_id,
                    term=6,
                    verified=True,
                    evidence_url=HttpUrl(SIXTH_ARCHIVE),
                )
                current_path = folder / Path(name).name
                if current_path.exists():
                    current = APPG.model_validate_json(current_path.read_text())
                    if body_id_from_group(current) == body_id:
                        continue
                archives.append(bound_senedd_group(group, checker))
                recovered += 1
    # Parse every source and optional git snapshot before changing saved data.
    for group in updates:
        save_appg(group, data_dir / APPG._get_parliament_folder(group.parliament))
    for group in archives:
        archive_group(group, data_dir)
    return MigrationResult(sixth, seventh, unverified, recovered)


def migrate_from_official_sources(
    data_dir: Path, sixth_ref: str | None = None
) -> MigrationResult:
    """
    Save reproducible term-classification evidence and migrate the existing files.
    """
    archive_html = fetch_page(
        SIXTH_ARCHIVE.replace("https://senedd.", "https://www.senedd.")
    )
    current_html = fetch_page(SENEDD_EN_BASE + LIST_PAGE)
    # Validate both before storing evidence or modifying records.
    sixth_ids = archive_body_ids(archive_html)
    current_entries = parse_current_cpg_list(current_html)
    evidence_dir = data_dir / "raw" / "senedd"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    evidence = {
        "checked_on": date.today().isoformat(),
        "sixth_archive_url": SIXTH_ARCHIVE,
        "sixth_body_ids": sorted(sixth_ids),
        "current_list_url": SENEDD_EN_BASE + LIST_PAGE,
        "seventh_body_ids": sorted(entry.body_id for entry in current_entries),
        "sixth_git_revision": sixth_ref,
    }
    (evidence_dir / "migration_evidence.json").write_text(
        json.dumps(evidence, indent=2) + "\n", encoding="utf-8"
    )
    return migrate_senedd_data(
        data_dir, Popolo.from_parlparse(), archive_html, current_html, sixth_ref
    )
