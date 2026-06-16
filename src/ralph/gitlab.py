"""GitLab merge request integration seam."""

from dataclasses import dataclass


@dataclass(frozen=True)
class MergeRequestDraft:
    title: str
    description: str
    source_branch: str
    target_project: str

