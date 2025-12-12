#!/usr/bin/env python3

"""
Export notes from Notes.app to static HTML blog posts.

A spiritual successor to Markdown - authoring in Notes.app with minimal markup,
exporting to clean HTML with support for [[wiki links]], footnotes, and RSS.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path


# --- Configuration ---

def load_config(config_path=None, cli_args=None):
    """Load configuration from file and merge with CLI arguments."""
    config = {
        'notesFolderName': 'test',
        'templateDirectory': './templates',
        'outputDirectory': './output',
        'siteTitle': 'My Blog',
        'siteUrl': 'https://example.com',
        'siteDescription': 'Notes from the field'
    }
    
    # Try to find config file
    if config_path:
        config_file = Path(config_path)
    else:
        # Check script directory first, then current working directory
        script_dir = Path(__file__).parent
        if (script_dir / 'config.json').exists():
            config_file = script_dir / 'config.json'
        elif Path('config.json').exists():
            config_file = Path('config.json')
        else:
            config_file = None
    
    # Load config file if found
    if config_file and config_file.exists():
        with open(config_file, 'r') as f:
            file_config = json.load(f)
            config.update(file_config)
    
    # Override with CLI arguments
    if cli_args:
        if cli_args.folder:
            config['notesFolderName'] = cli_args.folder
        if cli_args.templates:
            config['templateDirectory'] = cli_args.templates
        if cli_args.output:
            config['outputDirectory'] = cli_args.output
        if cli_args.site_url:
            config['siteUrl'] = cli_args.site_url
        if cli_args.site_title:
            config['siteTitle'] = cli_args.site_title
        if cli_args.site_description:
            config['siteDescription'] = cli_args.site_description
    
    return config


# --- Dependency Check ---

def check_dependencies():
    """Verify osascript is available."""
    if not Path('/usr/bin/osascript').exists():
        print("Error: osascript not found. This script requires macOS.", file=sys.stderr)
        sys.exit(1)


# --- Notes.app Bridge ---

def get_notes_from_folder(folder_name):
    """Fetch all notes from specified Notes.app folder via JXA (JavaScript for Automation)."""
    # Use JXA to get notes and output as JSON for easy parsing
    script = f'''
        const app = Application("Notes");
        const notes = [];
        
        for (const account of app.accounts()) {{
            for (const folder of account.folders()) {{
                if (folder.name() === "{folder_name}") {{
                    for (const note of folder.notes()) {{
                        notes.push({{
                            name: note.name(),
                            body: note.body(),
                            creationDate: note.creationDate().toISOString()
                        }});
                    }}
                }}
            }}
        }}
        
        JSON.stringify(notes);
    '''
    
    try:
        result = subprocess.run(
            ['osascript', '-l', 'JavaScript', '-e', script],
            capture_output=True,
            text=True,
            check=True
        )
        
        # Parse JSON output
        output = result.stdout.strip()
        if not output or output == '':
            return []
        
        notes_data = json.loads(output)
        
        # Convert ISO date strings to datetime objects
        for note in notes_data:
            note['creationDate'] = datetime.fromisoformat(note['creationDate'].replace('Z', '+00:00'))
        
        return notes_data
        
    except subprocess.CalledProcessError as e:
        print(f"Error: Failed to fetch notes from Notes.app", file=sys.stderr)
        print(f"Details: {e.stderr}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error: Failed to parse notes data", file=sys.stderr)
        print(f"Details: {e}", file=sys.stderr)
        sys.exit(1)


# --- Helper Functions ---

def generate_slug(title, creation_date):
    """Generate URL slug from title and date: YYYY/MM/title-slug"""
    year = creation_date.strftime('%Y')
    month = creation_date.strftime('%m')
    
    # Clean title for URL
    title_slug = title.lower()
    title_slug = re.sub(r'[^a-z0-9\s]', '', title_slug)
    title_slug = re.sub(r'\s+', '-', title_slug)
    
    return f"{year}/{month}/{title_slug}"


def format_date(dt):
    """Format date for display: January 1, 2025"""
    return dt.strftime('%B %d, %Y').replace(' 0', ' ')  # Remove leading zero from day


def format_datetime(dt):
    """Format datetime for HTML datetime attribute: ISO 8601"""
    return dt.isoformat()


def format_rfc822_date(dt):
    """Format datetime for RSS pubDate: RFC 822"""
    return dt.strftime('%a, %d %b %Y %H:%M:%S +0000')


# --- HTML Transformation Functions ---

def clean_html(html):
    """Clean Apple Notes HTML to standard HTML."""
    c = html
    
    # Replace <tt> with <code>
    c = re.sub(r'<tt>', '<code>', c)
    c = re.sub(r'</tt>', '</code>', c)
    
    # Remove Apple-dash-list class
    c = re.sub(r'<ul class="Apple-dash-list">', '<ul>', c)
    
    # Strip inline styles from table elements
    c = re.sub(r'<table[^>]*>', '<table>', c)
    c = re.sub(r'<td[^>]*>', '<td>', c)
    c = re.sub(r'<tr[^>]*>', '<tr>', c)
    c = re.sub(r'<tbody[^>]*>', '<tbody>', c)
    
    # Remove <object> wrappers
    c = re.sub(r'<object>', '', c)
    c = re.sub(r'</object>', '', c)
    
    # Convert divs to content with newlines
    c = re.sub(r'<div><br></div>', '\n', c)
    c = re.sub(r'<div>', '', c)
    c = re.sub(r'</div>', '\n', c)
    
    # Clean table cells
    c = re.sub(r'<td>\n*', '<td>', c)
    c = re.sub(r'\n*</td>', '</td>', c)
    
    # Convert <br> to newlines
    c = re.sub(r'<br>', '\n', c)
    
    # Clean up excess newlines
    c = re.sub(r'\n{3,}', '\n\n', c)
    
    return c.strip()


def wrap_paragraphs(html):
    """Wrap bare text in <p> tags, preserving block elements."""
    block_tags = re.compile(r'^<(h[1-6]|ul|ol|li|table|thead|tbody|tr|td|th|blockquote|pre|code|header|footer|article|section|nav|aside|figure|figcaption)', re.IGNORECASE)
    closing_block = re.compile(r'^</(h[1-6]|ul|ol|li|table|thead|tbody|tr|td|th|blockquote|pre|code|header|footer|article|section|nav|aside|figure|figcaption)', re.IGNORECASE)
    
    lines = html.split('\n')
    result = []
    in_block = 0
    buffer = []
    
    def flush_buffer():
        if buffer:
            text = ' '.join(buffer).strip()
            if text:
                result.append(f'<p>{text}</p>')
            buffer.clear()
    
    for line in lines:
        trimmed = line.strip()
        if not trimmed:
            flush_buffer()
            continue
        
        if block_tags.match(trimmed):
            flush_buffer()
            result.append(trimmed)
            if not re.search(r'</[^>]+>\s*$', trimmed):
                in_block += 1
        elif closing_block.match(trimmed):
            flush_buffer()
            result.append(trimmed)
            in_block = max(0, in_block - 1)
        elif in_block > 0:
            result.append(trimmed)
        else:
            buffer.append(trimmed)
    
    flush_buffer()
    return '\n'.join(result)


def resolve_links(html, note_lookup):
    """Replace [[Note Title]] with <a href="/slug.html">Note Title</a>"""
    def replace_link(match):
        title = match.group(1)
        if title in note_lookup:
            slug = note_lookup[title]['slug']
            return f'<a href="/{slug}.html">{title}</a>'
        else:
            print(f"Warning: Note not found: [[{title}]]", file=sys.stderr)
            return title
    
    return re.sub(r'\[\[([^\]]+)\]\]', replace_link, html)


def process_footnotes(html, slug):
    """Process footnote references and definitions."""
    definitions = {}
    
    # Extract footnote definitions: [^n]: text or [^n] text
    def extract_definition(match):
        num = match.group(1)
        text = match.group(2)
        definitions[num] = text.strip()
        return ''
    
    content = re.sub(r'^\[\^(\d+)\]:?\s+(.+?)$', extract_definition, html, flags=re.MULTILINE)
    
    # Replace footnote references [^n]
    def replace_reference(match):
        num = match.group(1)
        anchor_id = f"{slug}--footnote-{num}--anchor"
        target_id = f"{slug}--footnote-{num}"
        return f'<a id="{anchor_id}" href="#{target_id}"><sup>{num}</sup></a>'
    
    content = re.sub(r'\[\^(\d+)\]', replace_reference, content)
    
    # Build footer if there are definitions
    footer = ''
    if definitions:
        nums = sorted(definitions.keys(), key=int)
        footer = '<footer>\n<ol>\n'
        for num in nums:
            def_id = f"{slug}--footnote-{num}"
            anchor_id = f"{slug}--footnote-{num}--anchor"
            footer += f'<li id="{def_id}">{definitions[num]}<a href="#{anchor_id}">↩︎</a></li>\n'
        footer += '</ol>\n</footer>'
    
    return {'content': content.strip(), 'footer': footer}


# --- Template Engine ---

def load_template(template_dir, name):
    """Load template file."""
    template_path = Path(template_dir) / f"{name}.html"
    
    if name == 'feed':
        template_path = Path(template_dir) / "feed.xml"
    
    if not template_path.exists():
        print(f"Error: Template not found: {template_path}", file=sys.stderr)
        sys.exit(1)
    
    with open(template_path, 'r') as f:
        return f.read()


def render_template(template, variables):
    """Render template with {{variable}} substitution."""
    result = template
    for key, value in variables.items():
        result = result.replace(f'{{{{{key}}}}}', str(value))
    return result


# --- Note Lookup Builder ---

def build_note_lookup(notes):
    """Build title -> {slug, date} lookup for link resolution."""
    lookup = {}
    for note in notes:
        title = note['name']
        creation_date = note['creationDate']
        slug = generate_slug(title, creation_date)
        lookup[title] = {
            'slug': slug,
            'creationDate': creation_date
        }
    return lookup


# --- RSS Generation ---

def generate_rss_items(posts, site_url):
    """Generate RSS item elements for posts."""
    items = []
    
    # Take 30 most recent (same as index)
    recent_posts = sorted(posts, key=lambda p: p['creationDate'], reverse=True)[:30]
    
    for post in recent_posts:
        title = post['title']
        link = f"{site_url}/{post['slug']}.html"
        pub_date = format_rfc822_date(post['creationDate'])
        content = post['content']
        
        # Escape content for CDATA (just in case)
        content = content.replace(']]>', ']]]]><![CDATA[>')
        
        item = f'''<item>
  <title>{title}</title>
  <link>{link}</link>
  <pubDate>{pub_date}</pubDate>
  <description><![CDATA[{content}]]></description>
  <guid>{link}</guid>
</item>'''
        items.append(item)
    
    return '\n'.join(items)


# --- File Writing ---

def write_article(slug, content, output_dir):
    """Write article HTML to file, creating directories as needed."""
    filepath = Path(output_dir) / f"{slug}.html"
    filepath.parent.mkdir(parents=True, exist_ok=True)
    
    with open(filepath, 'w') as f:
        f.write(content)


def write_index(content, output_dir):
    """Write index.html to output directory."""
    filepath = Path(output_dir) / "index.html"
    
    with open(filepath, 'w') as f:
        f.write(content)


def write_feed(content, output_dir):
    """Write feed.xml to output directory."""
    filepath = Path(output_dir) / "feed.xml"
    
    with open(filepath, 'w') as f:
        f.write(content)


# --- Main Orchestration ---

def main():
    """Main entry point."""
    # Parse arguments
    parser = argparse.ArgumentParser(
        description='Export notes from Notes.app to static HTML blog'
    )
    parser.add_argument('--config', help='Path to config.json file')
    parser.add_argument('--folder', help='Notes folder name')
    parser.add_argument('--templates', help='Template directory path')
    parser.add_argument('--output', help='Output directory path')
    parser.add_argument('--site-url', help='Site URL for RSS feed')
    parser.add_argument('--site-title', help='Site title for RSS feed')
    parser.add_argument('--site-description', help='Site description for RSS feed')
    
    args = parser.parse_args()
    
    # Check dependencies
    check_dependencies()
    
    # Load configuration
    config = load_config(args.config, args)
    
    folder_name = config['notesFolderName']
    template_dir = config['templateDirectory']
    output_dir = config['outputDirectory']
    site_title = config['siteTitle']
    site_url = config['siteUrl']
    site_description = config['siteDescription']
    
    # Ensure output directory exists
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    
    # Load templates
    article_template = load_template(template_dir, 'article')
    snippet_template = load_template(template_dir, 'article-snippet')
    index_template = load_template(template_dir, 'index')
    feed_template = load_template(template_dir, 'feed')
    
    # Get notes from Notes.app
    notes = get_notes_from_folder(folder_name)
    
    if not notes:
        print(f"Error: Notes folder '{folder_name}' not found or empty", file=sys.stderr)
        sys.exit(1)
    
    # Build note lookup for link resolution
    note_lookup = build_note_lookup(notes)
    
    # Process each note
    posts = []
    
    for note in notes:
        title = note['name']
        creation_date = note['creationDate']
        slug = generate_slug(title, creation_date)
        datetime_str = format_datetime(creation_date)
        human_date = format_date(creation_date)
        
        # Transform content
        html = note['body']
        html = clean_html(html)
        
        # Remove first H1 (it's the title, already in header)
        html = re.sub(r'^<h1>[^<]*</h1>\n*', '', html)
        
        html = resolve_links(html, note_lookup)
        
        footnote_result = process_footnotes(html, slug)
        html = footnote_result['content']
        
        html = wrap_paragraphs(html)
        
        # Apply templates
        template_vars = {
            'title': title,
            'slug': slug,
            'datetime': datetime_str,
            'humanDate': human_date,
            'content': html,
            'footer': footnote_result['footer']
        }
        
        article_output = render_template(article_template, template_vars)
        snippet_output = render_template(snippet_template, template_vars)
        
        # Write article file
        write_article(slug, article_output, output_dir)
        
        # Store post data for index and RSS
        posts.append({
            'title': title,
            'slug': slug,
            'creationDate': creation_date,
            'humanDate': human_date,
            'content': html,
            'articleSnippet': snippet_output
        })
    
    # Generate index page
    posts_sorted = sorted(posts, key=lambda p: p['creationDate'], reverse=True)[:30]
    articles_html = '\n'.join([p['articleSnippet'] for p in posts_sorted])
    index_html = render_template(index_template, {'articles': articles_html})
    write_index(index_html, output_dir)
    
    # Generate RSS feed
    rss_items = generate_rss_items(posts, site_url)
    feed_vars = {
        'site_title': site_title,
        'site_url': site_url,
        'site_description': site_description,
        'items': rss_items
    }
    feed_xml = render_template(feed_template, feed_vars)
    write_feed(feed_xml, output_dir)
    
    # Success message
    print(f"Exported {len(posts)} posts")


if __name__ == '__main__':
    main()
