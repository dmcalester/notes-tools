#!/usr/bin/env python3

"""
Query Apple Notes SQLite database directly.

This script reads notes from the Notes.app SQLite database, extracting
note content and metadata. The note body is stored as gzip-compressed
protobuf data which we parse to extract text and formatting information.
"""

import argparse
import gzip
import json
import os
import sqlite3
import struct
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Apple's Core Data timestamp epoch (Jan 1, 2001)
APPLE_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)

# Notes database path
NOTES_DB_PATH = os.path.expanduser(
    "~/Library/Group Containers/group.com.apple.notes/NoteStore.sqlite"
)


def load_config(config_path=None):
    """Load configuration from file."""
    config = {
        "notesFolderName": "test",
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

    return config


def apple_timestamp_to_datetime(timestamp: float) -> datetime:
    """Convert Apple Core Data timestamp to datetime."""
    if timestamp is None:
        return None
    from datetime import timedelta

    return APPLE_EPOCH + timedelta(seconds=timestamp)


# Paragraph style types (from protobuf attribute a1)
PARA_STYLE_NORMAL = 0
PARA_STYLE_HEADING = 1  # "Heading" in Notes UI - maps to H1
PARA_STYLE_SUBHEADING = 2  # "Subheading" in Notes UI - maps to H2
PARA_STYLE_MONO = 4  # "Monospaced" in Notes UI - maps to <code>
PARA_STYLE_BULLET_LIST = 100  # Bulleted list (•)
PARA_STYLE_DASH_LIST = 101  # Dashed list (-)
PARA_STYLE_NUMBER_LIST = 102  # Numbered list (1. 2. 3.)

# Text style values (from protobuf field 5 at style run level)
TEXT_STYLE_NORMAL = 0
TEXT_STYLE_BOLD = 1
TEXT_STYLE_ITALIC = 2


@dataclass
class StyleRun:
    """A run of text with associated formatting."""

    start: int
    length: int
    text: str
    # Formatting attributes
    paragraph_style: int = 0  # PARA_STYLE_* constants
    text_style: int = 0  # TEXT_STYLE_* (bold/italic)
    is_blockquote: bool = False
    is_superscript: bool = False  # Field 8 at style run level
    is_underline: bool = False
    is_strikethrough: bool = False
    link_url: Optional[str] = None

    @property
    def is_bold(self) -> bool:
        return self.text_style == TEXT_STYLE_BOLD

    @property
    def is_italic(self) -> bool:
        return self.text_style == TEXT_STYLE_ITALIC

    @property
    def style_name(self) -> str:
        """Human-readable paragraph style name."""
        names = {
            PARA_STYLE_HEADING: "heading",
            PARA_STYLE_SUBHEADING: "subheading",
            PARA_STYLE_MONO: "monospace",
            PARA_STYLE_BULLET_LIST: "bullet-list",
            PARA_STYLE_DASH_LIST: "dash-list",
            PARA_STYLE_NUMBER_LIST: "number-list",
        }
        return names.get(self.paragraph_style, "normal")


@dataclass
class NoteLink:
    """An internal link to another note."""

    url: str  # applenotes:note/UUID?ownerIdentifier=...
    note_id: str  # UUID portion
    text: str = ""  # The linked text


@dataclass
class ParsedNote:
    """Parsed note content with extracted formatting."""

    title: str
    text_content: str
    style_runs: list  # List of StyleRun with formatting info
    note_links: list  # List of NoteLink (internal links)
    raw_data: bytes


class ProtobufParser:
    """Simple protobuf wire format parser for Notes data."""

    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def read_varint(self) -> int:
        """Read a variable-length integer."""
        result = 0
        shift = 0
        while True:
            if self.pos >= len(self.data):
                raise ValueError("Unexpected end of data while reading varint")
            byte = self.data[self.pos]
            self.pos += 1
            result |= (byte & 0x7F) << shift
            if (byte & 0x80) == 0:
                break
            shift += 7
        return result

    def read_bytes(self, length: int) -> bytes:
        """Read a fixed number of bytes."""
        if self.pos + length > len(self.data):
            raise ValueError("Unexpected end of data while reading bytes")
        result = self.data[self.pos : self.pos + length]
        self.pos += length
        return result

    def read_field(self):
        """Read a protobuf field (tag + value)."""
        if self.pos >= len(self.data):
            return None, None, None

        tag_wire = self.read_varint()
        field_number = tag_wire >> 3
        wire_type = tag_wire & 0x07

        if wire_type == 0:  # Varint
            value = self.read_varint()
        elif wire_type == 1:  # 64-bit
            value = struct.unpack("<Q", self.read_bytes(8))[0]
        elif wire_type == 2:  # Length-delimited
            length = self.read_varint()
            value = self.read_bytes(length)
        elif wire_type == 5:  # 32-bit
            value = struct.unpack("<I", self.read_bytes(4))[0]
        else:
            raise ValueError(f"Unknown wire type: {wire_type}")

        return field_number, wire_type, value

    def parse_all(self) -> list:
        """Parse all fields from the data."""
        fields = []
        while self.pos < len(self.data):
            try:
                field_num, wire_type, value = self.read_field()
                if field_num is None:
                    break
                fields.append((field_num, wire_type, value))
            except ValueError:
                break
        return fields


def extract_strings_from_protobuf(data: bytes) -> list:
    """Extract all string fields from protobuf data recursively."""
    strings = []

    def try_parse(d: bytes, depth=0):
        if depth > 10 or len(d) < 2:
            return
        try:
            parser = ProtobufParser(d)
            fields = parser.parse_all()
            for field_num, wire_type, value in fields:
                if wire_type == 2 and isinstance(value, bytes):
                    # Try to decode as UTF-8 string
                    try:
                        s = value.decode("utf-8")
                        if (
                            s
                            and len(s) > 0
                            and all(c.isprintable() or c in "\n\t" for c in s)
                        ):
                            strings.append((field_num, s))
                    except UnicodeDecodeError:
                        pass
                    # Recursively parse nested messages
                    try_parse(value, depth + 1)
        except (ValueError, struct.error):
            pass

    try_parse(data)
    return strings


def parse_all_fields(data: bytes) -> list:
    """Parse all protobuf fields from data."""
    parser = ProtobufParser(data)
    return parser.parse_all()


def get_note_content_fields(data: bytes):
    """
    Navigate to the note content section of the protobuf.

    Structure:
    - Field 1: version (varint)
    - Field 2: Document message containing:
      - Field 1: version (varint)
      - Field 2: unused (varint)
      - Field 3: Note content message

    Returns the parsed fields of the Note content message.
    """
    root_fields = parse_all_fields(data)

    # Find field 2 (Document)
    for field_num, wire_type, value in root_fields:
        if field_num == 2 and wire_type == 2:
            doc_fields = parse_all_fields(value)

            # Find field 3 (Note content)
            for doc_field_num, doc_wire_type, doc_value in doc_fields:
                if doc_field_num == 3 and doc_wire_type == 2:
                    return parse_all_fields(doc_value)
    return []


def extract_main_text(data: bytes) -> str:
    """Extract the main text content from Notes protobuf."""
    note_fields = get_note_content_fields(data)

    for field_num, wire_type, value in note_fields:
        if field_num == 2 and wire_type == 2:
            try:
                return value.decode("utf-8")
            except UnicodeDecodeError:
                pass
    return ""


def extract_style_runs(data: bytes, text: str) -> list:
    """
    Extract formatting/style runs from Notes protobuf.

    Style information is in Field 5 of the note content.
    Each style run contains:
    - Field 1: length of this run
    - Field 2: character attributes
      - a1: paragraph style (title, heading, list type, etc.)
      - a8: blockquote flag
    - Field 5: text style (1=bold, 2=italic)
    - Field 9: link URL
    """
    note_fields = get_note_content_fields(data)

    style_runs = []
    pos = 0

    for field_num, wire_type, value in note_fields:
        if field_num == 5 and wire_type == 2:
            style_fields = parse_all_fields(value)

            run = {
                "length": 0,
                "para_style": 0,
                "text_style": 0,
                "is_blockquote": False,
                "is_superscript": False,
                "is_underline": False,
                "is_strikethrough": False,
                "link_url": None,
            }

            for sfn, swt, sval in style_fields:
                if sfn == 1:  # Length
                    run["length"] = sval
                elif sfn == 2:  # Character attributes
                    attrs = parse_all_fields(sval)
                    for afn, awt, aval in attrs:
                        if afn == 1:  # Paragraph style type
                            run["para_style"] = aval
                        elif afn == 5:  # Underline
                            run["is_underline"] = bool(aval)
                        elif afn == 6:  # Strikethrough
                            run["is_strikethrough"] = bool(aval)
                        elif afn == 8:  # Blockquote flag
                            run["is_blockquote"] = bool(aval)
                elif sfn == 5:  # Text style (bold/italic)
                    run["text_style"] = sval
                elif sfn == 8:  # Superscript (at style run level, not inside a2)
                    run["is_superscript"] = bool(sval)
                elif sfn == 9:  # Link URL
                    if isinstance(sval, bytes):
                        try:
                            run["link_url"] = sval.decode("utf-8")
                        except UnicodeDecodeError:
                            pass

            length = run["length"]
            if length > 0 and pos < len(text):
                run_text = text[pos : pos + length]
                style_runs.append(
                    StyleRun(
                        start=pos,
                        length=length,
                        text=run_text,
                        paragraph_style=run["para_style"],
                        text_style=run["text_style"],
                        is_blockquote=run["is_blockquote"],
                        is_superscript=run["is_superscript"],
                        is_underline=run["is_underline"],
                        is_strikethrough=run["is_strikethrough"],
                        link_url=run["link_url"],
                    )
                )
                pos += length

    return style_runs


def parse_note_content(compressed_data: bytes) -> ParsedNote:
    """Parse the gzip-compressed protobuf note content."""
    try:
        data = gzip.decompress(compressed_data)
    except gzip.BadGzipFile:
        return ParsedNote(
            title="",
            text_content="",
            style_runs=[],
            note_links=[],
            raw_data=compressed_data,
        )

    # Extract main text content using proper protobuf structure
    text_content = extract_main_text(data)

    # Split into title (first line) and body
    lines = text_content.split("\n", 1)
    title = lines[0] if lines else ""
    body = lines[1] if len(lines) > 1 else ""

    # Extract style runs with formatting info
    style_runs = extract_style_runs(data, text_content)

    # Find note links from style runs (more accurate than string search)
    note_links = []
    for run in style_runs:
        if run.link_url and run.link_url.startswith("applenotes:note/"):
            parts = run.link_url.split("?")[0].split("/")
            if len(parts) >= 2:
                note_id = parts[-1]
                note_links.append(
                    NoteLink(url=run.link_url, note_id=note_id, text=run.text)
                )

    return ParsedNote(
        title=title,
        text_content=body,
        style_runs=style_runs,
        note_links=note_links,
        raw_data=data,
    )


def get_folder_id(conn: sqlite3.Connection, folder_name: str) -> Optional[int]:
    """Find the folder ID (Z_PK) for a folder by name."""
    cursor = conn.cursor()
    # Folders have ZTITLE2 set to the folder name
    cursor.execute(
        "SELECT Z_PK FROM ZICCLOUDSYNCINGOBJECT WHERE ZTITLE2 = ?", (folder_name,)
    )
    row = cursor.fetchone()
    return row[0] if row else None


def get_notes_from_folder(conn: sqlite3.Connection, folder_id: int) -> list:
    """Fetch all notes from a folder by folder ID."""
    cursor = conn.cursor()

    # Query notes and join with note data
    cursor.execute(
        """
        SELECT
            n.Z_PK,
            n.ZIDENTIFIER,
            n.ZTITLE1,
            n.ZSNIPPET,
            n.ZCREATIONDATE3,
            n.ZMODIFICATIONDATE1,
            n.ZNOTEDATA,
            nd.ZDATA
        FROM ZICCLOUDSYNCINGOBJECT n
        LEFT JOIN ZICNOTEDATA nd ON nd.Z_PK = n.ZNOTEDATA
        WHERE n.ZFOLDER = ?
        ORDER BY n.ZMODIFICATIONDATE1 DESC
    """,
        (folder_id,),
    )

    notes = []
    for row in cursor.fetchall():
        z_pk, identifier, title, snippet, creation_ts, mod_ts, notedata_pk, raw_data = (
            row
        )

        # Parse timestamps
        creation_date = apple_timestamp_to_datetime(creation_ts)
        modification_date = apple_timestamp_to_datetime(mod_ts)

        # Parse note content if available
        parsed = None
        if raw_data:
            parsed = parse_note_content(raw_data)

        notes.append(
            {
                "id": z_pk,
                "identifier": identifier,
                "title": title or (parsed.title if parsed else ""),
                "snippet": snippet,
                "creation_date": creation_date,
                "modification_date": modification_date,
                "parsed_content": parsed,
            }
        )

    return notes


def print_note_summary(note: dict, show_formatting: bool = False):
    """Print a summary of a note."""
    print(f"\n{'=' * 60}")
    print(f"Title: {note['title']}")
    print(f"ID: {note['identifier']}")
    print(f"Created: {note['creation_date']}")
    print(f"Modified: {note['modification_date']}")
    print(f"-" * 60)

    if note["parsed_content"]:
        parsed = note["parsed_content"]
        print(f"Text Content Preview:")
        # Show first 500 chars
        preview = parsed.text_content[:500]
        if len(parsed.text_content) > 500:
            preview += "..."
        print(preview)

        if parsed.note_links:
            print(f"\nInternal Links:")
            for link in parsed.note_links:
                print(f"  - [{link.text}] -> {link.note_id}")

        if show_formatting and parsed.style_runs:
            print(f"\nFormatting Runs:")
            for run in parsed.style_runs:
                attrs = []
                if run.paragraph_style != PARA_STYLE_NORMAL:
                    attrs.append(run.style_name)
                if run.is_blockquote:
                    attrs.append("blockquote")
                if run.is_bold:
                    attrs.append("bold")
                if run.is_italic:
                    attrs.append("italic")
                if run.is_superscript:
                    attrs.append("superscript")
                if run.is_underline:
                    attrs.append("underline")
                if run.is_strikethrough:
                    attrs.append("strikethrough")
                if run.link_url:
                    url = (
                        run.link_url[:40] + "..."
                        if len(run.link_url) > 40
                        else run.link_url
                    )
                    attrs.append(f"link:{url}")

                if attrs:
                    text_preview = run.text[:30].replace("\n", "\\n")
                    print(
                        f"  [{run.start}:{run.start + run.length}] {', '.join(attrs)}"
                    )
                    print(f'    "{text_preview}"')
    else:
        print(f"Snippet: {note['snippet']}")


def export_notes_json(notes: list, output_path: str, include_formatting: bool = False):
    """Export notes to JSON file."""
    output = []
    for note in notes:
        entry = {
            "id": note["id"],
            "identifier": note["identifier"],
            "title": note["title"],
            "snippet": note["snippet"],
            "creation_date": note["creation_date"].isoformat()
            if note["creation_date"]
            else None,
            "modification_date": note["modification_date"].isoformat()
            if note["modification_date"]
            else None,
        }
        if note["parsed_content"]:
            parsed = note["parsed_content"]
            entry["text_content"] = parsed.text_content
            entry["note_links"] = [
                {"url": link.url, "note_id": link.note_id, "text": link.text}
                for link in parsed.note_links
            ]

            if include_formatting:
                entry["style_runs"] = [
                    {
                        "start": run.start,
                        "length": run.length,
                        "text": run.text,
                        "style": run.style_name,
                        "is_blockquote": run.is_blockquote,
                        "is_bold": run.is_bold,
                        "is_italic": run.is_italic,
                        "is_superscript": run.is_superscript,
                        "is_underline": run.is_underline,
                        "is_strikethrough": run.is_strikethrough,
                        "link_url": run.link_url,
                    }
                    for run in parsed.style_runs
                    if (
                        run.paragraph_style != PARA_STYLE_NORMAL
                        or run.is_blockquote
                        or run.text_style
                        or run.is_superscript
                        or run.is_underline
                        or run.is_strikethrough
                        or run.link_url
                    )
                ]
        output.append(entry)

    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"Exported {len(notes)} notes to {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Query Apple Notes SQLite database directly"
    )
    parser.add_argument("--config", help="Path to config.json file")
    parser.add_argument("--folder", help="Notes folder name (overrides config)")
    parser.add_argument("--output", "-o", help="Output JSON file path")
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Print detailed note content"
    )
    parser.add_argument(
        "--formatting",
        "-f",
        action="store_true",
        help="Include formatting/style information in output",
    )

    args = parser.parse_args()

    # Load configuration
    config = load_config(args.config)
    folder_name = args.folder or config["notesFolderName"]

    # Check database exists
    if not os.path.exists(NOTES_DB_PATH):
        print(f"Error: Notes database not found at {NOTES_DB_PATH}")
        return 1

    # Connect to database (read-only)
    conn = sqlite3.connect(f"file:{NOTES_DB_PATH}?mode=ro", uri=True)

    try:
        # Find folder
        folder_id = get_folder_id(conn, folder_name)
        if folder_id is None:
            print(f"Error: Folder '{folder_name}' not found")
            return 1

        print(f"Found folder '{folder_name}' (ID: {folder_id})")

        # Get notes
        notes = get_notes_from_folder(conn, folder_id)
        print(f"Found {len(notes)} notes")

        # Output
        if args.output:
            export_notes_json(notes, args.output, include_formatting=args.formatting)
        elif args.verbose:
            for note in notes:
                print_note_summary(note, show_formatting=args.formatting)
        else:
            # Brief listing
            for note in notes:
                date_str = (
                    note["modification_date"].strftime("%Y-%m-%d")
                    if note["modification_date"]
                    else "Unknown"
                )
                print(f"  [{date_str}] {note['title']}")
                if note["parsed_content"] and note["parsed_content"].note_links:
                    for link in note["parsed_content"].note_links:
                        print(f"             -> links to: {link.note_id}")

    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    exit(main())
