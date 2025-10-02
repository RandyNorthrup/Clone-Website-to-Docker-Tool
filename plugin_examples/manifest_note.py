"""Example plugin: append a custom note into the manifest.

Demonstrates the `finalize` hook. Adds/merges a `custom_notes` list in the
manifest (creating it if missing) so downstream tooling can detect plugin
contributions.
"""
from datetime import datetime, timezone

def finalize(output_folder, manifest_dict, context):  # legacy expanded signature
    try:
        notes = manifest_dict.setdefault('custom_notes', [])
        notes.append({
            'added_by': 'manifest_note_plugin',
            'utc': datetime.now(timezone.utc).isoformat(),
            'message': 'Example finalize hook executed.'
        })
    except Exception:
        pass
