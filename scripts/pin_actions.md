# Pinned GitHub Actions

Every third-party action in `.github/workflows` is pinned by full commit SHA, with the tag in a trailing
comment. Dependabot (`github-actions` ecosystem) proposes updates weekly; review the diff of the new tag
before merging.

To resolve a tag to its commit SHA (annotated tags need the `^{}` form):

```bash
git ls-remote https://github.com/<owner>/<repo> "refs/tags/<tag>^{}" "refs/tags/<tag>"
```

| Action | Tag | Commit SHA |
|---|---|---|
| `actions/checkout` | v7.0.1 | `3d3c42e5aac5ba805825da76410c181273ba90b1` |
| `astral-sh/setup-uv` | v10.3.3 | `68559e99cc807c1eb7e9238fd43a15bba460eec2` |
| `peter-evans/create-pull-request` | v8.1.3 | `3ffccacd46053766916f087ce41d627c0b8cf2d1` |
| `actions/upload-artifact` | v7.0.2 | `cf430e030ddbb5b0abf93d22962f4752f3646cd9` |
| `actions/download-artifact` | v8.0.2 | `9000827ccba6bdab643e8b6fd33ac0654aef8333` |
| `pypa/gh-action-pypi-publish` | v1.14.3 | `7245906fb61fa33a13554f9d5fb856fe61758086` |
| `actions/configure-pages` | v6.0.0 | `45bfe0192ca1faeb007ade9deae92b16b8254a0d` |
| `actions/upload-pages-artifact` | v5.0.0 | `fc324d3547104276b827a68afc52ff2a11cc49c9` |
| `actions/deploy-pages` | v5.0.1 | `368f82528645a54fb793d4d04e342629a3f51346` |

Resolved on 2026-11-10.
