# Docs theme

`theme/` holds the Grow Codes branding for MkDocs Material. It is the `custom_dir` of this site
and is mirrored into the template as `docs/.overrides/`, the `custom_dir` of every generated
repository's `mkdocs.yml` (hidden from the pages, synced by `sdk-kit sync`).

| File | What |
| - | - |
| `main.html` | extends Material's `base.html`; inlines `grow.css` and sets the theme colour |
| `grow.css` | green accent `#2ea44f` for light and dark schemes, tab and table styling, footer |
| `partials/copyright.html` | footer: "Made by [Grow Codes](https://grow.codes)" + the site copyright |
| `.icons/grow/logo.svg` | the logo mark (`theme.icon.logo: grow/logo`) |
| `assets/favicon.svg` | favicon |

After changing a file in `theme/`, update the mirror (CI fails while it differs):

```sh
.github/scripts/sync-theme.sh          # copy theme/ → template/common/docs/.overrides/
.github/scripts/sync-theme.sh --check  # what CI runs
```

!!! note "MkDocs Material lifecycle"
    Material for MkDocs announced end of life on 2027-05-05 (fixes until then) with Zensical as
    successor, which reads existing `mkdocs.yml` files. The theme only uses documented override
    blocks, so a later move stays small.
