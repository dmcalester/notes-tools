# Notes Export

Inspired by recollection of Jon Gruber’s reasons for creating Markdown for [Daring Fireball](https://daringfireball.net/) - a simple way to focus on writing, and not structure. I love Apple’s Notes app, it’s focused and with just enough structure and formatting to keep my focused on content and not presentation or ogranization. I’ve always thought it would be a great minimal Content Management System for simple blog-like web sites.

Export notes from Apple Notes to static HTML blog posts with support for:
- Direct SQLite database access (no AppleScript/osascript)
- Rich text formatting (bold, italic, links, lists, headings, code blocks)
- Internal note links (converted to HTML links)
- Nested folders with hierarchical URLs
- RSS feed generation
- Incremental publishing (only regenerates modified notes)
- Automatic redirects for moved notes

## Requirements

- macOS (accesses Notes.app SQLite database)
- Python 3.6+ (built-in on modern macOS)

## Quick Start

```bash
# Publish notes to static HTML
python3 publish.py

# Specify different folder
python3 publish.py --folder "Blog Posts"

# Force publish even if notes moved (generates redirects)
python3 publish.py --force

# Export notes to JSON (for inspection/debugging)
python3 export.py --folder "test" --verbose
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

## Commands

### publish.py - Generate Static Site

Main command to publish notes as HTML:

```bash
python3 publish.py [options]
```

**Options:**
- `--config CONFIG` - Path to config.json file
- `--folder FOLDER` - Notes folder name (overrides config)
- `--templates TEMPLATES` - Template directory path
- `--output OUTPUT` - Output directory path
- `--site-url SITE_URL` - Site URL for RSS feed
- `--site-title SITE_TITLE` - Site title for RSS feed
- `--site-description SITE_DESCRIPTION` - Site description
- `--force` - Force publish even if notes moved (generates redirects)

### export.py - Export to JSON

Export notes metadata and content to JSON:

```bash
python3 export.py [options]
```

**Options:**
- `--config CONFIG` - Path to config.json file
- `--folder FOLDER` - Notes folder name (overrides config)
- `--output OUTPUT` - Output JSON file path
- `--verbose` - Print detailed note content
- `--formatting` - Include formatting/style information

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

## Features

### Rich Text Support

Notes.app formatting is preserved:
- **Bold** and *italic* text
- Headings (H1, H2)
- Bulleted and numbered lists
- Monospace/code blocks
- Blockquotes
- Links (internal and external)
- Strikethrough and underline
- Superscript (for footnotes)

### Internal Note Links

Links between notes in Notes.app are automatically converted to HTML links:
```
[[Other Note Title]]
```
Becomes: `<a href="/folder/other-note-title.html">Other Note Title</a>`

### Nested Folders

Notes in subfolders get hierarchical URLs:
```
Blog/
  Tech/
    My Note.md  →  /tech/my-note.html
  Personal/
    Thoughts.md →  /personal/thoughts.html
```

### Incremental Publishing

Only modified notes are regenerated on subsequent runs:
- Manifest tracks last publish time and note paths
- Cached snippets for unchanged notes (fast index/RSS generation)
- Automatic redirect generation for moved notes

### Footnotes

Superscript numbers in Notes.app are converted to proper HTML footnotes with return links.

## Output Structure

```
output/
├── index.html                      # 30 most recent posts
├── feed.xml                        # RSS feed (30 most recent)
├── .htaccess                       # Redirects for moved notes
├── article-name.html               # Top-level articles
└── folder-name/
    └── nested-article.html         # Nested folder articles
```

## How It Works

1. **Read Notes Database**: Directly queries Notes.app SQLite database (`~/Library/Group Containers/group.com.apple.notes/NoteStore.sqlite`)
2. **Parse Protobuf**: Extracts note content and formatting from gzip-compressed protobuf data
3. **Generate HTML**: Converts rich text formatting to semantic HTML
4. **Build Site**: Creates article pages, index, and RSS feed from templates
5. **Save Manifest**: Tracks published notes and cached snippets for incremental builds

## Performance

- **Full rebuild**: ~100ms for 6 notes
- **Incremental**: ~50ms (2x faster, scales to 10-100x with more notes)
- **Direct SQLite access**: No AppleScript overhead
- **Cached snippets**: Avoids regenerating unchanged notes

## Security & Validation

The codebase includes comprehensive security measures:
- Path traversal protection (prevents writing outside output directory)
- XML escaping for RSS feeds
- Config validation (blocks dangerous output paths)
- Database schema validation (detects incompatible Notes versions)
- Manifest corruption recovery (automatic backup and rebuild)

## Troubleshooting

### "Notes database not found"
The database path is: `~/Library/Group Containers/group.com.apple.notes/NoteStore.sqlite`

If Notes.app is running, this should exist. If not, check your Notes.app installation.

### "Database schema incompatible"
Your Notes.app version may have changed the database structure. Please report this issue with your macOS and Notes.app versions.

### "Folder not found"
The script lists available folders in the error message. Folder names are case-sensitive.

### Permission errors
You may need to grant Full Disk Access to Terminal or Python in:
System Preferences → Privacy & Security → Full Disk Access
