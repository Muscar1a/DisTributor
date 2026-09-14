## 📝 Description
Provide a brief summary of the changes introduced by this Pull Request. What problem does it solve and how?

## 🔗 Related Issue
Linked Issue: Closes #__ (or Fixes `[FR-xx]` / Implements `[US-xx]`)

## 🛠️ Type of Change
Select all that apply:
- [ ] `feat` (New feature / Functional Requirement)
- [ ] `fix` (Bug fix)
- [ ] `docs` (Documentation updates)
- [ ] `infra` (Docker, CI/CD, database migration, VPS)
- [ ] `refactor` (Code style, cleanup, performance improvement)
- [ ] `interface-change` (Modifies `05_interfaces.md` contracts - **Requires approval from all team members**)

## 🧪 How Has This Been Tested?
Please describe the tests that you ran to verify your changes. Provide instructions so we can reproduce.

### Automated Tests
- Run command: `pytest tests/`
- Output/Result:
  ```
  # Paste test outputs if relevant
  ```

### Manual Verification
- Describe how to manually verify the change (e.g. curl commands, UI playground interactions, etc.)

## Checklist
Before requesting review, make sure:
- [ ] I have run `ruff check .` and resolved all lint issues.
- [ ] I have run `pytest` and all tests passed.
- [ ] My changes do not break existing interfaces in `05_interfaces.md`. (If they do, a separate contract PR must be merged first).
- [ ] I have updated the documentation (`docs/` or `README.md`) accordingly.
- [ ] I have updated `AI_LOG.md` to document the AI tools used for this task (if applicable).
