#!/usr/bin/env python3
"""Create a v2 self-contained Holographic Palette from a legacy recipe and library."""

import argparse
import json
import re
import time
import uuid
from copy import deepcopy
from pathlib import Path
from xml.etree import ElementTree as ET

import boto3
from boto3.dynamodb.conditions import Attr


def snapshot(cut):
    settings, sub_layers = {}, []
    for node in list(cut):
        if node.tag == "SubLayer":
            sub_layers.append(snapshot(node))
        elif node.get("Value") is not None:
            settings[str(node.tag)] = str(node.get("Value") or "")
    result = {"type": str(cut.get("type") or "Setting"), "settings": settings}
    if sub_layers:
        result["sub_layers"] = sub_layers
    return result


def named_entry(material, wanted):
    wanted = wanted.strip().casefold()
    for entry in material.findall("./Entry"):
        cut = entry.find("./CutSetting")
        cut_name = cut.find("./name") if cut is not None else None
        names = {
            str(entry.get("Desc") or "").strip().casefold(),
            str(cut_name.get("Value") if cut_name is not None else "").strip().casefold(),
        }
        if wanted in names and cut is not None:
            return entry
    return None


def selected_material(root, wanted):
    wanted = wanted.strip().casefold()
    exact = [item for item in root.findall("./Material") if str(item.get("name") or "").strip().casefold() == wanted]
    if exact:
        return exact[0]
    materials = root.findall("./Material")
    return materials[0] if len(materials) == 1 else None


def safe_name(value):
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-._") or "holographic-recipe"


def assets(table):
    result, kwargs = [], {"FilterExpression": Attr("sk").begins_with("MATERIAL#") | Attr("sk").begins_with("HOLORECIPE#")}
    while True:
        page = table.scan(**kwargs)
        result.extend(page.get("Items") or [])
        if "LastEvaluatedKey" not in page:
            return result
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default="mopa-admin")
    parser.add_argument("--region", default="us-east-2")
    parser.add_argument("--table", required=True)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--owner")
    parser.add_argument("--source-recipe-id")
    parser.add_argument("--library-id")
    parser.add_argument("--rename-record-id")
    parser.add_argument("--inspect-library-id")
    parser.add_argument("--material", default="Stainless")
    parser.add_argument("--setting", default="holographic-etching")
    parser.add_argument("--name")
    args = parser.parse_args()

    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    table = session.resource("dynamodb").Table(args.table)
    s3 = session.client("s3")
    records = assets(table)
    if args.list:
        for item in sorted(records, key=lambda row: (str(row.get("pk")), str(row.get("sk")))):
            print(json.dumps({
                "owner": str(item.get("pk") or "").removeprefix("USER#"),
                "kind": "recipe" if str(item.get("sk") or "").startswith("HOLORECIPE#") else "material",
                "id": str(item.get("recipe_id") or item.get("library_id") or ""),
                "name": str(item.get("name") or ""),
                "created_at": int(item.get("created_at") or 0),
                "metadata": item.get("metadata") or {},
            }, default=str))
        return

    if args.rename_record_id:
        if not args.owner or not args.name:
            parser.error("--owner and --name are required with --rename-record-id")
        key = {"pk": f"USER#{args.owner}", "sk": f"HOLORECIPE#{args.rename_record_id}"}
        record = table.get_item(Key=key, ConsistentRead=True).get("Item")
        if not record:
            raise SystemExit("The recipe record to rename was not found")
        profile = json.loads(s3.get_object(Bucket=args.bucket, Key=record["s3_key"])["Body"].read())
        profile["profile_name"] = args.name
        s3.put_object(Bucket=args.bucket, Key=record["s3_key"], Body=json.dumps(profile, indent=2).encode(), ContentType="application/json")
        metadata = dict(record.get("metadata") or {})
        metadata["profile_name"] = args.name
        table.update_item(Key=key, UpdateExpression="SET #name=:name, metadata=:metadata, updated_at=:now",
                          ExpressionAttributeNames={"#name":"name"},
                          ExpressionAttributeValues={":name":args.name, ":metadata":metadata, ":now":int(time.time())})
        print(json.dumps({"recipe_id":args.rename_record_id, "name":args.name, "renamed":True}))
        return

    if args.inspect_library_id:
        if not args.owner:
            parser.error("--owner is required with --inspect-library-id")
        record = table.get_item(Key={"pk":f"USER#{args.owner}", "sk":f"MATERIAL#{args.inspect_library_id}"}, ConsistentRead=True).get("Item")
        if not record:
            raise SystemExit("The Material Library to inspect was not found")
        source = s3.get_object(Bucket=args.bucket, Key=record["s3_key"])["Body"].read()
        root = ET.fromstring(source)
        material = selected_material(root, args.material)
        entry = named_entry(material, args.setting) if material is not None else None
        if entry is None:
            raise SystemExit(f"Setting {args.setting!r} was not found")
        summary_entry = next((item for item in (record.get("summary") or {}).get("entries") or []
                              if str(item.get("description") or "").strip().casefold() == args.setting.strip().casefold()), None)
        print(json.dumps({
            "record_name":record.get("name"), "original_name":record.get("original_name"),
            "s3_key":record.get("s3_key"), "selected_material":material.get("name"),
            "entry_description":entry.get("Desc"), "dynamodb_summary":summary_entry,
            "source_cut_setting":snapshot(entry.find("./CutSetting")),
        }, indent=2, default=str))
        return

    required = (args.owner, args.source_recipe_id, args.library_id, args.name)
    if not all(required):
        parser.error("--owner, --source-recipe-id, --library-id, and --name are required unless --list is used")
    owner_key = f"USER#{args.owner}"
    source_record = table.get_item(Key={"pk": owner_key, "sk": f"HOLORECIPE#{args.source_recipe_id}"}, ConsistentRead=True).get("Item")
    library_record = table.get_item(Key={"pk": owner_key, "sk": f"MATERIAL#{args.library_id}"}, ConsistentRead=True).get("Item")
    if not source_record or not library_record:
        raise SystemExit("The selected source recipe or Material Library was not found for that owner")

    source_profile = json.loads(s3.get_object(Bucket=args.bucket, Key=source_record["s3_key"])["Body"].read())
    library_root = ET.fromstring(s3.get_object(Bucket=args.bucket, Key=library_record["s3_key"])["Body"].read())
    material = selected_material(library_root, args.material)
    if material is None:
        raise SystemExit(f"Material {args.material!r} was not found unambiguously")
    base_entry = named_entry(material, args.setting)
    if base_entry is None:
        raise SystemExit(f"Setting {args.setting!r} was not found in material {args.material!r}")
    black_entry = named_entry(material, "Black")
    base_cut = base_entry.find("./CutSetting")
    recipes = []
    sweep_fields = {"power":"maxPower", "speed":"speed", "frequency":"frequency", "pulse_width":"QPulseWidth", "passes":"numPasses"}
    for measured in source_profile.get("recipes") or []:
        item, cut = deepcopy(measured), deepcopy(base_cut)
        for tag, value in (("interval", item.get("interval_mm")), ("angle", item.get("angle_degrees"))):
            node = cut.find(f"./{tag}")
            if node is None:
                node = ET.SubElement(cut, tag)
            node.set("Value", f"{float(value):g}")
        override = item.get("laser_setting_override") or {}
        field_name = sweep_fields.get(override.get("parameter"))
        if field_name and override.get("value") is not None:
            node = cut.find(f"./{field_name}")
            if node is None:
                node = ET.SubElement(cut, field_name)
            node.set("Value", f"{float(override['value']):g}")
        item["laser_settings"] = snapshot(cut)
        recipes.append(item)
    if not recipes:
        raise SystemExit("The source profile has no measured recipes")

    recipe_id, now = str(uuid.uuid4()), int(time.time())
    black_setting = None if black_entry is None else {
        "name": "Black", "description": str(black_entry.get("Desc") or "Black"),
        "laser_settings": snapshot(black_entry.find("./CutSetting")),
    }
    profile = deepcopy(source_profile)
    profile.update({
        "kind": "holographic_calibration_profile", "schema_version": 2,
        "status": "recipe_palette_ready", "self_contained": True,
        "profile_id": recipe_id, "profile_name": args.name,
        "black_setting": black_setting, "recipes": recipes,
    })
    profile.setdefault("grid", {}).update({
        "material": args.material, "setting_description": args.setting,
        "source_library_id": args.library_id, "embedded_black_setting": black_setting,
    })
    filename = f"{safe_name(args.name)}.json"
    key = f"users/{args.owner}/holographic-recipes/{recipe_id}/{filename}"
    body = json.dumps(profile, indent=2).encode()
    s3.put_object(Bucket=args.bucket, Key=key, Body=body, ContentType="application/json")
    table.put_item(Item={
        "pk": owner_key, "sk": f"HOLORECIPE#{recipe_id}", "recipe_id": recipe_id,
        "name": args.name, "original_name": filename, "s3_key": key,
        "metadata": {"profile_name": args.name, "recipe_count": len(recipes),
                     "material": args.material, "schema_version": 2,
                     "self_contained": True, "has_black_setting": bool(black_setting)},
        "created_at": now, "updated_at": now,
    }, ConditionExpression="attribute_not_exists(pk)")
    print(json.dumps({"recipe_id": recipe_id, "name": args.name, "recipe_count": len(recipes),
                      "has_black_setting": bool(black_setting), "s3_key": key}))


if __name__ == "__main__":
    main()
