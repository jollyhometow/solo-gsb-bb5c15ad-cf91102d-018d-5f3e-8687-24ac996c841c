"""Unit tests for the Markdown analyzer."""
from app.analyzer import analyze, normalize_submitted_path, slugify

import pytest


def by_type(diags, type_):
    return [d for d in diags if d.type == type_]


class TestSlugify:
    def test_basic(self):
        assert slugify("Hello, World!") == "hello-world"

    def test_cjk_kept(self):
        assert slugify("功能 介绍") == "功能-介绍"

    def test_underscore_and_digits_kept(self):
        assert slugify("foo_bar v2") == "foo_bar-v2"

    def test_punctuation_dropped(self):
        assert slugify("What's new?") == "whats-new"


class TestNormalizePath:
    def test_strips_dot_and_backslashes(self):
        assert normalize_submitted_path("./docs\\a.md") == "docs/a.md"

    def test_rejects_absolute(self):
        with pytest.raises(ValueError):
            normalize_submitted_path("/etc/passwd")

    def test_rejects_traversal(self):
        with pytest.raises(ValueError):
            normalize_submitted_path("../secret.md")


class TestAnchors:
    def test_duplicate_anchor_reported_with_first_line(self):
        diags = analyze({"a.md": "# Intro\n\n## Intro\n"})
        dups = by_type(diags, "duplicate_anchor")
        assert len(dups) == 1
        assert dups[0].source_file == "a.md"
        assert dups[0].line == 3
        assert dups[0].link == "#intro"
        assert "line 1" in dups[0].message

    def test_fragment_only_link_ok(self):
        diags = analyze({"a.md": "# Intro\n\nSee [top](#intro).\n"})
        assert diags == []

    def test_missing_anchor_same_file(self):
        diags = analyze({"a.md": "# Intro\n\nSee [nope](#nope).\n"})
        miss = by_type(diags, "missing_anchor")
        assert len(miss) == 1
        assert miss[0].line == 3
        assert miss[0].link == "#nope"
        assert miss[0].target_file == "a.md"

    def test_heading_inside_code_fence_ignored(self):
        content = "```\n# Not A Heading\n```\n\n# Real\n"
        diags = analyze({"a.md": content, "b.md": "[x](a.md#real)\n"})
        assert diags == []

    def test_link_inside_code_ignored(self):
        content = "# T\n\n`[x](missing.md)` and\n\n```\n[y](also-missing.md)\n```\n"
        assert analyze({"a.md": content}) == []


class TestCrossFileLinks:
    FILES = {
        "README.md": "# Home\n\nSee [guide](docs/guide.md#install) and [api](docs/api.md#nope).\n",
        "docs/guide.md": "# Guide\n\n## Install\n\nBack to [home](../README.md#home).\n",
        "docs/api.md": "# API\n",
    }

    def test_valid_links_produce_no_diagnostics(self):
        files = {k: v for k, v in self.FILES.items() if k != "docs/api.md"}
        files["README.md"] = "# Home\n\nSee [guide](docs/guide.md#install).\n"
        assert analyze(files) == []

    def test_missing_anchor_cross_file(self):
        miss = by_type(analyze(self.FILES), "missing_anchor")
        assert len(miss) == 1
        assert miss[0].source_file == "README.md"
        assert miss[0].line == 3
        assert miss[0].link == "docs/api.md#nope"
        assert miss[0].target_file == "docs/api.md"

    def test_missing_file(self):
        diags = analyze({"a.md": "[gone](sub/dir/nope.md)\n"})
        miss = by_type(diags, "missing_file")
        assert len(miss) == 1
        assert miss[0].target_file == "sub/dir/nope.md"

    def test_path_normalization(self):
        files = {
            "docs/a.md": "[b](../docs/./b.md)\n",
            "docs/b.md": "# B\n",
        }
        assert analyze(files) == []

    def test_percent_encoded_path_and_fragment(self):
        files = {
            "a.md": "[x](my%20docs/b%20file.md#hello-world)\n",
            "my docs/b file.md": "# Hello World\n",
        }
        assert analyze(files) == []

    def test_external_links_ignored(self):
        content = "[site](https://example.com/x#y) [mail](mailto:a@b.c) [ftp](ftp://h/f)\n"
        assert analyze({"a.md": content}) == []


class TestTraversalAndSelfReference:
    def test_path_out_of_root(self):
        diags = analyze({"docs/a.md": "[esc](../../etc/passwd.md)\n"})
        out = by_type(diags, "path_out_of_root")
        assert len(out) == 1
        assert out[0].source_file == "docs/a.md"
        assert out[0].line == 1
        assert out[0].link == "../../etc/passwd.md"
        assert out[0].target_file is None

    def test_root_relative_absolute_link_resolves_inside_root(self):
        files = {"a.md": "[b](/docs/b.md)\n", "docs/b.md": "# B\n"}
        assert analyze(files) == []

    def test_self_reference_flagged(self):
        diags = analyze({"docs/a.md": "# A\n\n[me](../docs/a.md#anchor)\n"})
        selfrefs = by_type(diags, "self_reference")
        assert len(selfrefs) == 1
        assert selfrefs[0].line == 3
        assert selfrefs[0].link == "../docs/a.md#anchor"
        assert selfrefs[0].target_file == "docs/a.md"

    def test_fragment_only_is_not_self_reference(self):
        diags = analyze({"a.md": "# A\n\n[toc](#a)\n"})
        assert diags == []


class TestDiagnosticsShape:
    def test_sorted_and_complete_fields(self):
        files = {
            "b.md": "[x](missing.md)\n",
            "a.md": "# Dup\n# Dup\n\n[y](gone.md)\n",
        }
        diags = analyze(files)
        assert [d.source_file for d in diags] == sorted(d.source_file for d in diags)
        for d in diags:
            assert d.line >= 1
            assert d.link
            assert d.message
