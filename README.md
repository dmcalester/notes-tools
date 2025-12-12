# Notes Export

A spiritual successor to Markdown - write in Notes.app with minimal markup, export to clean HTML.

Export notes from Apple Notes to static HTML blog posts with support for:
- Wiki-style `[[links]]` between notes
- Footnotes with `[^1]` syntax
- Automatic paragraph wrapping
- RSS feed generation
- Date-based URL slugs (`YYYY/MM/title-slug`)

## Requirements

- macOS (uses Notes.app via osascript)
- Python 3 (built-in on macOS)

## Quick Start

```bash
# Basic usage (uses config.json in current/script directory)
./export.py

# Specify different folder
./export.py --folder "Blog Posts"

# Override output location
./export.py --output ./public

# Override all settings
./export.py --folder "Posts" --output ./dist --site-url https://myblog.com
```

## Configuration

Create a `config.json` file:

```json
{
  "notesFolderName": "test",
  "templateDirectory": "./templates",
  "outputDirectory": "./output",
  "siteTitle": "My Blog",
  "siteUrl": "https://example.com",
  "siteDescription": "Notes from the field"
}
```

Config file is searched in:
1. Path specified with `--config` flag
2. Script directory (`./config.json`)
3. Current working directory (`./config.json`)

CLI flags override config file settings.

## CLI Options

```
--config CONFIG               Path to config.json file
--folder FOLDER              Notes folder name
--templates TEMPLATES        Template directory path
--output OUTPUT              Output directory path
--site-url SITE_URL          Site URL for RSS feed
--site-title SITE_TITLE      Site title for RSS feed
--site-description DESC      Site description for RSS feed
```

## Templates

Templates use simple `{{variable}}` substitution:

### article.html
Full article page template.

Variables: `{{title}}`, `{{slug}}`, `{{datetime}}`, `{{humanDate}}`, `{{content}}`, `{{footer}}`

### article-snippet.html
Article excerpt for index page.

Variables: Same as article.html

### index.html
Index page listing recent posts.

Variables: `{{articles}}` (contains rendered snippets)

### feed.xml
RSS 2.0 feed template.

Variables: `{{site_title}}`, `{{site_url}}`, `{{site_description}}`, `{{items}}`

## Markup Conventions

### Wiki-Style Links
```
Link to another note: [[Note Title]]
```
Becomes: `<a href="/YYYY/MM/note-title.html">Note Title</a>`

### Footnotes
```
Here's a statement[^1]

[^1]: This is the footnote text
```

Generates anchored footnotes with return links.

## Output Structure

```
output/
├── index.html              # 30 most recent posts
├── feed.xml                # RSS feed
└── YYYY/
    └── MM/
        └── title-slug.html # Individual posts
```

## Notes to SQLite Migration

To switch from AppleScript to direct SQLite access (future):

1. Replace the `get_notes_from_folder()` function in export.py
2. Return same structure: `[{name, body, creationDate}, ...]`
3. Everything else stays the same

## Performance

**Python version**: Sub-second for dozens of notes
**Old JXA version**: 5-10+ seconds (and sometimes hangs)

The Notes.app bridge via osascript is the bottleneck, but Python's text processing is significantly faster than JXA.
