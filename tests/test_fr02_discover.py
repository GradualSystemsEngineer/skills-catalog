"""FR-02 / UC-02: discover skills by described need; nothing matching is an explicit empty result."""

import pytest
from conftest import ALL_SKILLS

from skills_catalog import client


@pytest.fixture
def catalog(cfg):
    for folder in ALL_SKILLS:
        client.publish(cfg, folder, author="teammate")
    return cfg


def names(result):
    return [m["name"] for m in result["matches"]]


def test_release_notes_finds_release_note_draft_with_description(catalog):
    result = client.discover(catalog, "release notes")
    top = result["matches"][0]
    assert top["name"] == "release-note-draft"
    assert top["description"].startswith("Drafts release notes and changelog entries")
    assert top["version"] == 1


# Keyword queries the way an assistant sends them, none copied from the skill's description.
@pytest.mark.parametrize(
    "query, expected",
    [
        ("changelog for a new version", "release-note-draft"),
        ("summarize what shipped", "release-note-draft"),
        ("outage writeup root cause", "incident-postmortem"),
        ("database schema change safety", "sql-migration-review"),
        ("explain my pull request to reviewers", "pr-description"),
    ],
)
def test_paraphrased_requests_find_the_expected_skill(catalog, query, expected):
    assert expected in names(client.discover(catalog, query))[:3]


def test_unrelated_query_returns_explicit_empty_result(catalog):
    result = client.discover(catalog, "kubernetes autoscaling")
    assert result["matches"] == []
    assert result["catalog_size"] == len(ALL_SKILLS)
    assert result["message"] == f"No skills match 'kubernetes autoscaling' (searched {len(ALL_SKILLS)} skills)."


def test_punctuation_and_search_syntax_in_queries_are_harmless(catalog):
    assert "release-note-draft" in names(client.discover(catalog, 'release AND "notes* OR (NEAR'))
    assert client.discover(catalog, "!!! ???")["matches"] == []


def test_no_query_lists_every_skill(catalog):
    result = client.discover(catalog, None)
    assert sorted(names(result)) == names(result)
    assert len(result["matches"]) == len(ALL_SKILLS)


def test_terms_removed_in_v2_stop_matching(cfg, make_skill):
    client.publish(cfg, make_skill(body="Mention zanzibar here.\n"))
    assert names(client.discover(cfg, "zanzibar")) == ["demo-skill"]
    client.publish(cfg, make_skill(body="No longer mentioned.\n"))
    assert client.discover(cfg, "zanzibar")["matches"] == []
