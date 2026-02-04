# nenabot-main
Repo for hosting Hardware Controls and Machine Vision code


# GitHub Workflow & Contribution Guidelines

This section outlines the standards for branching, committing, and managing Pull Requests within this repository.

---

## 1. Branch Naming Conventions
Always use a prefix that describes the intent of your work. Use **kebab-case** (all lowercase, hyphens as separators).

| Prefix | Purpose | Example |
| :--- | :--- | :--- |
| `feat/` | A new feature or enhancement | `feat/user-login` |
| `fix/` | A bug fix | `fix/broken-button` |
| `docs/` | Documentation changes | `docs/update-readme` |
| `refactor/` | Code changes that improve structure without changing behavior | `refactor/api-calls` |
| `chore/` | Maintenance, dependencies, or build tasks | `chore/update-deps` |

**Command:** `git checkout -b feat/your-branch-name`

---

## 2. Commit Message Standards
We follow the **Conventional Commits** format. This keeps the history clean and allows for automated changelogs.

**Format:** `<type>(optional-scope): <description>`

* **Type:** Use the prefixes mentioned above (feat, fix, docs, etc.).
* **Description:** Use the imperative, present tense (e.g., "add" instead of "added").
* **Case:** Start the description with a lowercase letter and do not end with a period.

**Examples:**
* `feat(ui): add toggle for dark mode`
* `fix(auth): resolve token expiration bug`
* `docs: clarify installation steps`

---

## 3. Pull Request (PR) Details

### PR Title
The title should be concise and follow the commit naming convention.
* **Good:** `feat: implement user dashboard`
* **Bad:** `Merge my code` or `Finished the task`

