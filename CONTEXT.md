# RALPH

RALPH is a local operator CLI for running ticket work in isolated worktrees while keeping human judgment and repository ownership outside the tool.

## Language

**Git global excludes**:
The user-level Git ignore file that applies across repositories for one operator. Ralph may add its agent files directory pattern there so product repositories do not need Ralph-specific ignore entries.
_Avoid_: Global gitignore, global git config ignore

**Agent files directory**:
The operator-configured directory inside a ticket worktree where Ralph writes local agent context and review request files.
_Avoid_: Agent folder, Ralph scratch directory
