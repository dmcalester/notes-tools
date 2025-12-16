# Code Review: Notes Static Site Generator

## ✅ Security Analysis

### Database Access (VERIFIED SECURE)
All database connections use read-only mode:
- `export.py:765`: `sqlite3.connect(f"file:{NOTES_DB_PATH}?mode=ro", uri=True)`
- `publish.py:706`: `sqlite3.connect(f"file:{export.NOTES_DB_PATH}?mode=ro", uri=True)`

**No SQL injection vulnerabilities detected** - all queries use parameterized statements.

### Potential Security Issues

#### 1. 🔴 CRITICAL: Arbitrary File Write (publish.py:583-587)
**Location**: `write_file()` function
```python
def write_file(filepath, content):
    """Write content to file, creating directories as needed."""
    Path(filepath).parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w") as f:
        f.write(content)
```

**Risk**: Path traversal attack
- A malicious note title could create files outside the output directory
- Example: A note titled `../../../../etc/passwd` would attempt to write to system directories

**Fix**: Validate that output path stays within output_dir
```python
def write_file(filepath, content, output_dir=None):
    """Write content to file, creating directories as needed."""
    filepath = Path(filepath).resolve()
    
    # Ensure path is within output directory
    if output_dir:
        output_dir = Path(output_dir).resolve()
        if not str(filepath).startswith(str(output_dir)):
            raise ValueError(f"Attempted path traversal: {filepath}")
    
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w") as f:
        f.write(content)
```

#### 2. 🟡 MEDIUM: Config File Injection (export.py:48-51, publish.py:57-60)
**Location**: `load_config()` functions
```python
if config_file and config_file.exists():
    with open(config_file, "r") as f:
        file_config = json.load(f)
        config.update(file_config)
```

**Risk**: Arbitrary code execution if attacker controls config.json
- No validation of config values
- `outputDirectory` could point to sensitive locations

**Fix**: Validate configuration values
```python
def validate_config(config):
    """Validate configuration values."""
    # Validate output directory is safe
    output_dir = Path(config['outputDirectory']).resolve()
    dangerous_paths = [Path.home(), Path('/'), Path('/etc'), Path('/usr')]
    for dangerous in dangerous_paths:
        if output_dir == dangerous.resolve():
            raise ValueError(f"Unsafe output directory: {output_dir}")
    
    # Validate other critical paths
    template_dir = Path(config['templateDirectory']).resolve()
    if not template_dir.exists():
        raise ValueError(f"Template directory doesn't exist: {template_dir}")
    
    return config
```

#### 3. 🟡 MEDIUM: Template Injection (publish.py:572-577)
**Location**: `render_template()` function
```python
def render_template(template, variables):
    """Render template with {{variable}} substitution."""
    result = template
    for key, value in variables.items():
        result = result.replace(f'{{{{{key}}}}}', str(value))
    return result
```

**Risk**: If templates are user-controlled, arbitrary content injection
- Current implementation is safe if templates are trusted
- But no validation that templates come from expected location

**Fix**: Add template source validation or use a proper templating engine

#### 4. 🟡 MEDIUM: RSS Feed XML Injection (publish.py:593-615)
**Location**: `generate_rss_items()` function
```python
content = content.replace(']]>', ']]]]><![CDATA[>')

item = f'''<item>
  <title>{title}</title>
  <link>{link}</link>
  ...
</item>'''
```

**Risk**: XML injection through note titles
- Title is not escaped for XML
- Could break feed or inject malicious content

**Fix**: Escape XML special characters
```python
import html

def escape_xml(text):
    """Escape XML special characters."""
    return html.escape(text, quote=True)

# In generate_rss_items:
title = escape_xml(post["title"])
link = escape_xml(f"{site_url}/{post['slug']}.html")
```

#### 5. 🟢 LOW: .htaccess Append Mode (publish.py:621-648)
**Location**: `generate_htaccess_redirects()` function

**Risk**: Unbounded file growth
- Redirects are appended but never cleaned up
- Could grow indefinitely over time

**Fix**: Manage redirects section with markers
```python
# Generate redirects with clear markers
MARKER_START = "# BEGIN publish.py redirects\n"
MARKER_END = "# END publish.py redirects\n"

if htaccess_path.exists():
    with open(htaccess_path, "r") as f:
        content = f.read()
    
    # Remove old redirects section
    if MARKER_START in content:
        start = content.find(MARKER_START)
        end = content.find(MARKER_END) + len(MARKER_END)
        content = content[:start] + content[end:]
    
    # Append new section
    with open(htaccess_path, "w") as f:
        f.write(content)
        f.write(MARKER_START)
        for rule in new_rules:
            f.write(rule + "\n")
        f.write(MARKER_END)
```

---

## 🚀 Performance Optimizations

### 1. 🔴 CRITICAL: N+1 Query Problem (publish.py:873-915)
**Location**: Incremental publishing loop for non-updated notes

**Problem**: Processing ALL notes on every incremental build
```python
if last_published and updated_count > 0:
    # Build snippets for all OTHER notes (ones we didn't just process)
    processed_identifiers = {note["identifier"] for note in notes}
    for note in all_notes:
        if note["identifier"] in processed_identifiers:
            continue
        
        # Convert to HTML using style runs (EXPENSIVE!)
        html = convert_note_to_html(parsed, note_lookup, slug)
```

**Impact**: On a site with 1000 notes, updating 1 note processes all 1000 notes
- Defeats the purpose of incremental publishing
- `convert_note_to_html()` is expensive (protobuf parsing, style runs, etc.)

**Fix**: Cache rendered snippets
```python
# Strategy 1: Cache snippets in manifest
manifest = {
    "last_published": "...",
    "notes": {...},
    "snippets": {
        "note-slug": "<article>cached snippet html</article>",
        ...
    }
}

# Strategy 2: Write snippet files alongside HTML
# When publishing, write both article.html and article-snippet.html
# On incremental builds, read cached snippets for unchanged notes

# Strategy 3: Only regenerate index if needed
# If only one note changed and it's not in top 30, skip index regeneration
```

### 2. 🟡 MEDIUM: Redundant Slug Generation (publish.py:807-825, 834, 897)
**Location**: Multiple places generate the same slug

**Problem**: `generate_slug()` called multiple times for same note
- Line 809, 834, 897 for the same notes

**Fix**: Generate once and store
```python
# Add slug to note dict when fetching from database
for note in all_notes:
    folder_path = note.get("folder_path", [])
    note["slug"] = generate_slug(note["title"], folder_path)
```

### 3. 🟡 MEDIUM: Inefficient Folder Hierarchy Traversal (export.py:438-458)
**Location**: `get_folder_path()` function

**Problem**: Walks up tree one node at a time with individual queries
```python
while current_id and current_id != root_folder_id:
    name = get_folder_name(conn, current_id)  # Individual query!
    if name:
        path.append(name)
    current_id = get_folder_parent(conn, current_id)  # Another query!
```

**Fix**: Single query to get entire path
```python
def get_folder_path_optimized(conn, folder_id, root_folder_id):
    """Get folder path with recursive CTE (single query)."""
    cursor = conn.cursor()
    cursor.execute('''
        WITH RECURSIVE folder_path(id, name, parent, level) AS (
            SELECT Z_PK, ZTITLE2, ZPARENT, 0
            FROM ZICCLOUDSYNCINGOBJECT
            WHERE Z_PK = ?
            
            UNION ALL
            
            SELECT f.Z_PK, f.ZTITLE2, f.ZPARENT, fp.level + 1
            FROM ZICCLOUDSYNCINGOBJECT f
            JOIN folder_path fp ON f.Z_PK = fp.parent
            WHERE f.Z_PK != ?
        )
        SELECT name FROM folder_path 
        WHERE id != ? 
        ORDER BY level DESC
    ''', (folder_id, root_folder_id, root_folder_id))
    
    return [row[0] for row in cursor.fetchall()]
```

### 4. 🟡 MEDIUM: Duplicate Note Lookup Building (publish.py:787-803)
**Location**: Building note_lookup from all_notes

**Problem**: Iterates through all_notes twice (once for lookup, once for collisions)

**Fix**: Single pass with collision detection
```python
note_lookup = {}
slug_to_notes = {}

for note in all_notes:
    title = note["title"]
    identifier = note["identifier"]
    folder_path = note.get("folder_path", [])
    
    # Generate slug once
    if identifier in manifest_notes:
        slug = manifest_notes[identifier].lstrip("/")
    else:
        slug = generate_slug(title, folder_path)
    
    # Check collision while building
    if slug in slug_to_notes:
        existing = slug_to_notes[slug]
        print(f"Error: Slug collision detected for '{slug}':", file=sys.stderr)
        print(f"  - '{existing['title']}' (ID: {existing['identifier']})", file=sys.stderr)
        print(f"  - '{title}' (ID: {identifier})", file=sys.stderr)
        sys.exit(1)
    
    # Build both lookups in one pass
    note_lookup[title] = {
        "slug": slug,
        "creationDate": note["creation_date"],
        "identifier": identifier,
    }
    slug_to_notes[slug] = note
```

### 5. 🟢 LOW: Protobuf Parsing Inefficiency (export.py:206-234)
**Location**: `extract_strings_from_protobuf()` recursive parsing

**Problem**: Recursively parses same data looking for strings (not critical as it's called once per note)

**Optimization**: Could use protobuf library instead of manual parsing
```python
# Consider using google.protobuf library if schema is known
# Would be faster and more reliable than manual parsing
```

---

## 🏗️ Brittleness & Reliability

### 1. 🔴 CRITICAL: Database Schema Assumptions
**Location**: Throughout export.py

**Problem**: Hardcoded column names (ZFOLDER, ZPARENT, ZTITLE2, etc.)
- Apple could change schema in any Notes update
- No version checking or graceful degradation

**Fix**: Add schema version detection
```python
def check_database_schema(conn):
    """Verify expected database schema."""
    cursor = conn.cursor()
    
    # Check for expected columns
    cursor.execute("PRAGMA table_info(ZICCLOUDSYNCINGOBJECT)")
    columns = {row[1] for row in cursor.fetchall()}
    
    required = {'Z_PK', 'ZTITLE2', 'ZFOLDER', 'ZPARENT', 'ZTITLE1', 'ZDATA'}
    missing = required - columns
    
    if missing:
        raise RuntimeError(
            f"Database schema incompatible. Missing columns: {missing}\n"
            f"This may indicate an incompatible Notes.app version."
        )
```

### 2. 🟡 MEDIUM: Protobuf Format Assumptions (export.py:269-360)
**Location**: Style run extraction

**Problem**: Reverse-engineered protobuf structure could break
- Field numbers are hardcoded (field 2, field 3, field 5, etc.)
- No error handling for unexpected format

**Fix**: Add defensive parsing with fallback
```python
def extract_style_runs(data: bytes, text: str) -> list:
    """Extract style runs with error handling."""
    try:
        return _extract_style_runs_impl(data, text)
    except Exception as e:
        # Log warning but don't fail
        import sys
        print(f"Warning: Could not parse formatting: {e}", file=sys.stderr)
        # Return empty list - note will publish as plain text
        return []
```

### 3. 🟡 MEDIUM: Manifest Corruption Recovery (publish.py:79-116)
**Location**: `load_manifest()` and `save_manifest()`

**Problem**: No validation or corruption recovery
- Invalid JSON crashes the script
- Corrupted manifest breaks incremental publishing

**Fix**: Add validation and recovery
```python
def load_manifest(config_path=None):
    """Load manifest with validation and recovery."""
    config_dir = find_config_dir(config_path)
    if config_dir is None:
        return None
    
    manifest_path = config_dir / "manifest.json"
    if not manifest_path.exists():
        return None
    
    try:
        with open(manifest_path, "r") as f:
            manifest = json.load(f)
        
        # Validate structure
        if not isinstance(manifest, dict):
            raise ValueError("Manifest must be a dict")
        if "notes" not in manifest or not isinstance(manifest["notes"], dict):
            raise ValueError("Manifest missing 'notes' field")
        
        return manifest
    
    except (json.JSONDecodeError, ValueError) as e:
        print(f"Warning: Corrupted manifest ({e}), forcing full rebuild", 
              file=sys.stderr)
        # Backup corrupted manifest
        backup_path = manifest_path.with_suffix('.json.corrupt')
        manifest_path.rename(backup_path)
        return None
```

### 4. 🟡 MEDIUM: Template Loading Failures (publish.py:557-569)
**Location**: `load_template()` function

**Problem**: Missing template causes hard exit
- No helpful error message about which templates are needed
- Could fail partway through publishing

**Fix**: Validate all templates upfront
```python
def validate_templates(template_dir):
    """Ensure all required templates exist before starting."""
    required = ['article.html', 'article-snippet.html', 'index.html', 'feed.xml']
    missing = []
    
    for template in required:
        ext = '.xml' if template.endswith('.xml') else '.html'
        path = Path(template_dir) / template
        if not path.exists():
            missing.append(str(path))
    
    if missing:
        print("Error: Missing required templates:", file=sys.stderr)
        for path in missing:
            print(f"  - {path}", file=sys.stderr)
        sys.exit(1)

# Call in main() before processing
validate_templates(template_dir)
```

### 5. 🟢 LOW: Folder Not Found Handling (publish.py:709-712)
**Location**: Main function folder lookup

**Problem**: Unhelpful error when folder not found
- Doesn't suggest similar folder names

**Fix**: Better error message with suggestions
```python
folder_id = export.get_folder_id(conn, folder_name)
if folder_id is None:
    # Get all folders for suggestions
    cursor = conn.cursor()
    cursor.execute(
        "SELECT ZTITLE2 FROM ZICCLOUDSYNCINGOBJECT WHERE ZTITLE2 IS NOT NULL"
    )
    available = [row[0] for row in cursor.fetchall()]
    
    print(f"Error: Folder '{folder_name}' not found", file=sys.stderr)
    print("\nAvailable folders:", file=sys.stderr)
    for folder in sorted(available):
        print(f"  - {folder}", file=sys.stderr)
    sys.exit(1)
```

### 6. 🟢 LOW: Style Run Position Tracking (export.py:283-360, publish.py:179-215)
**Location**: Style run processing

**Problem**: Complex position tracking logic prone to off-by-one errors
- Assumes runs are contiguous and non-overlapping
- No validation that runs cover the full text

**Fix**: Add assertions and validation
```python
def validate_style_runs(text: str, style_runs: list):
    """Validate that style runs are valid."""
    if not style_runs:
        return
    
    # Check runs are within bounds
    for run in style_runs:
        if run.start < 0:
            raise ValueError(f"Negative run start: {run.start}")
        if run.start + run.length > len(text):
            raise ValueError(
                f"Run extends past text end: {run.start}+{run.length} > {len(text)}"
            )
```

---

## 📊 Code Quality Issues

### 1. 🟡 Code Duplication: Config Loading
**Locations**: export.py:31-53, publish.py:35-76

**Problem**: Two similar but not identical config loading functions

**Fix**: Move to shared module
```python
# common.py
def load_config(config_path=None, cli_args=None, defaults=None):
    """Unified config loading."""
    # ...
```

### 2. 🟡 Missing Type Hints
**Location**: Throughout publish.py

**Problem**: No type hints in publish.py (export.py has some)

**Fix**: Add type hints for better IDE support and error detection

### 3. 🟡 Long Functions
**Location**: 
- `publish.py:main()` - 260 lines (653-911)
- `publish.py:convert_note_to_html()` - 55 lines (325-380)

**Problem**: Hard to understand, test, and maintain

**Fix**: Break into smaller functions with clear responsibilities

---

## Summary Priority Rankings

### Security (Fix Immediately)
1. 🔴 Path traversal in `write_file()` - Could write files anywhere
2. 🟡 XML injection in RSS feed - Could break feeds
3. 🟡 Config validation - Prevent dangerous configurations

### Performance (Fix for Scale)
1. 🔴 Incremental publishing processes all notes - Defeats purpose
2. 🟡 Redundant slug generation - Easy wins
3. 🟡 Folder path traversal - N+1 queries

### Reliability (Fix for Robustness)
1. 🔴 Database schema assumptions - Will break on Notes updates
2. 🟡 Manifest corruption - Breaks incremental builds
3. 🟡 Template validation - Better error messages

### Overall Recommendations
1. **Immediate**: Fix path traversal vulnerability
2. **Short-term**: Cache rendered snippets for incremental builds
3. **Medium-term**: Add schema version detection and validation
4. **Long-term**: Refactor for testability and maintainability
