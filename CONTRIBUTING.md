# Contribution Workflow

This repository follows a branch and pull request model.

## Branch strategy
- main: stable integration branch
- feature/<name>: feature development branch
- fix/<name>: bug fix branch

## Recommended collaboration flow
1. Create a branch from main.
2. Commit small logical changes with clear messages.
3. Push branch to GitHub.
4. Open Pull Request to main.
5. Ensure CI passes before merge.

## Useful commands
1. Create a feature branch
- git checkout -b feature/my-change

2. Push branch
- git push -u origin feature/my-change

3. Update branch with latest main
- git checkout main
- git pull
- git checkout feature/my-change
- git rebase main

4. Merge after PR approval
- Use GitHub Pull Request merge UI
