"""
Convert FHIR transaction bundles from PUT-with-id (updateCreate) style
to POST + urn:uuid fullUrl style with PROPER UUIDs.

The Prompt Opinion FHIR server does not support updateCreate operations.
Additionally, FHIR R4 spec requires fullUrl values in urn:uuid: form to be
ACTUAL UUIDs, not arbitrary text. HAPI FHIR validates this strictly and
can throw unhandled exceptions (502 Bad Gateway) on non-UUID values.

This script:
  1. Generates deterministic UUIDs for each resource (same input → same UUID)
  2. Uses those UUIDs as fullUrls
  3. Rewrites all references to use the new UUIDs
  4. Changes request.method to POST and strips IDs from resources

Deterministic UUIDs are used (uuid5 from a namespace + original-id) so that
re-running the script produces identical output. This makes the bundles
stable and reproducible for testing.
"""

import json
import uuid
from pathlib import Path


# Fixed namespace for deterministic UUID generation.
# Same original ID + same namespace = same UUID across runs.
SIGNALLOOP_NAMESPACE = uuid.UUID("6a4f4f74-7369-67e5-6c6c-6f6f7000b7fe")


def make_uuid(resource_type: str, original_id: str) -> str:
    """Generate a deterministic UUID for a resource."""
    name = f"{resource_type}/{original_id}"
    return str(uuid.uuid5(SIGNALLOOP_NAMESPACE, name))


def rewrite_references(obj, id_to_urn: dict[str, str]):
    """Recursively rewrite reference strings to urn:uuid form."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key == "reference" and isinstance(value, str):
                if value in id_to_urn:
                    obj[key] = id_to_urn[value]
            else:
                rewrite_references(value, id_to_urn)
    elif isinstance(obj, list):
        for item in obj:
            rewrite_references(item, id_to_urn)


def convert_bundle(bundle: dict) -> dict:
    """Convert a transaction bundle to POST + proper UUID fullUrl form."""
    if bundle.get("type") != "transaction":
        raise ValueError("Not a transaction bundle")

    entries = bundle.get("entry", [])

    # First pass: build mapping from old references to new urn:uuid values
    id_to_urn: dict[str, str] = {}
    entry_uuids: list[str | None] = []

    for entry in entries:
        resource = entry.get("resource", {})
        resource_type = resource.get("resourceType")
        resource_id = resource.get("id")

        if resource_type and resource_id:
            new_uuid = make_uuid(resource_type, resource_id)
            # Map "Patient/patient-margaret" → "urn:uuid:<real-uuid>"
            id_to_urn[f"{resource_type}/{resource_id}"] = f"urn:uuid:{new_uuid}"
            entry_uuids.append(new_uuid)
        else:
            entry_uuids.append(None)

    # Second pass: rewrite each entry
    new_entries = []
    for entry, new_uuid in zip(entries, entry_uuids):
        resource = entry.get("resource", {})
        resource_type = resource.get("resourceType")
        resource.pop("id", None)  # Remove id field — server will assign

        # Rewrite any references inside this resource
        rewrite_references(resource, id_to_urn)

        new_entry = {
            "resource": resource,
            "request": {
                "method": "POST",
                "url": resource_type,
            },
        }
        if new_uuid:
            new_entry["fullUrl"] = f"urn:uuid:{new_uuid}"

        new_entries.append(new_entry)

    return {
        "resourceType": "Bundle",
        "type": "transaction",
        "entry": new_entries,
    }


def convert_file(input_path: Path, output_path: Path):
    with open(input_path) as f:
        bundle = json.load(f)
    converted = convert_bundle(bundle)
    with open(output_path, "w") as f:
        json.dump(converted, f, indent=2)
    print(f"Converted: {input_path.name} → {output_path.name} ({len(converted['entry'])} entries)")


if __name__ == "__main__":
    bundles_dir = Path(__file__).parent
    files = [
        "patient-margaret.json",
        "patient-james.json",
        "patient-doris.json",
        "consult-return-nephrology.json",
    ]
    for filename in files:
        input_path = bundles_dir / filename
        output_path = bundles_dir / filename.replace(".json", "-post.json")
        convert_file(input_path, output_path)
