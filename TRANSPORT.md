# Repository workflow

Clone the repository and create a branch before making changes:

```bash
git clone https://github.com/AminKhalif/nakama.git
cd nakama
git switch -c feature/description
```

Run the checks in [TESTING.md](TESTING.md), review `git diff`, and commit related
changes together. Keep private keys, credentials, databases, and logs outside
version control. Use your configured Git credential helper for remote access.
