# Cross-Agent Compatibility Notes

This skill is packaged primarily as an Agent Skills-compatible directory, with lightweight adapters for Codex and Cursor.

## Agent Skills Open Standard

The Agent Skills specification defines a skill as a directory containing at minimum `SKILL.md`. `SKILL.md` must have YAML frontmatter followed by Markdown instructions. Required fields are `name` and `description`; optional fields include `license`, `compatibility`, `metadata`, and experimental `allowed-tools`.

Original documentation:

- https://agentskills.io/specification
- https://openagentskills.dev/docs/writing-skill-md

This package follows that structure:

```text
skills/tabular-file-understanding/SKILL.md
skills/tabular-file-understanding/scripts/profile_tabular_file.py
skills/tabular-file-understanding/references/*.md
```

## Claude Code / Claude Skills

Claude Skills use a `SKILL.md` file with YAML frontmatter and Markdown instructions. Skills may bundle `scripts/`, `references/`, and `assets/`. Claude's public docs emphasize progressive disclosure: frontmatter is used for discovery, `SKILL.md` is loaded when relevant, and resources are loaded only when needed.

Original documentation:

- https://code.claude.com/docs/en/skills.md
- https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview
- https://claude.com/docs/skills/how-to

This skill uses concise frontmatter, keeps the main instructions focused, and puts detailed schemas in `references/`.

## OpenClaw

OpenClaw documents AgentSkills-compatible skill folders with `SKILL.md` frontmatter and instructions. OpenClaw can load skills from workspace, project, personal, managed, bundled, and extra directories. Its docs note that OpenClaw follows the AgentSkills layout and that `{baseDir}` can be used in instructions where supported.

Original documentation:

- https://docs.openclaw.ai/tools/skills.md
- https://docs.openclaw.ai/tools/creating-skills

This skill avoids platform-specific required frontmatter and uses a simple metadata line for broad parser compatibility.

## OpenAI Codex

Codex uses `AGENTS.md` files for persistent project instructions. Codex documentation describes discovery from global and project scopes and notes that skills may live globally or in `.agents/skills` depending on Codex configuration.

Original documentation:

- https://developers.openai.com/codex/guides/agents-md
- https://developers.openai.com/codex/concepts/customization

This package includes a root `AGENTS.md` that points Codex-compatible agents to the bundled `SKILL.md` and Python script.

## Cursor

Cursor uses persistent rules in `.cursor/rules/`. Rules can be always applied, auto-attached by glob, agent-decided via description, or manually referenced. Cursor also supports `AGENTS.md` as a simpler project-level instruction file.

Original documentation:

- https://cursor.com/help/customization/rules

This package includes `.cursor/rules/tabular-file-understanding.mdc` as an agent-decided rule with relevant file globs.

## Portability Choices

- Python-only execution.
- Standard-library reference script.
- No automatic dependency installation.
- No platform-specific command-line tools.
- Canonical outputs in JSON and Markdown.
- Root `AGENTS.md` and Cursor rule adapters for agents that do not natively load `SKILL.md`.
