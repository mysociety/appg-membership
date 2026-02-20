from __future__ import annotations

from collections.abc import Iterable, Sequence

from appg_membership.classify_appg_agent import classify_appg
from appg_membership.models import APPGList, Parliament

DEVOLVED_PARLIAMENTS: tuple[Parliament, ...] = (
    Parliament.SCOTLAND,
    Parliament.SENEDD_EN,
    Parliament.SENEDD_CY,
    Parliament.NI,
)


def _normalise_parliaments(
    parliaments: Sequence[Parliament] | None,
) -> tuple[Parliament, ...]:
    if parliaments:
        return tuple(parliaments)
    return DEVOLVED_PARLIAMENTS


def assign_categories(
    parliaments: Sequence[Parliament] | None = None,
    only_missing: bool = True,
    target_slugs: dict[Parliament, Iterable[str]] | None = None,
) -> int:
    """
    Assign LLM categories to APPGs/CPGs for selected parliaments.

    Args:
        parliaments: Which parliaments to process. Defaults to all devolved parliaments.
        only_missing: If True, only classify items with no categories.
        target_slugs: Optional per-parliament set/list of slugs to restrict processing.

    Returns:
        Number of groups successfully updated.
    """
    selected_parliaments = _normalise_parliaments(parliaments)
    updated_count = 0

    normalised_slugs: dict[Parliament, set[str]] = {}
    if target_slugs:
        for parliament, slugs in target_slugs.items():
            normalised_slugs[parliament] = set(slugs)

    for parliament in selected_parliaments:
        appgs = APPGList.load(parliament=parliament)
        requested_slugs = normalised_slugs.get(parliament)

        for appg in appgs:
            if requested_slugs is not None and appg.slug not in requested_slugs:
                continue
            if only_missing and appg.categories:
                continue

            try:
                updated = classify_appg(appg)
                updated.save()
                updated_count += 1
                print(f"Classified {parliament.value}: {updated.slug}")
            except Exception as exc:
                print(
                    f"Warning: failed to classify {parliament.value}/{appg.slug}: {exc}"
                )

    return updated_count


def assign_categories_for_new_groups(
    parliament: Parliament,
    previous_slugs: set[str],
    current_slugs: set[str],
) -> int:
    """
    Assign categories for newly created groups after a scraper run.
    """
    new_slugs = current_slugs - previous_slugs
    if not new_slugs:
        print(
            f"No new groups found for {parliament.value}; skipping category assignment"
        )
        return 0

    print(
        f"Found {len(new_slugs)} new groups for {parliament.value}; assigning categories"
    )
    return assign_categories(
        parliaments=[parliament],
        only_missing=True,
        target_slugs={parliament: new_slugs},
    )
