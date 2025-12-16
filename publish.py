#!/usr/bin/env python3

"""
Publish notes as static HTML.

Takes parsed note data from export.py and generates HTML files
using templates. Handles conversion of style runs to HTML markup.
"""

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

# Import the export module for parsing
import export


def find_config_dir(config_path=None):
    """Find the directory containing config.json."""
    if config_path:
        return Path(config_path).parent

    script_dir = Path(__file__).parent
    if (script_dir / "config.json").exists():
        return script_dir
    elif Path("config.json").exists():
        return Path.cwd()
    else:
        return None


def load_config(config_path=None, cli_args=None):
    """Load configuration from file and merge with CLI arguments."""
    config = {
        "notesFolderName": "test",
        "templateDirectory": "./templates",
        "outputDirectory": "./output",
        "siteTitle": "My Blog",
        "siteUrl": "https://example.com",
        "siteDescription": "Notes from the field",
    }

    if config_path:
        config_file = Path(config_path)
    else:
        script_dir = Path(__file__).parent
        if (script_dir / "config.json").exists():
            config_file = script_dir / "config.json"
        elif Path("config.json").exists():
            config_file = Path("config.json")
        else:
            config_file = None

    if config_file and config_file.exists():
        with open(config_file, "r") as f:
            file_config = json.load(f)
            config.update(file_config)

    if cli_args:
        if cli_args.folder:
            config["notesFolderName"] = cli_args.folder
        if cli_args.templates:
            config["templateDirectory"] = cli_args.templates
        if cli_args.output:
            config["outputDirectory"] = cli_args.output
        if cli_args.site_url:
            config["siteUrl"] = cli_args.site_url
        if cli_args.site_title:
            config["siteTitle"] = cli_args.site_title
        if cli_args.site_description:
            config["siteDescription"] = cli_args.site_description

    return config


def load_manifest(config_path=None):
    """Load the publish manifest from the config directory."""
    config_dir = find_config_dir(config_path)
    if config_dir is None:
        return None

    manifest_path = config_dir / "manifest.json"
    if not manifest_path.exists():
        return None

    with open(manifest_path, "r") as f:
        return json.load(f)


def save_manifest(config_path=None):
    """Save the publish manifest with current timestamp (UTC)."""
    from datetime import timezone

    config_dir = find_config_dir(config_path)
    if config_dir is None:
        # Fall back to current directory
        config_dir = Path.cwd()

    manifest_path = config_dir / "manifest.json"
    manifest = {"last_published": datetime.now(timezone.utc).isoformat()}

    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    return manifest_path


# --- Helper Functions ---


def generate_slug(title, creation_date):
    """Generate URL slug from title and date: YYYY/MM/title-slug"""
    year = creation_date.strftime("%Y")
    month = creation_date.strftime("%m")

    title_slug = title.lower()
    title_slug = re.sub(r"[^a-z0-9\s]", "", title_slug)
    title_slug = re.sub(r"\s+", "-", title_slug)

    return f"{year}/{month}/{title_slug}"


def format_date(dt):
    """Format date for display: January 1, 2025"""
    return dt.strftime("%B %d, %Y").replace(" 0", " ")


def format_datetime(dt):
    """Format datetime for HTML datetime attribute: ISO 8601"""
    return dt.isoformat()


def format_rfc822_date(dt):
    """Format datetime for RSS pubDate: RFC 822"""
    return dt.strftime("%a, %d %b %Y %H:%M:%S +0000")


def escape_html(text):
    """Escape HTML special characters."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# --- Style Run to HTML Conversion ---


def style_runs_to_html(text, style_runs, note_lookup, slug):
    """
    Convert text with style runs to HTML.

    This processes the style runs to wrap text in appropriate HTML tags.
    """
    if not style_runs:
        # No formatting, just escape and wrap in paragraphs
        return text_to_paragraphs(escape_html(text))

    # Build HTML by processing each character position
    # First, create a map of positions to their formatting
    pos_to_runs = {}
    for run in style_runs:
        for i in range(run.start, run.start + run.length):
            if i not in pos_to_runs:
                pos_to_runs[i] = []
            pos_to_runs[i].append(run)

    # Process text and apply formatting
    result = []
    i = 0

    while i < len(text):
        runs_at_pos = pos_to_runs.get(i, [])

        if not runs_at_pos:
            # No formatting, just add the character
            char = text[i]
            if char == "\n":
                result.append("\n")
            else:
                result.append(escape_html(char))
            i += 1
        else:
            # Find the run that starts at this position (or use any run)
            run = runs_at_pos[0]
            run_text = text[run.start : run.start + run.length]

            # Build the HTML for this run
            html = format_run_as_html(run, run_text, note_lookup, slug)
            result.append(html)

            # Skip to end of this run
            i = run.start + run.length

    # Join and convert to paragraphs
    raw_html = "".join(result)
    return text_to_paragraphs(raw_html)


def format_run_as_html(run, text, note_lookup, slug):
    """Format a single style run as HTML."""
    # Escape the text first
    html = escape_html(text)

    # Apply inline formatting (innermost first)
    if run.is_superscript:
        html = f"<sup>{html}</sup>"

    if run.is_bold:
        html = f"<strong>{html}</strong>"

    if run.is_italic:
        html = f"<em>{html}</em>"

    if run.is_underline:
        html = f"<u>{html}</u>"

    if run.is_strikethrough:
        html = f"<s>{html}</s>"

    # Handle links
    if run.link_url:
        if run.link_url.startswith("applenotes:note/"):
            # Internal note link - resolve to slug
            note_id = run.link_url.split("?")[0].split("/")[-1].lower()
            target_slug = None
            for title, info in note_lookup.items():
                if info.get("identifier", "").lower() == note_id:
                    target_slug = info["slug"]
                    break
            if target_slug:
                html = f'<a href="/{target_slug}.html">{html}</a>'
            else:
                # Link to unknown note, just show text
                pass
        else:
            # External link
            html = f'<a href="{run.link_url}">{html}</a>'

    return html


def text_to_paragraphs(html):
    """Convert text with newlines to proper HTML paragraphs and blocks."""
    lines = html.split("\n")
    result = []
    current_block = None  # Track if we're in a list or blockquote
    buffer = []

    def flush_buffer():
        if buffer:
            text = " ".join(buffer).strip()
            if text:
                result.append(f"<p>{text}</p>")
            buffer.clear()

    for line in lines:
        stripped = line.strip()

        if not stripped:
            flush_buffer()
            continue

        # Check for block-level elements already in the text
        if stripped.startswith("<h") or stripped.startswith("<blockquote"):
            flush_buffer()
            result.append(stripped)
        else:
            buffer.append(stripped)

    flush_buffer()
    return "\n".join(result)


def get_run_format_key(run):
    """Get a formatting signature for a run to determine if it can be merged."""
    return (
        run.is_bold,
        run.is_italic,
        run.is_superscript,
        run.is_underline,
        run.is_strikethrough,
        run.link_url,
    )


def get_block_type(run):
    """Determine the block type for a style run."""
    if run.is_blockquote:
        return "blockquote"
    elif run.paragraph_style == export.PARA_STYLE_HEADING:
        return "h1"
    elif run.paragraph_style == export.PARA_STYLE_SUBHEADING:
        return "h2"
    elif run.paragraph_style == export.PARA_STYLE_MONO:
        return "code"
    elif run.paragraph_style == export.PARA_STYLE_BULLET_LIST:
        return "ul"
    elif run.paragraph_style == export.PARA_STYLE_DASH_LIST:
        return "ul-dash"
    elif run.paragraph_style == export.PARA_STYLE_NUMBER_LIST:
        return "ol"
    else:
        return "normal"


def convert_note_to_html(parsed_note, note_lookup, slug):
    """
    Convert a parsed note to HTML content.

    Uses style runs to generate properly formatted HTML.
    """
    full_text = parsed_note.title + "\n" + parsed_note.text_content
    style_runs = parsed_note.style_runs

    # Calculate where the title ends (title + newline)
    title_end_pos = len(parsed_note.title) + 1  # +1 for the newline after title

    # Skip if no style runs
    if not style_runs:
        # Just return the body as paragraphs
        paragraphs = parsed_note.text_content.split("\n\n")
        return "\n\n".join(
            f"<p>{escape_html(p.strip())}</p>" for p in paragraphs if p.strip()
        )

    # Group runs by paragraph/block type, skipping the title
    blocks = []
    current_block = None

    for run in style_runs:
        # Skip runs that are entirely within the title portion
        # (title is already shown in the template header)
        if run.start + run.length <= title_end_pos:
            continue

        block_type = get_block_type(run)

        # Skip title style blocks too (in case some notes do mark it)
        if block_type == "h1":
            continue

        # Check if we need to start a new block
        if current_block is None or block_type != current_block["type"]:
            if current_block is not None and current_block["runs"]:
                blocks.append(current_block)
            current_block = {"type": block_type, "runs": []}

        current_block["runs"].append(run)

    # Don't forget the last block
    if current_block is not None and current_block["runs"]:
        blocks.append(current_block)

    # Convert blocks to HTML
    html_parts = []
    for block in blocks:
        block_html = render_block(block, full_text, note_lookup, slug)
        if block_html:
            html_parts.append(block_html)

    return "\n\n".join(html_parts)


def merge_runs_for_rendering(runs, full_text):
    """
    Merge adjacent runs with the same inline formatting.

    This prevents fragmented output like <strong>bo</strong><strong>ld</strong>
    by combining runs that have identical formatting into a single run.
    """
    if not runs:
        return []

    merged = []
    current = None

    for run in runs:
        run_text = full_text[run.start : run.start + run.length]
        format_key = get_run_format_key(run)

        if current is None:
            current = {
                "text": run_text,
                "format_key": format_key,
                "run": run,  # Keep reference for formatting info
            }
        elif format_key == current["format_key"]:
            # Same formatting - merge the text
            current["text"] += run_text
        else:
            # Different formatting - save current and start new
            merged.append(current)
            current = {
                "text": run_text,
                "format_key": format_key,
                "run": run,
            }

    # Don't forget the last one
    if current is not None:
        merged.append(current)

    return merged


def format_merged_run_as_html(merged_run, note_lookup, slug):
    """Format a merged run as HTML."""
    run = merged_run["run"]
    text = merged_run["text"]

    # Check if this run has any inline formatting
    has_inline_formatting = (
        run.is_superscript
        or run.is_bold
        or run.is_italic
        or run.is_underline
        or run.is_strikethrough
        or run.link_url
    )

    # For runs with inline formatting, handle trailing newlines separately
    # to prevent tags from spanning across paragraph breaks
    trailing_newlines = ""
    if has_inline_formatting:
        stripped = text.rstrip("\n")
        trailing_newlines = text[len(stripped) :]
        text = stripped

    # Escape the text first
    html = escape_html(text)

    # Apply inline formatting (innermost first)
    if run.is_superscript:
        html = f"<sup>{html}</sup>"

    if run.is_bold:
        html = f"<strong>{html}</strong>"

    if run.is_italic:
        html = f"<em>{html}</em>"

    if run.is_underline:
        html = f"<u>{html}</u>"

    if run.is_strikethrough:
        html = f"<s>{html}</s>"

    # Handle links
    if run.link_url:
        if run.link_url.startswith("applenotes:note/"):
            # Internal note link - resolve to slug
            note_id = run.link_url.split("?")[0].split("/")[-1].lower()
            target_slug = None
            for title, info in note_lookup.items():
                if info.get("identifier", "").lower() == note_id:
                    target_slug = info["slug"]
                    break
            if target_slug:
                html = f'<a href="/{target_slug}.html">{html}</a>'
        else:
            # External link
            html = f'<a href="{run.link_url}">{html}</a>'

    # Add trailing newlines back after formatting
    html += trailing_newlines

    return html


def render_block(block, full_text, note_lookup, slug):
    """Render a block of styled text as HTML."""
    block_type = block["type"]
    runs = block["runs"]

    if not runs:
        return ""

    # Merge adjacent runs with the same formatting
    merged_runs = merge_runs_for_rendering(runs, full_text)

    # Build content from merged runs
    content_parts = []
    for merged_run in merged_runs:
        html = format_merged_run_as_html(merged_run, note_lookup, slug)
        content_parts.append(html)

    content = "".join(content_parts)

    # Strip trailing newlines for block elements
    content = content.rstrip("\n")

    # Wrap in appropriate block element
    if block_type == "h2":
        # Strip the newline that often ends headings
        return f"<h2>{content.strip()}</h2>"
    elif block_type == "h3":
        return f"<h3>{content.strip()}</h3>"
    elif block_type == "code":
        return f"<pre><code>{content}</code></pre>"
    elif block_type == "blockquote":
        # Convert newlines to <br> or paragraphs inside blockquote
        inner = content.replace("\n\n", "</p><p>").replace("\n", "<br>")
        return f"<blockquote><p>{inner}</p></blockquote>"
    elif block_type in ("ul", "ul-dash"):
        # Split by newlines to create list items
        items = [item.strip() for item in content.split("\n") if item.strip()]
        li_items = "\n".join(f"<li>{item}</li>" for item in items)
        return f"<ul>\n{li_items}\n</ul>"
    elif block_type == "ol":
        items = [item.strip() for item in content.split("\n") if item.strip()]
        li_items = "\n".join(f"<li>{item}</li>" for item in items)
        return f"<ol>\n{li_items}\n</ol>"
    else:
        # Normal paragraph
        # Split by double newlines for paragraphs
        paragraphs = content.split("\n\n")
        p_tags = []
        for p in paragraphs:
            p = p.strip()
            if p:
                # Convert single newlines to spaces within paragraph
                p = p.replace("\n", " ")
                p_tags.append(f"<p>{p}</p>")
        return "\n".join(p_tags)


def process_footnotes(html, slug):
    """Process footnote references in the HTML."""
    # Find superscript numbers that could be footnotes
    # For now, we just return the html as-is since superscripts are already marked
    # A more sophisticated version would match footnotes with their definitions
    return {"content": html, "footer": ""}


# --- Template Engine ---


def load_template(template_dir, name):
    """Load template file."""
    if name == "feed":
        template_path = Path(template_dir) / "feed.xml"
    else:
        template_path = Path(template_dir) / f"{name}.html"

    if not template_path.exists():
        print(f"Error: Template not found: {template_path}", file=sys.stderr)
        sys.exit(1)

    with open(template_path, "r") as f:
        return f.read()


def render_template(template, variables):
    """Render template with {{variable}} substitution."""
    result = template
    for key, value in variables.items():
        result = result.replace(f"{{{{{key}}}}}", str(value))
    return result


# --- File Writing ---


def write_file(filepath, content):
    """Write content to file, creating directories as needed."""
    Path(filepath).parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w") as f:
        f.write(content)


# --- RSS Generation ---


def generate_rss_items(posts, site_url):
    """Generate RSS item elements for posts."""
    items = []
    recent_posts = sorted(posts, key=lambda p: p["creationDate"], reverse=True)[:30]

    for post in recent_posts:
        title = post["title"]
        link = f"{site_url}/{post['slug']}.html"
        pub_date = format_rfc822_date(post["creationDate"])
        content = post["content"]

        content = content.replace("]]>", "]]]]><![CDATA[>")

        item = f"""<item>
  <title>{title}</title>
  <link>{link}</link>
  <pubDate>{pub_date}</pubDate>
  <description><![CDATA[{content}]]></description>
  <guid>{link}</guid>
</item>"""
        items.append(item)

    return "\n".join(items)


# --- Main ---


def main():
    parser = argparse.ArgumentParser(description="Publish notes as static HTML")
    parser.add_argument("--config", help="Path to config.json file")
    parser.add_argument("--folder", help="Notes folder name")
    parser.add_argument("--templates", help="Template directory path")
    parser.add_argument("--output", help="Output directory path")
    parser.add_argument("--site-url", help="Site URL for RSS feed")
    parser.add_argument("--site-title", help="Site title for RSS feed")
    parser.add_argument("--site-description", help="Site description for RSS feed")

    args = parser.parse_args()

    # Load configuration
    config = load_config(args.config, args)

    folder_name = config["notesFolderName"]
    template_dir = config["templateDirectory"]
    output_dir = config["outputDirectory"]
    site_title = config["siteTitle"]
    site_url = config["siteUrl"]
    site_description = config["siteDescription"]

    # Load manifest for incremental publishing
    manifest = load_manifest(args.config)
    last_published = None
    if manifest and "last_published" in manifest:
        last_published = datetime.fromisoformat(manifest["last_published"])

    # Ensure output directory exists
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    # Load templates
    article_template = load_template(template_dir, "article")
    snippet_template = load_template(template_dir, "article-snippet")
    index_template = load_template(template_dir, "index")
    feed_template = load_template(template_dir, "feed")

    # Get notes from database via export module
    import os
    import sqlite3

    if not os.path.exists(export.NOTES_DB_PATH):
        print(
            f"Error: Notes database not found at {export.NOTES_DB_PATH}",
            file=sys.stderr,
        )
        sys.exit(1)

    conn = sqlite3.connect(f"file:{export.NOTES_DB_PATH}?mode=ro", uri=True)

    try:
        folder_id = export.get_folder_id(conn, folder_name)
        if folder_id is None:
            print(f"Error: Folder '{folder_name}' not found", file=sys.stderr)
            sys.exit(1)

        all_notes = export.get_notes_from_folder(conn, folder_id)
    finally:
        conn.close()

    if not all_notes:
        print(f"Error: No notes found in folder '{folder_name}'", file=sys.stderr)
        sys.exit(1)

    # Filter notes by modification date if manifest exists
    if last_published:
        notes = [
            note
            for note in all_notes
            if note["modification_date"] and note["modification_date"] > last_published
        ]
        if not notes:
            print(f"No notes modified since {last_published.isoformat()}")
            sys.exit(0)
    else:
        notes = all_notes

    # Build note lookup for link resolution (use all_notes so links resolve even in incremental mode)
    note_lookup = {}
    for note in all_notes:
        title = note["title"]
        creation_date = note["creation_date"]
        slug = generate_slug(title, creation_date)
        note_lookup[title] = {
            "slug": slug,
            "creationDate": creation_date,
            "identifier": note["identifier"],
        }

    # Process each note
    posts = []

    for note in notes:
        title = note["title"]
        creation_date = note["creation_date"]
        slug = generate_slug(title, creation_date)
        datetime_str = format_datetime(creation_date)
        human_date = format_date(creation_date)

        parsed = note["parsed_content"]

        # Convert to HTML using style runs
        html = convert_note_to_html(parsed, note_lookup, slug)

        # Process footnotes
        footnote_result = process_footnotes(html, slug)
        html = footnote_result["content"]

        # Apply templates
        template_vars = {
            "title": title,
            "slug": slug,
            "datetime": datetime_str,
            "humanDate": human_date,
            "content": html,
            "footer": footnote_result["footer"],
        }

        article_output = render_template(article_template, template_vars)
        snippet_output = render_template(snippet_template, template_vars)

        # Write article file
        write_file(f"{output_dir}/{slug}.html", article_output)

        # Store post data for index and RSS
        posts.append(
            {
                "title": title,
                "slug": slug,
                "creationDate": creation_date,
                "humanDate": human_date,
                "content": html,
                "articleSnippet": snippet_output,
            }
        )

    # Generate index page
    posts_sorted = sorted(posts, key=lambda p: p["creationDate"], reverse=True)[:30]
    articles_html = "\n".join([p["articleSnippet"] for p in posts_sorted])
    index_html = render_template(index_template, {"articles": articles_html})
    write_file(f"{output_dir}/index.html", index_html)

    # Generate RSS feed
    rss_items = generate_rss_items(posts, site_url)
    feed_vars = {
        "site_title": site_title,
        "site_url": site_url,
        "site_description": site_description,
        "items": rss_items,
    }
    feed_xml = render_template(feed_template, feed_vars)
    write_file(f"{output_dir}/feed.xml", feed_xml)

    # Save manifest with current timestamp
    manifest_path = save_manifest(args.config)

    if last_published:
        print(f"Published {len(posts)} updated posts to {output_dir}")
    else:
        print(f"Published {len(posts)} posts to {output_dir}")
    print(f"Manifest saved to {manifest_path}")


if __name__ == "__main__":
    main()
