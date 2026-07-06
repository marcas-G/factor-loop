---
name: start-mr
description: Use when the user wants to create a merge request on GitLab
allowed-tools:
  - Bash
  - Read
  - Edit
  - Write
  - Skill
  - mcp__gitlab__*
---

# GitLab Merge Request Creator

Automate the full workflow: commit uncommitted changes → push → create or update MR with Conventional Commits format.

All GitLab API operations use MCP tools. Git local operations (branch, push) use Bash; commit operations are delegated to the available commit skill.

## Prerequisites

1. **GitLab Access**: Personal Access Token with `api` scope, configured per your platform's GitLab integration.
2. **Working directory**: Must be inside a git repository (`git rev-parse --is-inside-work-tree`)

## Skill Files

- `scripts/detect-project.sh` — Extract GitLab project path from git remote (execute via Bash)
- `templates/mr-description.md` — MR description template (read when generating description)

All file paths above are relative to the skill base directory.

## MCP Tools

The skill uses `mcp__gitlab__*` tools from `@ttpears/gitlab-mcp-server`:

| Action | MCP Tool |
|--------|----------|
| List/search MRs | `mcp__gitlab__get_merge_requests` |
| Create MR | `mcp__gitlab__create_merge_request` |
| Update MR | `mcp__gitlab__update_merge_request` |
| Get MR details | `mcp__gitlab__get_merge_request_context` |

## Step 1: Check Branch and Sync Remote

1. Detect the current branch via Bash: `git branch --show-current`

   - If on `main`, `master`, or `develop` (protected/base branches): ask the user for a feature name, then create and switch:
     ```bash
     git checkout -b feature/<name>
     ```
   - If already on a feature branch: reuse it.

2. Fetch remote via Bash: `git fetch origin`

3. Detect project path: Execute `bash <skill-base-dir>/scripts/detect-project.sh`

4. Detect target branch: `git remote show origin 2>/dev/null | grep 'HEAD branch' | awk '{print $NF}'`

5. Check merged MRs via MCP — use `mcp__gitlab__search_merge_requests` with `searchTerm: "author:me"`, `projectPath`, `state: "merged"`, filtering by source_branch:
   - If a merged MR exists for this branch → warn the user: "This branch already has a merged MR. Create a new branch? or continue with a new MR?" Wait for user decision before proceeding.

## Step 2: Comprehensive Change Audit

Before any commit or MR creation, perform a **complete audit of all local changes** relative to the remote target branch. Run these commands via Bash:

```bash
# 1. Commits not yet pushed to remote
git log origin/<target_branch>..HEAD --oneline

# 2. Staged but not committed
git diff --cached --stat

# 3. Unstaged modifications
git diff --stat

# 4. Untracked files
git ls-files --others --exclude-standard
```

**Aggregate all four categories into a complete change summary** and present it to the user:

```
📋 Complete Change Audit for MR:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
▸ Committed (not pushed): N commit(s)
  <list commits>
▸ Staged (not committed): N file(s)
  <list files with stats>
▸ Unstaged modifications: N file(s)
  <list files with stats>
▸ Untracked files: N file(s)
  <list files>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

**Critical rule**: The MR must include **ALL** local changes across all four categories. Never silently exclude any category.

Ask the user:
> "Above is the complete audit of all your local changes. Confirm: should ALL of these be included in this MR? (yes / no — if no, specify which to exclude)"

Wait for explicit user confirmation before proceeding.

## Step 3: Commit Changes

Stage all included changes:
```bash
git add -A
```

Check if this branch already has commits (updating existing MR) or is empty (new MR):
```bash
git log <target_branch>..HEAD --oneline
```

- **Has commits** → amend to keep MR as a single commit:
  ```bash
  git commit --amend --no-edit
  ```
- **No commits** → invoke the available commit skill to create the first commit

## Step 4: Check Existing MR and Generate Content

### 4.1 Detect target branch, project, and commits

1. Target branch and project path: already detected in Step 1
2. Commits: `git log <target_branch>..HEAD --oneline`

### 4.2 Check existing MR via MCP

Use `mcp__gitlab__search_merge_requests` with `searchTerm: "author:me"`, `projectPath`, `state: "opened"`, filtering by source_branch.

- Open MR exists → **update mode**
- No open MR → **create mode**

If the remote branch doesn't exist (deleted after merge), the first push will recreate it.

### 4.3 Generate MR content

**Has commits**: Get diff via `git diff <target_branch>...HEAD --stat` and `git diff <target_branch>...HEAD`.

**No commits (empty MR)**: Ask the user what they plan to develop.

**Title format**: `<type>(<scope>): <description>` (same format as commit-commands).

**Description format**: See [templates/mr-description.md](templates/mr-description.md).

**Never prefix the title with "Draft:".** Pass `draft: true` to the MCP tool — the MCP server handles draft status.

Show the generated title and description to the user for confirmation.

## Step 5: Push and Create/Update MR

### 5.1 Pre-Push Final Verification

Before pushing, run a final verification to confirm the complete set of changes that will be included in the MR:

```bash
git log <target_branch>..HEAD --oneline
git diff <target_branch>...HEAD --stat
```

Present the summary to the user:

```
🚀 About to push the following to origin/<current_branch>:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
▸ N commit(s) to push:
  <list commits>
▸ Files changed:
  <list files with stats>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

Ask for explicit confirmation: "Push these changes and create/update the MR? (yes/no)"

Wait for user confirmation before proceeding.

### 5.2 Push (Bash)

1. Sync with target branch: `git rebase origin/<target_branch>` (already fetched in Step 1)
   - If rebase has conflicts → abort: `git rebase --abort`, warn user, stop.
2. Check if remote feature branch exists: `git rev-parse --verify origin/<current_branch>`
3. Push:
   - Remote branch doesn't exist: `git push -u origin <current_branch>`
   - Remote branch exists: `git push --force-with-lease origin <current_branch>`
   - If push rejected (remote has new commits) → fetch + rebase again, then retry push

### 5.3 Create or Update MR (MCP)

- Default: `draft: true`
- If user explicitly said "ready" or `--ready`: `draft: false`

**Important**: `@ttpears/gitlab-mcp-server` requires explicit `userCredentials` for write operations (create/update). Read operations auto-detect token from environment config.

**Create mode**: `mcp__gitlab__create_merge_request`
- `projectPath`, `title`, `description`, `sourceBranch`, `targetBranch`, `draft`, `squash: true`
- **Required**: `userCredentials: { accessToken: "glpat-xxxxxx", gitlabUrl: "https://gitlab.xyz.abc" }`

**Update mode**: `mcp__gitlab__update_merge_request`
- `projectPath`, `iid`, `title`, `description`, `draft`
- **Required**: `userCredentials: { accessToken: "glpat-xxxxxx", gitlabUrl: "https://gitlab.xyz.abc" }`

### 5.4 Verify MR (MCP)

`mcp__gitlab__get_merge_request_context` with `projectPath` and `iid`.

Report: MR web URL, IID, title, draft status, squash status.
